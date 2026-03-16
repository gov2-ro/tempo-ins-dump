#!/usr/bin/env python3
"""
12-split-datasets.py — Split inconsistent datasets into clean sub-datasets.

Reads parquet-v2 files and produces split parquets in parquet-v3/.
Registers sub-datasets in DuckDB (dataset_splits table + matrices entries).

Patterns handled:
  A) multi_um       — Split by UM value
  B) mixed_metrics  — Split by first dimension (different measured variables)
  C) slash_dims     — Split by semantic category within a mixed dimension
  D) hierarchy      — Split into county-level and locality-level views

Usage:
    python 12-split-datasets.py                    # Process all
    python 12-split-datasets.py --matrix FOM121B   # Process single dataset
    python 12-split-datasets.py --pattern multi_um # Process one pattern only
    python 12-split-datasets.py --dry-run          # Show what would be done
    python 12-split-datasets.py --debug            # Verbose logging
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from collections import defaultdict

import duckdb

from duckdb_config import DB_FILE, PARQUET_COMPRESSION
from split_rules import detect_all, SplitRule, SplitGroup

logger = logging.getLogger(__name__)

# Paths
DATA_DIR = Path(__file__).parent / "data"
PARQUET_V2_DIR = DATA_DIR / "parquet-v2" / "ro"
PARQUET_V3_DIR = DATA_DIR / "parquet-v3" / "ro"


def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def ensure_schema(conn):
    """Create/recreate the dataset_splits table and add is_split column to matrices."""
    conn.execute("DROP TABLE IF EXISTS dataset_splits")
    conn.execute("""
        CREATE TABLE dataset_splits (
            parent_matrix_code VARCHAR,
            sub_matrix_code VARCHAR,
            split_pattern VARCHAR,
            split_dimension VARCHAR,
            split_value VARCHAR,
            parquet_path VARCHAR,
            row_count BIGINT,
            suffix_label VARCHAR,
            display_name VARCHAR
        )
    """)

    # Add is_split column if it doesn't exist
    cols = [r[0] for r in conn.execute("DESCRIBE matrices").fetchall()]
    if "is_split" not in cols:
        conn.execute("ALTER TABLE matrices ADD COLUMN is_split BOOLEAN DEFAULT FALSE")
    if "parent_matrix_code" not in cols:
        conn.execute("ALTER TABLE matrices ADD COLUMN parent_matrix_code VARCHAR")

    logger.info("Schema ready (dataset_splits table created)")


def clean_previous_splits(conn):
    """Remove previously generated split entries from matrices, dimensions, dimension_options."""
    # Find existing splits
    existing = conn.execute("""
        SELECT matrix_code FROM matrices WHERE is_split = TRUE
    """).fetchall()

    if not existing:
        return

    codes = [r[0] for r in existing]
    logger.info(f"Cleaning {len(codes)} previous split entries from metadata")

    placeholders = ",".join(f"'{c}'" for c in codes)
    conn.execute(f"DELETE FROM dimension_options WHERE dimension_id IN (SELECT dimension_id FROM dimensions WHERE matrix_code IN ({placeholders}))")
    conn.execute(f"DELETE FROM dimensions WHERE matrix_code IN ({placeholders})")
    conn.execute(f"DELETE FROM matrices WHERE matrix_code IN ({placeholders})")


def generate_sub_matrix_code(matrix_code: str, suffix: str) -> str:
    """Generate a sub-dataset code like FOM121B_salariu_brut."""
    return f"{matrix_code}_{suffix}"


def split_parquet_by_filter(conn, rule: SplitRule, dry_run: bool = False) -> list[dict]:
    """Split a parquet file based on a SplitRule. Returns list of sub-dataset info dicts."""
    _v1 = DATA_DIR / "parquet" / "ro" / f"{rule.matrix_code}.parquet"
    src = _v1 if _v1.exists() else PARQUET_V2_DIR / f"{rule.matrix_code}.parquet"
    if not src.exists():
        logger.warning(f"Parquet not found: {src}")
        return []

    results = []
    split_col = rule.split_dimension

    # Deduplicate suffixes to avoid filename collisions
    seen_suffixes = {}
    for group in rule.groups:
        if group.label in seen_suffixes:
            seen_suffixes[group.label] += 1
            group.label = f"{group.label}_{seen_suffixes[group.label]}"
        else:
            seen_suffixes[group.label] = 0

    for group in rule.groups:
        sub_code = generate_sub_matrix_code(rule.matrix_code, group.label)
        dst = PARQUET_V3_DIR / f"{sub_code}.parquet"

        if dry_run:
            logger.info(f"  [DRY-RUN] {rule.matrix_code} -> {sub_code} "
                        f"({len(group.option_ids)} options in '{group.label}')")
            results.append({
                "sub_code": sub_code, "path": str(dst),
                "row_count": 0, "group": group,
            })
            continue

        # Build WHERE clause
        if rule.pattern == "hierarchy":
            # Special handling: hierarchy splits are row-level, not column-value
            row_count = _split_hierarchy(conn, src, dst, rule, group)
        else:
            ids_str = ",".join(str(i) for i in group.option_ids)
            # Select all columns except the ones we're dropping
            all_cols = _get_parquet_columns(conn, src)
            keep_cols = [c for c in all_cols if c not in rule.drop_columns]
            select = ", ".join(f'"{c}"' for c in keep_cols)

            query = f"""
                COPY (
                    SELECT {select}
                    FROM read_parquet('{src}')
                    WHERE "{split_col}" IN ({ids_str})
                ) TO '{dst}' (FORMAT PARQUET, COMPRESSION '{PARQUET_COMPRESSION}')
            """
            try:
                conn.execute(query)
                row_count = conn.execute(
                    f"SELECT COUNT(*) FROM read_parquet('{dst}')"
                ).fetchone()[0]
            except Exception as e:
                logger.error(f"Failed to split {rule.matrix_code} -> {sub_code}: {e}")
                continue

        logger.debug(f"  {sub_code}: {row_count} rows -> {dst.name}")
        results.append({
            "sub_code": sub_code, "path": str(dst),
            "row_count": row_count, "group": group,
        })

    return results


def _split_hierarchy(conn, src: Path, dst: Path, rule: SplitRule, group: SplitGroup) -> int:
    """Handle hierarchy splits (county vs locality level)."""
    # Get the county and locality column names
    dims = conn.execute(f"""
        SELECT dim_column_name, dim_label FROM dimensions
        WHERE matrix_code = '{rule.matrix_code}'
    """).fetchall()

    locality_col = rule.split_dimension  # The locality column

    all_cols = _get_parquet_columns(conn, src)

    if group.label == "judet":
        # County level: exclude locality column entirely
        keep_cols = [c for c in all_cols if c != locality_col]
        select = ", ".join(f'"{c}"' for c in keep_cols)
        # Deduplicate since multiple localities per county
        query = f"""
            COPY (
                SELECT DISTINCT {select}
                FROM read_parquet('{src}')
            ) TO '{dst}' (FORMAT PARQUET, COMPRESSION '{PARQUET_COMPRESSION}')
        """
    else:
        # Locality level: keep all columns as-is
        query = f"""
            COPY (
                SELECT * FROM read_parquet('{src}')
            ) TO '{dst}' (FORMAT PARQUET, COMPRESSION '{PARQUET_COMPRESSION}')
        """

    try:
        conn.execute(query)
        return conn.execute(f"SELECT COUNT(*) FROM read_parquet('{dst}')").fetchone()[0]
    except Exception as e:
        logger.error(f"Hierarchy split failed for {rule.matrix_code}/{group.label}: {e}")
        return 0


def _get_parquet_columns(conn, parquet_path: Path) -> list[str]:
    """Get column names from a parquet file."""
    schema = conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{parquet_path}')").fetchall()
    return [r[0] for r in schema]


def register_sub_dataset(conn, rule: SplitRule, sub_info: dict):
    """Register a sub-dataset in DuckDB metadata."""
    sub_code = sub_info["sub_code"]
    group = sub_info["group"]

    # Get parent matrix info
    parent = conn.execute(f"""
        SELECT matrix_name, context_code, file_size_bytes
        FROM matrices WHERE matrix_code = '{rule.matrix_code}'
    """).fetchone()

    if not parent:
        logger.warning(f"Parent matrix {rule.matrix_code} not found")
        return

    parent_name = parent[0]
    context_code = parent[1]

    # Build display name
    display_suffix = group.option_labels.get(
        group.option_ids[0] if group.option_ids else None,
        group.label
    )
    if len(group.option_ids) > 1:
        display_suffix = group.label  # Use semantic category name for multi-option groups
    display_name = f"{parent_name} [{display_suffix}]"

    # Insert into matrices
    conn.execute("""
        INSERT INTO matrices (matrix_code, matrix_name, context_code,
                              parquet_path, row_count, is_split, parent_matrix_code)
        VALUES (?, ?, ?, ?, ?, TRUE, ?)
    """, [sub_code, display_name, context_code,
          sub_info["path"], sub_info["row_count"], rule.matrix_code])

    # Insert into dataset_splits
    conn.execute("""
        INSERT INTO dataset_splits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [rule.matrix_code, sub_code, rule.pattern, rule.split_dimension,
          group.label, sub_info["path"], sub_info["row_count"],
          group.label, display_name])

    # Copy dimension metadata (minus split dimension)
    _copy_dimensions(conn, rule, sub_code, sub_info)


