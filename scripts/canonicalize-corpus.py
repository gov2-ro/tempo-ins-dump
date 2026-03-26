#!/usr/bin/env python3
"""
Phase 2: Establish canonical corpus.

Steps:
  2a. Convert 414 v2-only sub-datasets to v3 format
  2b. Adopt 348 orphan parquets into dataset_splits
  2c. Mark is_canonical on matrices table + create view
  2d. Move parent parquets to _parents/ archive
  2e. Clean orphaned view profiles

Usage:
    python scripts/canonicalize-corpus.py                # full run
    python scripts/canonicalize-corpus.py --dry-run      # report only
    python scripts/canonicalize-corpus.py --step 2a      # single step
    python scripts/canonicalize-corpus.py --debug        # verbose
"""
import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
from duckdb_config import DB_FILE, PARQUET_V2_DIR, PARQUET_COMPRESSION, DATA_DIR

PARQUET_V3_DIR = DATA_DIR / "parquet-v3" / "ro"
PARENTS_DIR = PARQUET_V3_DIR / "_parents"
VP_DIR = DATA_DIR / "view-profiles"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Step 2a: Convert v2-only splits to v3 ────────────────────────────────────

def step_2a_convert_v2_splits(conn, dry_run=False):
    """Convert sub-datasets that only exist in v2 to SDMX v3 format."""
    log.info("═══ Step 2a: Convert v2-only splits to v3 ═══")

    v3_codes = {f.stem for f in PARQUET_V3_DIR.glob("*.parquet")}

    # Find v2-only splits
    splits = conn.execute("""
        SELECT sub_matrix_code, parent_matrix_code FROM dataset_splits
    """).fetchall()

    v2_only = [(sub, parent) for sub, parent in splits if sub not in v3_codes]
    log.info(f"  Found {len(v2_only)} v2-only splits to convert")

    if dry_run or not v2_only:
        return len(v2_only)

    # Build lookup tables (same as 12-parquet-to-sdmx.py)
    id_to_value = {}
    for nom_id, val in conn.execute("SELECT nom_item_id, sdmx_value FROM sdmx_codes").fetchall():
        id_to_value[nom_id] = val
    log.info(f"  ID→value lookup: {len(id_to_value):,} entries")

    # Column map: include both parent and sub-dataset entries
    col_map = {}
    for mc, old, new in conn.execute(
        "SELECT matrix_code, old_column_name, sdmx_column_name FROM sdmx_column_map"
    ).fetchall():
        col_map.setdefault(mc, {})[old] = new

    success = 0
    errors = 0
    t0 = time.time()

    for i, (sub_code, parent_code) in enumerate(v2_only, 1):
        src = PARQUET_V2_DIR / f"{sub_code}.parquet"
        dst = PARQUET_V3_DIR / f"{sub_code}.parquet"

        if not src.exists():
            log.warning(f"  [{sub_code}] v2 file not found")
            errors += 1
            continue

        # Use sub-dataset's own column map, fall back to parent's
        rename = col_map.get(sub_code) or col_map.get(parent_code)
        if not rename:
            log.warning(f"  [{sub_code}] No column map (self or parent {parent_code})")
            errors += 1
            continue

        try:
            df = conn.execute(f"SELECT * FROM read_parquet('{src}')").fetchdf()
            if len(df) == 0:
                log.warning(f"  [{sub_code}] Empty parquet")
                errors += 1
                continue

            # Convert nomItemId integers → string values
            for col in list(df.columns):
                if col == "value":
                    continue
                df[col] = df[col].map(
                    lambda v: id_to_value.get(int(v), str(v))
                    if v is not None and not (hasattr(v, '__class__') and v.__class__.__name__ == 'NAType')
                    else None
                )

            # Rename columns using parent map (sub-dataset has subset of columns)
            new_columns = {}
            for col in df.columns:
                new_columns[col] = rename.get(col, col)
            df = df.rename(columns=new_columns)

            conn.execute(f"""
                COPY (SELECT * FROM df)
                TO '{dst}'
                (FORMAT PARQUET, COMPRESSION '{PARQUET_COMPRESSION}')
            """)
            success += 1

        except Exception as e:
            log.warning(f"  [{sub_code}] Error: {e}")
            errors += 1

        if i % 100 == 0:
            log.info(f"  Progress: {i}/{len(v2_only)} ({success} ok, {errors} err)")

    elapsed = time.time() - t0
    log.info(f"  Done: {success} converted, {errors} errors in {elapsed:.1f}s")
    return success


# ── Step 2b: Adopt orphan parquets ───────────────────────────────────────────

