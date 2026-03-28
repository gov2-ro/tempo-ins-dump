#!/usr/bin/env python3
"""
Detect and mark aggregate/total rows in canonical parquet files.

Scans all parquet files for known total-pattern dimension values in
safe dim_types (geo, gender, age, residence). Validates candidates
with a sum-check heuristic: if OBS_VALUE ≈ sum(other values) for the
same time+remaining dims, it's a confirmed aggregate.

Outputs decisions to data/logs/total-decisions.json for use by
12-parquet-to-sdmx.py --strip-totals.

Usage:
    python scripts/detect-totals.py                    # full run with interactive
    python scripts/detect-totals.py --auto-only        # auto-detect only, no prompts
    python scripts/detect-totals.py --dry-run          # preview, don't write decisions
    python scripts/detect-totals.py --matrix POP105A   # single dataset
    python scripts/detect-totals.py --debug            # verbose logging
"""

import argparse
import json
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))
from duckdb_config import DB_FILE, CORPUS_PARQUET_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DECISIONS_FILE = Path(__file__).parent.parent / "data" / "logs" / "total-decisions.json"

# ── Known total patterns per dim_type ────────────────────────────────────────
# High confidence: strip without asking if sum-check passes

KNOWN_TOTALS = {
    "geo": ["TOTAL", "Total", "Nivel National"],
    "gender": ["Total", "TOTAL", "Ambele sexe", "Total persoane"],
    "age": [
        "Total",
        "Total persoane",
        "Toate varstele",
        "Toate grupele de varsta",
    ],
    "residence": ["Total", "Total medii"],
}

# SDMX column names that map to safe dim_types
SAFE_COLUMNS = {
    "REF_AREA": "geo",
    "REF_AREA_2": "geo",
    "SEX": "gender",
    "AGE": "age",
    "RESIDENCE": "residence",
}

# Medium confidence regex — candidates that need sum-check or user confirmation
MAYBE_TOTALS_RE = re.compile(r"^total$|^total\s|\btoate\b|^ambele\s", re.IGNORECASE)

# Skip these dim_types entirely (too many false positives)
SKIP_DIM_TYPES = {"indicator", "time", "unit", "measure"}


def build_column_dim_type_map(conn) -> dict:
    """Build {(matrix_code, sdmx_column_name): dim_type} from sdmx_column_map."""
    rows = conn.execute(
        "SELECT matrix_code, sdmx_column_name, dim_type FROM sdmx_column_map"
    ).fetchall()
    return {(mc, col): dt for mc, col, dt in rows}


def build_parent_map(conn) -> dict:
    """Build {sub_matrix_code: parent_matrix_code} from dataset_splits."""
    rows = conn.execute(
        "SELECT sub_matrix_code, parent_matrix_code FROM dataset_splits"
    ).fetchall()
    return {sub: parent for sub, parent in rows}


def get_dim_type(matrix_code: str, col_name: str, col_dim_map: dict, parent_map: dict) -> str | None:
    """Resolve dim_type for a column in a matrix, handling sub-datasets."""
    # Direct lookup
    dt = col_dim_map.get((matrix_code, col_name))
    if dt:
        return dt
    # Try parent
    parent = parent_map.get(matrix_code)
    if parent:
        dt = col_dim_map.get((parent, col_name))
        if dt:
            return dt
    # Fall back to known SDMX column names
    return SAFE_COLUMNS.get(col_name)


def sum_check(conn, parquet_path: str, target_col: str, target_val: str, dim_cols: list[str]) -> dict:
    """Check if target_val rows are approximately equal to sum of other rows.

    Groups by TIME_PERIOD + all dims except target_col.
    Returns {match_pct, sample_total, sample_sum, n_groups, checked}.
    """
    other_dims = [c for c in dim_cols if c != target_col]
    group_cols = ["TIME_PERIOD"] + other_dims
    group_str = ", ".join(f'"{c}"' for c in group_cols)

    try:
        # Get aggregate rows (where target_col = target_val)
        # and detail rows (where target_col != target_val), grouped
        result = conn.execute(f"""
            WITH grouped AS (
                SELECT {group_str},
                       SUM(CASE WHEN "{target_col}" = $1 THEN OBS_VALUE END) as total_val,
                       SUM(CASE WHEN "{target_col}" != $1 THEN OBS_VALUE END) as detail_sum,
                       COUNT(CASE WHEN "{target_col}" = $1 THEN 1 END) as total_rows,
                       COUNT(CASE WHEN "{target_col}" != $1 THEN 1 END) as detail_rows
                FROM read_parquet('{parquet_path}')
                WHERE OBS_VALUE IS NOT NULL
                GROUP BY {group_str}
                HAVING total_rows > 0 AND detail_rows > 0
            )
            SELECT
                COUNT(*) as n_groups,
                COUNT(CASE WHEN ABS(total_val - detail_sum) <= ABS(total_val) * 0.05 THEN 1 END) as matches,
                AVG(total_val) as avg_total,
                AVG(detail_sum) as avg_sum
            FROM grouped
            WHERE total_val IS NOT NULL AND detail_sum IS NOT NULL
        """, [target_val]).fetchone()

        n_groups, matches, avg_total, avg_sum = result
        if n_groups == 0:
            return {"checked": False, "reason": "no_comparable_groups"}

        match_pct = matches / n_groups if n_groups > 0 else 0
        return {
            "checked": True,
            "n_groups": n_groups,
            "matches": matches,
            "match_pct": round(match_pct, 3),
            "avg_total": round(avg_total, 2) if avg_total else None,
            "avg_sum": round(avg_sum, 2) if avg_sum else None,
        }
    except Exception as e:
        return {"checked": False, "reason": str(e)[:100]}


