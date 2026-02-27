#!/usr/bin/env python3
"""
11-slim-samples.py — Create slim sample CSVs for recent INS datasets.

Reads matrices-list.csv, filters to datasets updated in 2024+, then for each
dataset takes up to N evenly-distributed rows (default 100) and writes them to
data/4-datasets-slim-samples/.

Useful for analysis and LLM-based exploration without loading full CSVs.

Usage:
    python 11-slim-samples.py                   # All 2024+ datasets, 100 rows each
    python 11-slim-samples.py --year 2023        # Override minimum year
    python 11-slim-samples.py --limit 50         # Override sample size
    python 11-slim-samples.py --matrix ACC101B   # Single dataset (for testing)
"""

import argparse
import csv
import sys
from pathlib import Path

from duckdb_config import BASE_DIR

MATRICES_LIST = BASE_DIR / "data" / "1-indexes" / "ro" / "matrices-list.csv"
SOURCE_DIR    = BASE_DIR / "data" / "4-datasets" / "ro"
OUTPUT_DIR    = BASE_DIR / "data" / "4-datasets-slim-samples"


def sample_rows(rows: list, limit: int) -> list:
    """Return up to `limit` evenly-distributed rows from `rows`."""
    n = len(rows)
    if n <= limit:
        return rows
    step = n / limit
    return [rows[int(i * step)] for i in range(limit)]


def process_file(filename: str, limit: int, verbose: bool = False) -> dict:
    """
    Sample one dataset CSV file.

    Returns a stats dict: {filename, total_rows, sampled_rows, status}
    """
    src = SOURCE_DIR / f"{filename}.csv"
    dst = OUTPUT_DIR / f"{filename}.csv"

    if not src.exists():
        return {'filename': filename, 'status': 'missing', 'total_rows': 0, 'sampled_rows': 0}

    with open(src, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return {'filename': filename, 'status': 'empty', 'total_rows': 0, 'sampled_rows': 0}
        data_rows = list(reader)

    sampled = sample_rows(data_rows, limit)

    with open(dst, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(sampled)

    if verbose:
        print(f"  {filename}: {len(data_rows):,} → {len(sampled)} rows")

    return {
        'filename': filename,
        'status': 'ok',
        'total_rows': len(data_rows),
        'sampled_rows': len(sampled),
    }


def main():
    ap = argparse.ArgumentParser(description='Create slim sample CSVs for recent INS datasets')
    ap.add_argument('--year',   type=int, default=2024, help='Minimum update year (default: 2024)')
    ap.add_argument('--limit',  type=int, default=100,  help='Max rows per sample (default: 100)')
    ap.add_argument('--matrix', type=str,               help='Process only this matrix code')
    ap.add_argument('--verbose', action='store_true',   help='Log every file processed')
    args = ap.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("INS Slim Sample Generator")
    print("=" * 70)
    print(f"  Min year : {args.year}")
    print(f"  Row limit: {args.limit}")
    print(f"  Output   : {OUTPUT_DIR}")

    # ── Load matrices index ───────────────────────────────────────────────────
    if not MATRICES_LIST.exists():
        print(f"\nERROR: {MATRICES_LIST} not found", file=sys.stderr)
        sys.exit(1)

    with open(MATRICES_LIST, newline='', encoding='utf-8') as f:
        index = list(csv.DictReader(f))

    print(f"\n  Total datasets in index: {len(index):,}")

    # ── Filter by update year ─────────────────────────────────────────────────
    min_ymd = f"{args.year}-01-01"

    if args.matrix:
        targets = [row for row in index if row['filename'] == args.matrix]
        if not targets:
            print(f"\nERROR: '{args.matrix}' not found in index", file=sys.stderr)
            sys.exit(1)
    else:
        targets = [row for row in index if row.get('ymd', '') >= min_ymd]

    print(f"  Datasets updated {args.year}+: {len(targets):,}")
    print()

    # ── Process ───────────────────────────────────────────────────────────────
    stats = {'ok': 0, 'missing': 0, 'empty': 0}
    total_in = 0
    total_out = 0

    for i, row in enumerate(targets, 1):
        filename = row['filename']
        result = process_file(filename, args.limit, verbose=args.verbose)

        stats[result['status']] = stats.get(result['status'], 0) + 1
        total_in  += result['total_rows']
        total_out += result['sampled_rows']

        if not args.verbose and i % 50 == 0:
            print(f"  [{i:>4}/{len(targets)}] processed...")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)
    print(f"  Files written : {stats.get('ok', 0):,}")
    print(f"  Missing source: {stats.get('missing', 0):,}")
    print(f"  Empty files   : {stats.get('empty', 0):,}")
    print(f"  Total rows in : {total_in:,}")
    print(f"  Total rows out: {total_out:,}")
    if total_in:
        ratio = total_out / total_in * 100
        print(f"  Reduction     : {ratio:.1f}% of original")
    print(f"\n  Output: {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
