#!/usr/bin/env python3
"""
Phase 3: Build i18n dictionary from English metadata.

Creates:
  - labels_i18n table: nom_item_id → label_ro, label_en, dim_type
  - matrices.matrix_name_en, matrices.definitie_en columns
  - contexts.context_name_en column
  - Populates sdmx_codes.display_label_en

Usage:
    python scripts/build-i18n-dictionary.py
    python scripts/build-i18n-dictionary.py --dry-run
    python scripts/build-i18n-dictionary.py --debug
"""
import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb
from duckdb_config import DB_FILE, DATA_DIR

EN_METAS_DIR = DATA_DIR / "2-metas" / "en"
RO_METAS_DIR = DATA_DIR / "2-metas" / "ro"
EN_CONTEXT_CSV = DATA_DIR / "1-indexes" / "en" / "context.csv"
EN_MATRICES_CSV = DATA_DIR / "1-indexes" / "en" / "matrices.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def build_labels_i18n(conn, dry_run=False):
    """Extract nomItemId → label mappings from EN and RO metadata JSONs."""
    log.info("═══ Step 3a: Build labels_i18n table ═══")

    # Collect EN labels from metadata JSONs
    en_labels = {}  # nom_item_id → label_en
    en_files = sorted(EN_METAS_DIR.glob("*.json"))
    log.info(f"  Scanning {len(en_files)} EN metadata files...")

    for f in en_files:
        try:
            with open(f, encoding="utf-8") as fh:
                meta = json.load(fh)
            for dim in meta.get("dimensionsMap", []):
                for opt in dim.get("options", []):
                    nid = opt.get("nomItemId")
                    label = opt.get("label", "").strip()
                    if nid and label:
                        en_labels[nid] = label
        except Exception as e:
            log.warning(f"  Error reading {f.name}: {e}")

    log.info(f"  Extracted {len(en_labels):,} EN labels from metadata")

    # Get existing RO labels from dimension_options
    ro_labels = {}
    for nid, label in conn.execute(
        "SELECT nom_item_id, option_label FROM dimension_options"
    ).fetchall():
        if nid not in ro_labels:  # Keep first occurrence
            ro_labels[nid] = label

    log.info(f"  RO labels from dimension_options: {len(ro_labels):,}")

    # Get dim_type from dimension_options_parsed
    dim_types = {}
    for nid, dt in conn.execute(
        "SELECT nom_item_id, dim_type FROM dimension_options_parsed"
    ).fetchall():
        dim_types[nid] = dt

    # Union of all nom_item_ids
    all_ids = set(en_labels.keys()) | set(ro_labels.keys())
    log.info(f"  Union of IDs: {len(all_ids):,}")

    if dry_run:
        log.info(f"  Would create labels_i18n with {len(all_ids)} rows")
        return len(all_ids)

    # Create table
    conn.execute("DROP TABLE IF EXISTS labels_i18n")
    conn.execute("""
        CREATE TABLE labels_i18n (
            nom_item_id INTEGER PRIMARY KEY,
            label_ro VARCHAR,
            label_en VARCHAR,
            dim_type VARCHAR
        )
    """)

    # Batch insert
    rows = []
    for nid in all_ids:
        rows.append((nid, ro_labels.get(nid), en_labels.get(nid), dim_types.get(nid)))

    conn.executemany(
        "INSERT INTO labels_i18n VALUES (?, ?, ?, ?)", rows
    )

    total = conn.execute("SELECT COUNT(*) FROM labels_i18n").fetchone()[0]
    en_count = conn.execute("SELECT COUNT(*) FROM labels_i18n WHERE label_en IS NOT NULL").fetchone()[0]
    ro_count = conn.execute("SELECT COUNT(*) FROM labels_i18n WHERE label_ro IS NOT NULL").fetchone()[0]
    log.info(f"  Created labels_i18n: {total:,} rows ({en_count:,} EN, {ro_count:,} RO)")
    return total