def detect_one(
    conn,
    matrix_code: str,
    parquet_path: str,
    col_dim_map: dict,
    parent_map: dict,
    auto_only: bool,
    debug: bool,
) -> dict | None:
    """Detect total rows in one parquet file. Returns decisions dict or None."""
    try:
        cols = conn.execute(
            f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{parquet_path}'))"
        ).fetchall()
    except Exception as e:
        if debug:
            log.debug(f"  [{matrix_code}] Cannot read: {e}")
        return None

    col_names = [c[0] for c in cols]
    dim_cols = [c for c in col_names if c not in ("TIME_PERIOD", "OBS_VALUE", "UNIT_MEASURE")]

    decisions = {}

    for col in dim_cols:
        dim_type = get_dim_type(matrix_code, col, col_dim_map, parent_map)

        # Skip non-safe dim_types
        if dim_type in SKIP_DIM_TYPES or dim_type is None:
            continue

        # Get distinct values for this column
        try:
            vals = conn.execute(
                f'SELECT DISTINCT "{col}" FROM read_parquet(\'{parquet_path}\')'
            ).fetchall()
        except:
            continue

        val_list = [str(v[0]) for v in vals if v[0] is not None]

        # Check against known patterns
        known = KNOWN_TOTALS.get(dim_type, [])
        candidates = []

        for v in val_list:
            if v in known:
                candidates.append((v, "known_pattern"))
            elif MAYBE_TOTALS_RE.search(v) and v not in known:
                candidates.append((v, "regex_match"))

        if not candidates:
            continue

        # Skip if candidate is the only value — no detail rows to aggregate over
        non_candidate_vals = [v for v in val_list if v not in [c[0] for c in candidates]]
        if not non_candidate_vals:
            if debug:
                log.debug(f"  [{matrix_code}] {col}: skipping — only total values, no detail rows")
            continue

        for val, source in candidates:
            # Run sum-check
            check = sum_check(conn, parquet_path, col, val, dim_cols)

            if debug:
                log.debug(f"  [{matrix_code}] {col}={val!r} ({source}): {check}")

            if check.get("checked") and check["match_pct"] >= 0.8:
                # High confidence: auto-strip
                decisions.setdefault(col, {})[val] = {
                    "action": "strip",
                    "reason": "sum_match",
                    "confidence": "high",
                    "match_pct": check["match_pct"],
                    "n_groups": check["n_groups"],
                }
            elif check.get("checked") and check["match_pct"] >= 0.5:
                # Medium confidence
                if auto_only:
                    decisions.setdefault(col, {})[val] = {
                        "action": "strip",
                        "reason": "sum_partial_match",
                        "confidence": "medium",
                        "match_pct": check["match_pct"],
                        "n_groups": check["n_groups"],
                    }
                else:
                    # Interactive
                    decision = prompt_user(matrix_code, col, val, dim_type, check)
                    if decision:
                        decisions.setdefault(col, {})[val] = decision
            elif source == "known_pattern":
                # Known pattern but sum doesn't match — could be rates/indices
                if auto_only:
                    decisions.setdefault(col, {})[val] = {
                        "action": "strip",
                        "reason": "known_pattern_no_sum",
                        "confidence": "medium",
                        "match_pct": check.get("match_pct", 0),
                    }
                else:
                    decision = prompt_user(matrix_code, col, val, dim_type, check)
                    if decision:
                        decisions.setdefault(col, {})[val] = decision
            # regex_match with low sum-check: skip (likely false positive)

    return decisions if decisions else None


def prompt_user(matrix_code: str, col: str, val: str, dim_type: str, check: dict) -> dict | None:
    """Interactive prompt for uncertain candidates."""
    print(f"\n  [{matrix_code}] {col} (dim_type={dim_type})")
    print(f"  Candidate: {val!r}")
    if check.get("checked"):
        print(f"  Sum-check: {check['match_pct']*100:.0f}% match ({check['matches']}/{check['n_groups']} groups)")
        if check.get("avg_total") and check.get("avg_sum"):
            print(f"  Avg total={check['avg_total']}, avg detail_sum={check['avg_sum']}")
    else:
        print(f"  Sum-check: {check.get('reason', 'failed')}")

    while True:
        answer = input("  Strip? [y]es / [n]o / [s]kip dataset: ").strip().lower()
        if answer in ("y", "yes"):
            return {"action": "strip", "reason": "user_confirmed", "confidence": "user"}
        elif answer in ("n", "no"):
            return {"action": "keep", "reason": "user_confirmed_not_aggregate", "confidence": "user"}
        elif answer in ("s", "skip"):
            return None
        print("  Please enter y, n, or s")


