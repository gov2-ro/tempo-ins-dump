#!/usr/bin/env python3
"""
Move stale view profiles to _stale/ directory.

Stale profiles fall into three categories:
1. Parent profiles — base matrix was split into sub-datasets, parent parquet removed
2. _nom_id profiles — reference old column names that don't match SDMX parquet columns
3. Empty datasets — 0 rows, no useful data

Usage:
    python scripts/cleanup-view-profiles.py          # dry run (default)
    python scripts/cleanup-view-profiles.py --apply   # actually move files
"""

import argparse
import glob
import json
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = PROJECT_ROOT / "data" / "corpus" / "view-profiles"
PARQUET_DIR = PROJECT_ROOT / "data" / "corpus" / "parquet"
STALE_DIR = PROFILES_DIR / "_stale"


def classify_profiles():
    """Classify all view profiles as valid or stale."""
    no_parquet = []
    nom_id_refs = []
    valid = []

    for path in sorted(PROFILES_DIR.glob("*.json")):
        if path.name == "_index.json":
            continue

        code = path.stem
        parquet_exists = (PARQUET_DIR / f"{code}.parquet").exists()

        with open(path) as f:
            content = f.read()
        has_nom_id = "_nom_id" in content

        if not parquet_exists:
            no_parquet.append(path)
        elif has_nom_id:
            nom_id_refs.append(path)
        else:
            valid.append(path)

    return no_parquet, nom_id_refs, valid


def main():
    parser = argparse.ArgumentParser(description="Move stale view profiles to _stale/")
    parser.add_argument("--apply", action="store_true", help="Actually move files (default: dry run)")
    args = parser.parse_args()

    if not PROFILES_DIR.exists():
        print(f"Error: {PROFILES_DIR} does not exist")
        sys.exit(1)

    no_parquet, nom_id_refs, valid = classify_profiles()

    print(f"View profile classification:")
    print(f"  Valid:              {len(valid)}")
    print(f"  No parquet (stale): {len(no_parquet)}")
    print(f"  _nom_id refs:       {len(nom_id_refs)}")
    print(f"  Total stale:        {len(no_parquet) + len(nom_id_refs)}")
    print()

    stale = no_parquet + nom_id_refs

    if not stale:
        print("Nothing to clean up.")
        return

    if not args.apply:
        print("Dry run — files that would be moved:")
        for p in no_parquet[:5]:
            print(f"  [no parquet] {p.name}")
        if len(no_parquet) > 5:
            print(f"  ... and {len(no_parquet) - 5} more")
        for p in nom_id_refs[:5]:
            print(f"  [_nom_id]    {p.name}")
        if len(nom_id_refs) > 5:
            print(f"  ... and {len(nom_id_refs) - 5} more")
        print(f"\nRun with --apply to move {len(stale)} files to {STALE_DIR}/")
        return

    # Move files
    STALE_DIR.mkdir(exist_ok=True)
    moved = 0
    for path in stale:
        dest = STALE_DIR / path.name
        shutil.move(str(path), str(dest))
        moved += 1

    print(f"Moved {moved} stale profiles to {STALE_DIR}/")
    print(f"  {len(no_parquet)} parent/empty (no parquet)")
    print(f"  {len(nom_id_refs)} _nom_id column refs")


if __name__ == "__main__":
    main()