def _copy_dimensions(conn, rule: SplitRule, sub_code: str, sub_info: dict):
    """Copy dimension + option metadata for sub-dataset, excluding split dimension."""
    # Get parquet columns to know which dimensions survived
    if sub_info["row_count"] == 0:
        return

    try:
        sub_cols = set(_get_parquet_columns(
            conn, Path(sub_info["path"])
        ))
    except Exception:
        # Fallback: use parent dims minus dropped
        sub_cols = None

    # Schema: dimension_id, matrix_code, dim_code, dim_label, dim_column_name, option_count
    parent_dims = conn.execute(f"""
        SELECT dimension_id, dim_code, dim_label, dim_column_name, option_count
        FROM dimensions
        WHERE matrix_code = '{rule.matrix_code}'
        ORDER BY dim_code
    """).fetchall()

    new_dim_code = 1
    for dim in parent_dims:
        parent_dim_id = dim[0]
        dim_col = dim[3]

        # Skip dropped columns
        if dim_col in rule.drop_columns:
            continue
        if sub_cols is not None and dim_col not in sub_cols:
            continue

        # For slash_dims, filter options to only this group's IDs
        if rule.pattern == "slash_dims" and parent_dim_id == rule.split_dimension_id:
            group = sub_info["group"]
            new_dim_id = _next_dim_id(conn)
            conn.execute("""
                INSERT INTO dimensions (dimension_id, matrix_code, dim_code,
                                        dim_label, dim_column_name, option_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [new_dim_id, sub_code, new_dim_code,
                  group.label, dim_col, len(group.option_ids)])

            # Copy only matching options
            for oid in group.option_ids:
                opts = conn.execute(f"""
                    SELECT nom_item_id, option_label, option_offset, parent_id
                    FROM dimension_options WHERE dimension_id = {parent_dim_id}
                    AND nom_item_id = {oid}
                """).fetchall()
                for o in opts:
                    new_oid = _next_option_id(conn)
                    conn.execute("""
                        INSERT INTO dimension_options (option_id, dimension_id, nom_item_id, option_label, option_offset, parent_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, [new_oid, new_dim_id, o[0], o[1], o[2], o[3]])
        else:
            # Copy dimension and all its options as-is
            new_dim_id = _next_dim_id(conn)
            conn.execute("""
                INSERT INTO dimensions (dimension_id, matrix_code, dim_code,
                                        dim_label, dim_column_name, option_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [new_dim_id, sub_code, new_dim_code,
                  dim[2], dim_col, dim[4]])

            # Copy all options with new option_ids
            parent_opts = conn.execute(f"""
                SELECT nom_item_id, option_label, option_offset, parent_id
                FROM dimension_options WHERE dimension_id = {parent_dim_id}
            """).fetchall()
            start_oid = _next_option_id(conn, len(parent_opts))
            for idx, o in enumerate(parent_opts):
                conn.execute("""
                    INSERT INTO dimension_options (option_id, dimension_id, nom_item_id, option_label, option_offset, parent_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, [start_oid + idx, new_dim_id, o[0], o[1], o[2], o[3]])

        new_dim_code += 1


_dim_id_counter = None
_option_id_counter = None

def _next_dim_id(conn) -> int:
    """Get next available dimension_id."""
    global _dim_id_counter
    if _dim_id_counter is None:
        _dim_id_counter = conn.execute("SELECT COALESCE(MAX(dimension_id), 0) FROM dimensions").fetchone()[0]
    _dim_id_counter += 1
    return _dim_id_counter

def _next_option_id(conn, count: int = 1) -> int:
    """Get next available option_id. Returns the starting ID for a batch."""
    global _option_id_counter
    if _option_id_counter is None:
        _option_id_counter = conn.execute("SELECT COALESCE(MAX(option_id), 0) FROM dimension_options").fetchone()[0]
    start = _option_id_counter + 1
    _option_id_counter += count
    return start


def main():
    parser = argparse.ArgumentParser(description="Split inconsistent datasets into sub-datasets")
    parser.add_argument("--matrix", help="Process a single matrix code")
    parser.add_argument("--pattern", choices=["multi_um", "mixed_metrics", "slash_dims", "hierarchy"],
                        help="Process only one pattern type")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(args.debug)
    logger.info("=" * 60)
    logger.info("12-split-datasets.py — Dataset Splitter")
    logger.info("=" * 60)

    # Create output directory
    if not args.dry_run:
        PARQUET_V3_DIR.mkdir(parents=True, exist_ok=True)

    read_only = args.dry_run
    conn = duckdb.connect(str(DB_FILE), read_only=read_only)

    try:
        # Detect all split rules
        logger.info("Detecting split patterns...")
        rules = detect_all(conn)

        # Filter by CLI args
        if args.matrix:
            rules = [r for r in rules if r.matrix_code == args.matrix]
        if args.pattern:
            rules = [r for r in rules if r.pattern == args.pattern]

        if not rules:
            logger.info("No datasets matched. Nothing to do.")
            return

        # Summary
        by_pattern = defaultdict(list)
        for r in rules:
            by_pattern[r.pattern].append(r.matrix_code)

        logger.info(f"\nSplit plan: {len(rules)} datasets")
        for pat, codes in sorted(by_pattern.items()):
            logger.info(f"  {pat}: {len(codes)} datasets")

        if not args.dry_run:
            # Prepare schema
            ensure_schema(conn)
            clean_previous_splits(conn)

        # Process each rule
        t0 = time.time()
        total_sub = 0
        total_rows = 0
        errors = 0

        for i, rule in enumerate(rules, 1):
            logger.info(f"\n[{i}/{len(rules)}] {rule.matrix_code} ({rule.pattern}) "
                        f"-> {len(rule.groups)} sub-datasets")

            sub_results = split_parquet_by_filter(conn, rule, dry_run=args.dry_run)

            if not args.dry_run:
                for sub in sub_results:
                    if sub["row_count"] > 0:
                        register_sub_dataset(conn, rule, sub)
                        total_sub += 1
                        total_rows += sub["row_count"]
                    else:
                        errors += 1

        elapsed = time.time() - t0

        # Summary
        logger.info("\n" + "=" * 60)
        if args.dry_run:
            logger.info(f"DRY RUN complete. Would create {sum(len(r.groups) for r in rules)} sub-datasets.")
        else:
            logger.info(f"Done in {elapsed:.1f}s")
            logger.info(f"  Sub-datasets created: {total_sub}")
            logger.info(f"  Total rows: {total_rows:,}")
            logger.info(f"  Errors: {errors}")
            logger.info(f"  Output: {PARQUET_V3_DIR}")

            # Verify
            count = conn.execute("SELECT COUNT(*) FROM dataset_splits").fetchone()[0]
            logger.info(f"  dataset_splits rows: {count}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
