#!/usr/bin/env python3
"""
Audit the data corpus: cross-reference parquet files, DuckDB metadata,
and dataset_splits to classify every file and detect inconsistencies.

Outputs:
  - Console summary with counts per category
  - data/logs/corpus-audit.json manifest

Categories:
  - canonical-unsplit: original dataset, not split, has v3 parquet
  - canonical-split: sub-dataset from a split, has v3 parquet
  - parent-has-splits: original that was split (should be archived)
  - orphan-untracked: parquet file not tracked in any DB table
  - split-missing-v3: in dataset_splits but no v3 parquet (may be v2-only)
"""
import json
import sys
from datetime import datetime
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))
from duckdb_config import DB_FILE, PARQUET_V2_DIR, DATA_DIR

PARQUET_V3_DIR = DATA_DIR / "parquet-v3" / "ro"

import duckdb


def audit():
    conn = duckdb.connect(str(DB_FILE), read_only=True)

    # ── 1. Load DB state ─────────────────────────────────────────────────
    # All matrix codes in the matrices table
    matrices = {r[0]: dict(zip(
        ['matrix_code', 'is_split', 'parent_matrix_code', 'parquet_path', 'row_count'],
        r
    )) for r in conn.execute("""
        SELECT matrix_code, is_split, parent_matrix_code, parquet_path, row_count
        FROM matrices
    """).fetchall()}

    # Parent codes that have splits
    parent_codes = set(conn.execute("""
        SELECT DISTINCT parent_matrix_code FROM dataset_splits
    """).fetchall())
    parent_codes = {r[0] for r in parent_codes}

    # Sub-dataset codes from splits
    split_codes = set(conn.execute("""
        SELECT DISTINCT sub_matrix_code FROM dataset_splits
    """).fetchall())
    split_codes = {r[0] for r in split_codes}

    # Table row counts
    tables = conn.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
    """).fetchall()
    table_counts = {}
    for (tbl,) in tables:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        table_counts[tbl] = cnt

    # Profiling coverage for sub-datasets
    profiled_splits = {}
    for tbl in ['matrix_profiles', 'dataset_coverage', 'dataset_value_profiles', 'dataset_trends']:
        if tbl in table_counts:
            rows = conn.execute(f"""
                SELECT COUNT(*) FROM {tbl}
                WHERE matrix_code IN (SELECT sub_matrix_code FROM dataset_splits)
            """).fetchone()[0]
            profiled_splits[tbl] = rows

    conn.close()

    # ── 2. Scan parquet directories ──────────────────────────────────────
    v3_files = {}
    if PARQUET_V3_DIR.exists():
        for f in PARQUET_V3_DIR.glob("*.parquet"):
            code = f.stem
            v3_files[code] = {'path': str(f), 'size': f.stat().st_size}

    v2_files = {}
    if PARQUET_V2_DIR.exists():
        for f in PARQUET_V2_DIR.glob("*.parquet"):
            code = f.stem
            v2_files[code] = {'path': str(f), 'size': f.stat().st_size}

    # ── 3. Classify each entity ──────────────────────────────────────────
    classified = {
        'canonical-unsplit': [],
        'canonical-split': [],
        'parent-has-splits': [],
        'orphan-untracked': [],
        'split-missing-v3': [],
        'split-v2-only': [],
    }

    # Classify v3 files
    for code, info in sorted(v3_files.items()):
        if code in split_codes:
            classified['canonical-split'].append(code)
        elif code in parent_codes:
            classified['parent-has-splits'].append(code)
        elif code in matrices:
            classified['canonical-unsplit'].append(code)
        else:
            classified['orphan-untracked'].append(code)

    # Check for splits that exist only in v2
    for code in sorted(split_codes):
        if code not in v3_files:
            if code in v2_files:
                classified['split-v2-only'].append(code)
            else:
                classified['split-missing-v3'].append(code)

    # ── 4. View profiles audit ───────────────────────────────────────────
    vp_dir = Path("data/view-profiles")
    vp_files = set()
    vp_orphans = []
    if vp_dir.exists():
        for f in vp_dir.glob("*.json"):
            if f.name.startswith("_"):
                continue
            code = f.stem
            vp_files.add(code)
            all_canonical = set(classified['canonical-unsplit'] + classified['canonical-split'])
            if code not in all_canonical and code not in parent_codes:
                vp_orphans.append(code)

    # ── 5. Build manifest ────────────────────────────────────────────────
    manifest = {
        'timestamp': datetime.now().isoformat(),
        'summary': {
            'v3_parquet_files': len(v3_files),
            'v2_parquet_files': len(v2_files),
            'matrices_in_db': len(matrices),
            'parent_codes': len(parent_codes),
            'split_codes': len(split_codes),
        },
        'classification': {k: len(v) for k, v in classified.items()},
        'table_row_counts': table_counts,
        'profiling_coverage_for_splits': profiled_splits,
        'view_profiles': {
            'total': len(vp_files),
            'orphans': len(vp_orphans),
        },
        'details': {
            'orphan_untracked': classified['orphan-untracked'][:50],
            'split_v2_only': classified['split-v2-only'][:50],
            'split_missing_v3': classified['split-missing-v3'][:50],
            'vp_orphans_sample': vp_orphans[:50],
        }
    }

    # ── 6. Output ────────────────────────────────────────────────────────
    total_v3_size = sum(f['size'] for f in v3_files.values())
    parent_size = sum(v3_files[c]['size'] for c in classified['parent-has-splits'] if c in v3_files)

    print("=" * 65)
    print("  CORPUS AUDIT REPORT")
    print("=" * 65)
    print()
    print(f"  Parquet v3 files:      {len(v3_files):>6}  ({total_v3_size / 1e6:.1f} MB)")
    print(f"  Parquet v2 files:      {len(v2_files):>6}")
    print(f"  Matrices in DB:        {len(matrices):>6}")
    print(f"  Parent codes (split):  {len(parent_codes):>6}")
    print(f"  Sub-dataset codes:     {len(split_codes):>6}")
    print()
    print("  Classification of v3 files:")
    print(f"    canonical-unsplit:   {len(classified['canonical-unsplit']):>6}  (keep)")
    print(f"    canonical-split:     {len(classified['canonical-split']):>6}  (keep)")
    print(f"    parent-has-splits:   {len(classified['parent-has-splits']):>6}  (→ archive, {parent_size / 1e6:.1f} MB)")
    print(f"    orphan-untracked:    {len(classified['orphan-untracked']):>6}  (investigate)")
    print()
    print(f"  Splits missing from v3:")
    print(f"    v2-only:             {len(classified['split-v2-only']):>6}  (need conversion)")
    print(f"    missing entirely:    {len(classified['split-missing-v3']):>6}")
    print()
    print(f"  Profiling coverage for sub-datasets:")
    for tbl, cnt in profiled_splits.items():
        print(f"    {tbl:30s} {cnt:>6} / {len(split_codes)}")
    print()
    print(f"  View profiles:         {len(vp_files):>6}")
    print(f"    orphaned:            {len(vp_orphans):>6}")
    print()
    print(f"  DuckDB table row counts:")
    for tbl, cnt in sorted(table_counts.items()):
        print(f"    {tbl:30s} {cnt:>8}")
    print()
    print("=" * 65)

    # Save manifest
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    out_path = log_dir / "corpus-audit.json"
    with open(out_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    print(f"  Manifest saved to: {out_path}")
    print()

    return manifest


if __name__ == "__main__":
    audit()