def add_matrix_translations(conn, dry_run=False):
    """Add matrix_name_en and definitie_en to matrices table."""
    log.info("═══ Step 3b: Add matrix/context EN translations ═══")

    # Check existing columns
    cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'matrices'"
    ).fetchall()}

    if "matrix_name_en" not in cols:
        if dry_run:
            log.info("  Would add matrix_name_en, definitie_en columns")
        else:
            conn.execute("ALTER TABLE matrices ADD COLUMN matrix_name_en VARCHAR")
            conn.execute("ALTER TABLE matrices ADD COLUMN definitie_en VARCHAR")
            log.info("  Added matrix_name_en, definitie_en columns")

    # Extract EN names from metadata JSONs
    en_names = {}  # matrix_code → (name_en, definitie_en)
    for f in sorted(EN_METAS_DIR.glob("*.json")):
        code = f.stem
        try:
            with open(f, encoding="utf-8") as fh:
                meta = json.load(fh)
            name = meta.get("matrixName", "").strip()
            defn = meta.get("definitie", "").strip() if meta.get("definitie") else None
            en_names[code] = (name, defn)
        except Exception:
            pass

    # Also try EN matrices CSV for broader coverage
    if EN_MATRICES_CSV.exists():
        with open(EN_MATRICES_CSV, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                code = row.get("code", "").strip()
                name = row.get("name", "").strip()
                if code and name and code not in en_names:
                    en_names[code] = (name, None)

    log.info(f"  EN translations for {len(en_names):,} matrices")

    if dry_run:
        return

    # Update matrices
    updated = 0
    for code, (name, defn) in en_names.items():
        try:
            conn.execute("""
                UPDATE matrices SET matrix_name_en = ?, definitie_en = ?
                WHERE matrix_code = ?
            """, [name, defn, code])
            updated += 1
        except Exception:
            pass

    # For sub-datasets, inherit parent's EN name + suffix
    conn.execute("""
        UPDATE matrices SET matrix_name_en = (
            SELECT p.matrix_name_en || ' (' || ds.suffix_label || ')'
            FROM dataset_splits ds
            JOIN matrices p ON p.matrix_code = ds.parent_matrix_code
            WHERE ds.sub_matrix_code = matrices.matrix_code
        )
        WHERE is_split = TRUE AND matrix_name_en IS NULL
    """)

    with_en = conn.execute(
        "SELECT COUNT(*) FROM matrices WHERE matrix_name_en IS NOT NULL"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM matrices").fetchone()[0]
    log.info(f"  Matrices with EN name: {with_en:,} / {total:,}")


def add_context_translations(conn, dry_run=False):
    """Add context_name_en to contexts table."""
    log.info("═══ Step 3c: Add context EN translations ═══")

    cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'contexts'"
    ).fetchall()}

    if "context_name_en" not in cols:
        if dry_run:
            log.info("  Would add context_name_en column")
        else:
            conn.execute("ALTER TABLE contexts ADD COLUMN context_name_en VARCHAR")
            log.info("  Added context_name_en column")

    if not EN_CONTEXT_CSV.exists():
        log.warning(f"  EN context CSV not found: {EN_CONTEXT_CSV}")
        return

    en_contexts = {}
    with open(EN_CONTEXT_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row.get("context_code", "").strip()
            name = row.get("context_name", "").strip()
            if code and name:
                en_contexts[code] = name

    log.info(f"  EN translations for {len(en_contexts):,} contexts")

    if dry_run:
        return

    for code, name in en_contexts.items():
        conn.execute("""
            UPDATE contexts SET context_name_en = ? WHERE context_code = ?
        """, [name, code])

    with_en = conn.execute(
        "SELECT COUNT(*) FROM contexts WHERE context_name_en IS NOT NULL"
    ).fetchone()[0]
    log.info(f"  Contexts with EN name: {with_en:,} / 339")


def populate_sdmx_display_label_en(conn, dry_run=False):
    """Fill sdmx_codes.display_label_en from labels_i18n."""
    log.info("═══ Step 3d: Populate sdmx_codes.display_label_en ═══")

    # Check if column exists
    cols = {r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'sdmx_codes'"
    ).fetchall()}

    if "display_label_en" not in cols:
        if dry_run:
            log.info("  Would add display_label_en column")
        else:
            conn.execute("ALTER TABLE sdmx_codes ADD COLUMN display_label_en VARCHAR")

    if dry_run:
        return

    conn.execute("""
        UPDATE sdmx_codes SET display_label_en = (
            SELECT label_en FROM labels_i18n
            WHERE labels_i18n.nom_item_id = sdmx_codes.nom_item_id
        )
    """)

    filled = conn.execute(
        "SELECT COUNT(*) FROM sdmx_codes WHERE display_label_en IS NOT NULL"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM sdmx_codes").fetchone()[0]
    log.info(f"  sdmx_codes with EN label: {filled:,} / {total:,}")


def main():
    parser = argparse.ArgumentParser(description="Phase 3: Build i18n dictionary")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    conn = duckdb.connect(str(DB_FILE), read_only=args.dry_run)

    try:
        t0 = time.time()
        build_labels_i18n(conn, dry_run=args.dry_run)
        print()
        add_matrix_translations(conn, dry_run=args.dry_run)
        print()
        add_context_translations(conn, dry_run=args.dry_run)
        print()
        populate_sdmx_display_label_en(conn, dry_run=args.dry_run)
        elapsed = time.time() - t0

        print(f"\n{'═' * 60}")
        print(f"  Phase 3 complete in {elapsed:.1f}s")
        if not args.dry_run:
            li = conn.execute("SELECT COUNT(*) FROM labels_i18n").fetchone()[0]
            li_en = conn.execute("SELECT COUNT(*) FROM labels_i18n WHERE label_en IS NOT NULL").fetchone()[0]
            m_en = conn.execute("SELECT COUNT(*) FROM matrices WHERE matrix_name_en IS NOT NULL").fetchone()[0]
            c_en = conn.execute("SELECT COUNT(*) FROM contexts WHERE context_name_en IS NOT NULL").fetchone()[0]
            s_en = conn.execute("SELECT COUNT(*) FROM sdmx_codes WHERE display_label_en IS NOT NULL").fetchone()[0]
            print(f"  labels_i18n:              {li:,} rows ({li_en:,} with EN)")
            print(f"  matrices with EN name:    {m_en:,}")
            print(f"  contexts with EN name:    {c_en:,}")
            print(f"  sdmx_codes with EN label: {s_en:,}")
        print()

    finally:
        conn.close()


if __name__ == "__main__":
    main()