def run(args):
    mode = "DRY RUN" if args.dry_run else "LIVE"
    log.info(f"Detecting aggregate/total rows ({mode})")

    conn = duckdb.connect(str(DB_FILE), read_only=True)

    # Build lookups
    col_dim_map = build_column_dim_type_map(conn)
    parent_map = build_parent_map(conn)
    log.info(f"  Column dim_type map: {len(col_dim_map)} entries")
    log.info(f"  Parent map: {len(parent_map)} sub-datasets")

    # Load existing decisions (merge mode)
    all_decisions = {}
    if DECISIONS_FILE.exists() and not args.fresh:
        all_decisions = json.loads(DECISIONS_FILE.read_text())
        log.info(f"  Loaded {len(all_decisions)} existing decisions from {DECISIONS_FILE.name}")

    # Get parquet files to scan
    if args.matrix:
        # Find all parquet files matching this matrix code (including sub-datasets)
        files = sorted(
            f for f in os.listdir(CORPUS_PARQUET_DIR)
            if f.endswith(".parquet") and (f.startswith(args.matrix + ".") or f.startswith(args.matrix + "_"))
        )
        if not files:
            log.error(f"No parquet files found for {args.matrix}")
            conn.close()
            return
    else:
        files = sorted(f for f in os.listdir(CORPUS_PARQUET_DIR) if f.endswith(".parquet"))

    total = len(files)
    log.info(f"Scanning {total} parquet files...\n")

    stats = {"scanned": 0, "affected": 0, "strip": 0, "keep": 0, "skipped": 0}

    for i, f in enumerate(files, 1):
        matrix_code = f.replace(".parquet", "")
        pq_path = str(CORPUS_PARQUET_DIR / f)

        # Skip if already decided and not forced
        if matrix_code in all_decisions and not args.force:
            stats["skipped"] += 1
            continue

        decisions = detect_one(
            conn, matrix_code, pq_path, col_dim_map, parent_map,
            auto_only=args.auto_only, debug=args.debug,
        )

        if decisions:
            all_decisions[matrix_code] = decisions
            stats["affected"] += 1
            n_strip = sum(1 for col_d in decisions.values() for d in col_d.values() if d["action"] == "strip")
            n_keep = sum(1 for col_d in decisions.values() for d in col_d.values() if d["action"] == "keep")
            stats["strip"] += n_strip
            stats["keep"] += n_keep
            log.info(f"  [{matrix_code}] {n_strip} strip, {n_keep} keep")

        stats["scanned"] += 1
        if i % 500 == 0:
            log.info(f"  Progress: {i}/{total} ({stats['affected']} affected)")

    conn.close()

    # Summary
    print(f"\n{'─' * 60}")
    print(f"Detection complete")
    print(f"  Scanned:  {stats['scanned']}")
    print(f"  Affected: {stats['affected']} files")
    print(f"  Strip:    {stats['strip']} dimension values")
    print(f"  Keep:     {stats['keep']} dimension values")
    print(f"  Skipped:  {stats['skipped']} (already decided)")

    # Summary by column
    col_counts = defaultdict(int)
    for mc, cols in all_decisions.items():
        for col, vals in cols.items():
            for val, d in vals.items():
                if d["action"] == "strip":
                    col_counts[col] += 1
    if col_counts:
        print(f"\n  Strip decisions by column:")
        for col, cnt in sorted(col_counts.items(), key=lambda x: -x[1]):
            print(f"    {col:20s}  {cnt}")

    # Value summary
    val_counts = defaultdict(int)
    for mc, cols in all_decisions.items():
        for col, vals in cols.items():
            for val, d in vals.items():
                if d["action"] == "strip":
                    val_counts[val] += 1
    if val_counts:
        print(f"\n  Most common stripped values:")
        for val, cnt in sorted(val_counts.items(), key=lambda x: -x[1])[:15]:
            print(f"    {cnt:4d}  {val!r}")

    # Write decisions
    if not args.dry_run and all_decisions:
        DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        DECISIONS_FILE.write_text(json.dumps(all_decisions, indent=2, ensure_ascii=False))
        print(f"\n  Decisions written to {DECISIONS_FILE}")
    elif args.dry_run:
        print(f"\n  [DRY RUN] Would write {len(all_decisions)} decisions to {DECISIONS_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Detect aggregate/total rows in parquet files")
    parser.add_argument("--matrix", help="Process single matrix (e.g. POP105A)")
    parser.add_argument("--auto-only", action="store_true", help="Auto-detect only, no interactive prompts")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing decisions file")
    parser.add_argument("--force", action="store_true", help="Re-check already-decided matrices")
    parser.add_argument("--fresh", action="store_true", help="Start fresh (ignore existing decisions)")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    run(args)


if __name__ == "__main__":
    main()
