#!/usr/bin/env python3
"""
13-slim-samples-to-markdown.py — Convert slim-sample CSVs to markdown for LLM analysis.

Reads all CSVs from data/4-datasets-slim-samples/, groups them by header structure,
and outputs a single markdown file with one table per unique header (deduplicates).

Usage:
    python 13-slim-samples-to-markdown.py
    python 13-slim-samples-to-markdown.py --limit 50    # Include max 50 rows per table
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from duckdb_config import BASE_DIR

SOURCE_DIR = BASE_DIR / "data" / "4-datasets-slim-samples" / "50"
OUTPUT_FILE = BASE_DIR / "docs" / "slim-sampless.md"


def main():
    ap = argparse.ArgumentParser(description='Convert slim-sample CSVs to markdown')
    ap.add_argument('--limit', type=int, default=50, help='Max rows per table (default: 50)')
    args = ap.parse_args()

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Slim Samples to Markdown Converter")
    print("=" * 70)

    csv_files = sorted(SOURCE_DIR.glob("*.csv"))
    print(f"\nFound {len(csv_files):,} CSV files in {SOURCE_DIR}")

    # ── Group by header ───────────────────────────────────────────────────────
    header_to_files: dict[tuple, list] = defaultdict(list)

    for csv_file in csv_files:
        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            try:
                headers = tuple(next(reader))
            except StopIteration:
                print(f"  ⚠ {csv_file.stem}: empty file")
                continue

        header_to_files[headers].append(csv_file)

    print(f"Unique headers: {len(header_to_files)}")
    print(f"Datasets per header: {len(csv_files) / len(header_to_files):.1f} avg")
    print()

    # ── Build markdown ────────────────────────────────────────────────────────
    md_lines = [
        "# Slim Sample Datasets",
        "",
        f"Generated from {len(csv_files)} datasets with {len(header_to_files)} unique column structures.",
        "",
        "Each section represents a unique table schema. Datasets with identical headers are grouped together.",
        "",
    ]

    table_num = 0
    for header_tuple, files in sorted(header_to_files.items(), key=lambda x: -len(x[1])):
        table_num += 1
        headers = list(header_tuple)

        # Dataset list
        dataset_codes = sorted([f.stem for f in files])
        md_lines.append(f"## Table {table_num} — {len(dataset_codes)} datasets")
        md_lines.append("")
        md_lines.append(f"**Datasets:** `{', '.join(dataset_codes)}`")
        md_lines.append("")

        # Column info
        md_lines.append(f"**Columns ({len(headers)}):**")
        md_lines.append("")
        for i, h in enumerate(headers, 1):
            md_lines.append(f"{i:2}. {h}")
        md_lines.append("")

        # Data from first file
        first_file = files[0]
        with open(first_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            data_rows = list(reader)[:args.limit]

        md_lines.append(f"**Sample data** (from `{first_file.stem}`, {len(data_rows)} rows):")
        md_lines.append("")
        md_lines.append("| " + " | ".join(headers) + " |")
        md_lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for row in data_rows:
            # Pad row with empty strings if needed
            padded = row + [""] * (len(headers) - len(row))
            md_lines.append("| " + " | ".join(padded[:len(headers)]) + " |")
        md_lines.append("")

    # Write output
    md_content = "\n".join(md_lines)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(md_content)

    print("=" * 70)
    print("✓ Done")
    print("=" * 70)
    print(f"  Output:   {OUTPUT_FILE}")
    print(f"  Tables:   {table_num}")
    print(f"  Size:     {OUTPUT_FILE.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