def step_2b_adopt_orphans(conn, dry_run=False):
    """Register orphan v3 parquets in dataset_splits and matrices."""
    log.info("═══ Step 2b: Adopt orphan parquets ═══")

    matrix_codes = {r[0] for r in conn.execute("SELECT matrix_code FROM matrices").fetchall()}
    split_codes = {r[0] for r in conn.execute("SELECT sub_matrix_code FROM dataset_splits").fetchall()}
    v3_codes = {f.stem for f in PARQUET_V3_DIR.glob("*.parquet")}

    orphans = v3_codes - matrix_codes - split_codes
    log.info(f"  Found {len(orphans)} orphan parquets")

    if dry_run or not orphans:
        return len(orphans)

    adopted = 0
    for code in sorted(orphans):
        base = code.split("_")[0]
        if base not in matrix_codes:
            log.warning(f"  [{code}] No parent {base} in matrices — skipping")
            continue

        suffix = code[len(base) + 1:]  # everything after "BASE_"
        parquet_path = str(PARQUET_V3_DIR / f"{code}.parquet")

        # Count rows
        try:
            row_count = conn.execute(
                f"SELECT COUNT(*) FROM read_parquet('{parquet_path}')"
            ).fetchone()[0]
        except Exception:
            row_count = 0

        # Determine split pattern from suffix
        pattern = "unknown"
        if any(g in suffix for g in ["judete", "regiuni", "macroregiuni"]):
            pattern = "geo_hierarchy"
        elif any(g in suffix for g in ["localitate", "judet"]):
            pattern = "hierarchy"
        elif any(g in suffix for g in ["anual", "trimestrial", "lunar"]):
            pattern = "mixed_time_granularity"

        # Insert into dataset_splits
        try:
            conn.execute("""
                INSERT INTO dataset_splits (
                    parent_matrix_code, sub_matrix_code, split_pattern,
                    suffix_label, parquet_path, row_count, display_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [base, code, pattern, suffix, parquet_path, row_count, f"{base} ({suffix})"])
            adopted += 1
        except Exception as e:
            log.warning(f"  [{code}] Insert error: {e}")

        # Also insert into matrices if not already there
        if code not in matrix_codes:
            try:
                # Copy basic info from parent
                parent = conn.execute(
                    "SELECT matrix_name, context_code FROM matrices WHERE matrix_code = ?",
                    [base]
                ).fetchone()
                if parent:
                    conn.execute("""
                        INSERT INTO matrices (matrix_code, matrix_name, context_code,
                                            is_split, parent_matrix_code, parquet_path, row_count)
                        VALUES (?, ?, ?, TRUE, ?, ?, ?)
                    """, [code, f"{parent[0]} ({suffix})", parent[1],
                          base, parquet_path, row_count])
            except Exception as e:
                log.warning(f"  [{code}] matrices insert error: {e}")

    log.info(f"  Adopted {adopted} orphans into dataset_splits + matrices")
    return adopted


# ── Step 2c: Mark canonical datasets ─────────────────────────────────────────

def step_2c_mark_canonical(conn, dry_run=False):
    """Add is_canonical column and create v_canonical_datasets view."""
    log.info("═══ Step 2c: Mark canonical datasets ═══")

    # Check if column already exists
    cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'matrices'"
    ).fetchall()}

    if "is_canonical" not in cols:
        if dry_run:
            log.info("  Would add is_canonical column")
        else:
            conn.execute("ALTER TABLE matrices ADD COLUMN is_canonical BOOLEAN DEFAULT TRUE")
            log.info("  Added is_canonical column")

    if dry_run:
        # Just count what would happen
        parent_codes = conn.execute("""
            SELECT COUNT(DISTINCT parent_matrix_code) FROM dataset_splits
        """).fetchone()[0]
        log.info(f"  Would mark {parent_codes} parents as non-canonical")
        return

    # Parents that were split → NOT canonical
    conn.execute("""
        UPDATE matrices SET is_canonical = FALSE
        WHERE matrix_code IN (SELECT DISTINCT parent_matrix_code FROM dataset_splits)
    """)
    non_canonical = conn.execute("SELECT COUNT(*) FROM matrices WHERE is_canonical = FALSE").fetchone()[0]
    canonical = conn.execute("SELECT COUNT(*) FROM matrices WHERE is_canonical = TRUE").fetchone()[0]
    log.info(f"  Canonical: {canonical}, Non-canonical (parents): {non_canonical}")

    # Create view
    try:
        conn.execute("DROP VIEW IF EXISTS v_canonical_datasets")
        conn.execute("""
            CREATE VIEW v_canonical_datasets AS
            SELECT * FROM matrices WHERE is_canonical = TRUE
        """)
        log.info("  Created v_canonical_datasets view")
    except Exception as e:
        log.warning(f"  View creation error: {e}")

    # Verify
    v_count = conn.execute("SELECT COUNT(*) FROM v_canonical_datasets").fetchone()[0]
    v3_count = len(list(PARQUET_V3_DIR.glob("*.parquet")))
    log.info(f"  View rows: {v_count}, v3 files: {v3_count}")


# ── Step 2d: Archive parent parquets ─────────────────────────────────────────

def step_2d_archive_parents(conn, dry_run=False):
    """Move parent parquets to _parents/ subdirectory."""
    log.info("═══ Step 2d: Archive parent parquets ═══")

    parent_codes = {r[0] for r in conn.execute(
        "SELECT DISTINCT parent_matrix_code FROM dataset_splits"
    ).fetchall()}

    moved = 0
    total_size = 0
    for code in sorted(parent_codes):
        src = PARQUET_V3_DIR / f"{code}.parquet"
        if not src.exists():
            continue

        size = src.stat().st_size
        total_size += size

        if dry_run:
            moved += 1
            continue

        PARENTS_DIR.mkdir(parents=True, exist_ok=True)
        dst = PARENTS_DIR / f"{code}.parquet"
        shutil.move(str(src), str(dst))
        moved += 1

    # Update parquet_path for parents
    if not dry_run and moved > 0:
        conn.execute("""
            UPDATE matrices SET parquet_path = NULL
            WHERE matrix_code IN (SELECT DISTINCT parent_matrix_code FROM dataset_splits)
        """)

    action = "Would move" if dry_run else "Moved"
    log.info(f"  {action} {moved} parent parquets ({total_size / 1e6:.1f} MB)")


# ── Step 2e: Clean orphaned view profiles ────────────────────────────────────

def step_2e_clean_view_profiles(conn, dry_run=False):
    """Delete view profile JSONs not matching any canonical dataset."""
    log.info("═══ Step 2e: Clean orphaned view profiles ═══")

    if not VP_DIR.exists():
        log.info("  No view-profiles directory")
        return

    # Check if is_canonical column exists yet
    cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'matrices'"
    ).fetchall()}

    if "is_canonical" in cols:
        canonical_codes = {r[0] for r in conn.execute(
            "SELECT matrix_code FROM matrices WHERE is_canonical = TRUE"
        ).fetchall()}
    else:
        canonical_codes = {r[0] for r in conn.execute(
            "SELECT matrix_code FROM matrices"
        ).fetchall()}

    # Also keep parent codes (they have useful metadata)
    parent_codes = {r[0] for r in conn.execute(
        "SELECT DISTINCT parent_matrix_code FROM dataset_splits"
    ).fetchall()}

    keep_codes = canonical_codes | parent_codes

    orphaned = []
    for f in VP_DIR.glob("*.json"):
        if f.name.startswith("_"):
            continue
        if f.stem not in keep_codes:
            orphaned.append(f)

    log.info(f"  Found {len(orphaned)} orphaned view profiles (out of {len(list(VP_DIR.glob('*.json')))})")

    if dry_run or not orphaned:
        return

    for f in orphaned:
        f.unlink()
    log.info(f"  Deleted {len(orphaned)} orphaned view profiles")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 2: Establish canonical corpus")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no changes")
    parser.add_argument("--step", choices=["2a", "2b", "2c", "2d", "2e"], help="Run single step")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    mode = "read_only=True" if args.dry_run else ""
    conn = duckdb.connect(str(DB_FILE), read_only=args.dry_run)

    try:
        steps = {
            "2a": step_2a_convert_v2_splits,
            "2b": step_2b_adopt_orphans,
            "2c": step_2c_mark_canonical,
            "2d": step_2d_archive_parents,
            "2e": step_2e_clean_view_profiles,
        }

        if args.step:
            steps[args.step](conn, dry_run=args.dry_run)
        else:
            for name, fn in steps.items():
                fn(conn, dry_run=args.dry_run)
                print()

        if not args.dry_run:
            # Final summary
            print("=" * 60)
            print("  FINAL STATE")
            print("=" * 60)
            v3_count = len([f for f in PARQUET_V3_DIR.glob("*.parquet")])
            cols = {r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'matrices'"
            ).fetchall()}
            if "is_canonical" in cols:
                canonical = conn.execute(
                    "SELECT COUNT(*) FROM matrices WHERE is_canonical = TRUE"
                ).fetchone()[0]
                parents = conn.execute(
                    "SELECT COUNT(*) FROM matrices WHERE is_canonical = FALSE"
                ).fetchone()[0]
                print(f"  Canonical:         {canonical}")
                print(f"  Non-canonical:     {parents}")
            else:
                total = conn.execute("SELECT COUNT(*) FROM matrices").fetchone()[0]
                print(f"  Matrices (total):  {total}")
                print(f"  (is_canonical not yet set — run step 2c)")
            splits = conn.execute("SELECT COUNT(*) FROM dataset_splits").fetchone()[0]
            print(f"  v3 parquet files:  {v3_count}")
            print(f"  dataset_splits:    {splits}")
            vp = len(list(VP_DIR.glob("*.json"))) if VP_DIR.exists() else 0
            print(f"  View profiles:     {vp}")
            print()

    finally:
        conn.close()


if __name__ == "__main__":
    main()
