#!/usr/bin/env python3
"""
Strip aggregate/total rows from existing parquet-v3 files in-place.

Reads decisions from data/logs/total-decisions.json and removes
matching rows from parquet files in data/corpus/parquet/.

This handles sub-datasets and any files that can't be regenerated
from v2 sources via 12-parquet-to-sdmx.py --strip-totals.

Usage:
    python scripts/strip-totals-from-parquet.py              # strip all affected
    python scripts/strip-totals-from-parquet.py --matrix AMG1010_someri_bim  # single file
    python scripts/strip-totals-from-parquet.py --dry-run    # preview only
    python scripts/strip-totals-from-parquet.py --debug      # verbose
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))
from duckdb_config import CORPUS_PARQUET_DIR, PARQUET_COMPRESSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DECISIONS_FILE = Path(__file__).parent.parent / "data" / "logs" / "total-decisions.json"


def load_strip_decisions() -> dict:
    """Load decisions, return {matrix_code: {col: [vals_to_strip]}}."""
    raw = json.loads(DECISIONS_FILE.read_text())
    decisions = {}
    for mc, cols in raw.items():
        for col, vals in cols.items():
            strip_vals = [v for v, d in vals.items() if isinstance(d, dict) and d.get("action") == "strip"]
            if strip_vals:
                decisions.setdefault(mc, {})[col] = strip_vals
    return decisions


def strip_one(conn, matrix_code: str, col_filters: dict, dry_run: bool, debug: bool) -> dict:
    """Strip total rows from one parquet file. Returns stats."""
    pq = CORPUS_PARQUET_DIR / f"{matrix_code}.parquet"
    if not pq.exists():
        return {"error": f"Not found: {pq.name}"}

    # Count rows before
    before = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{pq}')").fetchone()[0]

    # Build WHERE clause to exclude total rows (independent mode)
    conditions = []
    for col, vals in col_filters.items():
        placeholders = ", ".join(f"'{v}'" for v in vals)
        conditions.append(f'"{col}" NOT IN ({placeholders})')
    where_independent = " AND ".join(conditions)

    # Count rows after independent filter
    after_independent = conn.execute(
        f"SELECT COUNT(*) FROM read_parquet('{pq}') WHERE {where_independent}"
    ).fetchone()[0]

    # Safety check: if independent stripping removes ALL rows, the data uses
    # mutually exclusive breakdowns (only one dim active at a time).
    # Fall back to intersection mode: only strip the "grand total" row
    # (where ALL listed dims are Total simultaneously).
    if after_independent == 0 and len(col_filters) > 1:
        log.info(f"  [{matrix_code}] Mutually exclusive breakdowns detected — using intersection mode")
        intersection_conds = []
        for col, vals in col_filters.items():
            placeholders = ", ".join(f"'{v}'" for v in vals)
            intersection_conds.append(f'"{col}" IN ({placeholders})')
        # Exclude only rows where ALL dims are Total simultaneously
        where = f"NOT ({' AND '.join(intersection_conds)})"
        mode = "intersection"
    else:
        where = where_independent
        mode = "independent"

    after = conn.execute(
        f"SELECT COUNT(*) FROM read_parquet('{pq}') WHERE {where}"
    ).fetchone()[0]

    stripped = before - after
    if stripped == 0:
        return {"before": before, "after": after, "stripped": 0, "mode": mode}

    if debug:
        for col, vals in col_filters.items():
            for v in vals:
                cnt = conn.execute(
                    f"""SELECT COUNT(*) FROM read_parquet('{pq}') WHERE "{col}" = '{v}'"""
                ).fetchone()[0]
                log.debug(f"  [{matrix_code}] {col}={v!r}: {cnt} rows")

    if not dry_run:
        # Write filtered data to temp file, then replace
        tmp = pq.with_suffix(".tmp.parquet")
        conn.execute(f"""
            COPY (SELECT * FROM read_parquet('{pq}') WHERE {where})
            TO '{tmp}'
            (FORMAT PARQUET, COMPRESSION '{PARQUET_COMPRESSION}')
        """)
        tmp.rename(pq)

    return {"before": before, "after": after, "stripped": stripped, "mode": mode}


def run(args):
    if not DECISIONS_FILE.exists():
        log.error(f"No decisions file at {DECISIONS_FILE}")
        log.error("Run: python scripts/detect-totals.py --auto-only")
        return

    decisions = load_strip_decisions()
    log.info(f"Loaded {len(decisions)} matrices with strip decisions")

    if args.matrix:
        if args.matrix not in decisions:
            log.error(f"No strip decisions for {args.matrix}")
            return
        matrices = {args.matrix: decisions[args.matrix]}
    else:
        matrices = decisions

    conn = duckdb.connect(":memory:")
    total_stripped = 0
    affected = 0

    for mc, col_filters in sorted(matrices.items()):
        result = strip_one(conn, mc, col_filters, args.dry_run, args.debug)
        if "error" in result:
            log.warning(f"  [{mc}] {result['error']}")
        elif result["stripped"] > 0:
            affected += 1
            total_stripped += result["stripped"]
            log.info(f"  [{mc}] {result['before']} → {result['after']} rows (-{result['stripped']})")
        else:
            if args.debug:
                log.debug(f"  [{mc}] No rows to strip (already clean)")

    conn.close()

    mode = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{'─' * 60}")
    print(f"{mode}Stripped {total_stripped} rows from {affected}/{len(matrices)} files")


def main():
    parser = argparse.ArgumentParser(description="Strip aggregate rows from existing parquets")
    parser.add_argument("--matrix", help="Process single matrix")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    run(args)


if __name__ == "__main__":
    main()
