#!/usr/bin/env python3
"""
12-csv-headers-index.py — Extract headers from all dataset CSVs into a single index file.

Creates data/2-metas/csv-headers-index.csv with columns:
  matrix_code,header_count,headers

Headers are comma-separated in the "headers" column.

Usage:
    python 12-csv-headers-index.py
"""

import csv
from pathlib import Path

from duckdb_config import BASE_DIR

# SOURCE_DIR = BASE_DIR / "data" / "4-datasets" / "ro"
SOURCE_DIR = BASE_DIR / "data" / "4-datasets-slim-samples"
OUTPUT_FILE = BASE_DIR / "data" / "2-metas" / "csv-headers-indexx.csv"


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("CSV Headers Index Generator")
    print("=" * 70)

    csv_files = sorted(SOURCE_DIR.glob("*.csv"))
    print(f"\nFound {len(csv_files):,} CSV files")

    rows = []
    for i, csv_file in enumerate(csv_files, 1):
        matrix_code = csv_file.stem

        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                print(f"  ⚠ {matrix_code}: empty file")
                continue

        # Quote headers that contain commas
        header_str = ",".join(f'"{h}"' if "," in h else h for h in headers)

        rows.append({
            "matrix_code": matrix_code,
            "header_count": len(headers),
            "headers": header_str,
        })

        if i % 200 == 0:
            print(f"  [{i:>4}/{len(csv_files)}] processed...")

    # Write output
    print(f"\nWriting {len(rows):,} rows to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["matrix_code", "header_count", "headers"])
        writer.writeheader()
        writer.writerows(rows)

    print("\n" + "=" * 70)
    print("✓ Done")
    print("=" * 70)
    print(f"  Output: {OUTPUT_FILE}")
    print(f"  Rows:   {len(rows):,}")
    print(f"  Size:   {OUTPUT_FILE.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
