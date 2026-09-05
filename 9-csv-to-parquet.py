"""
9-csv-to-parquet.py — Convert INS CSV exports directly to canonical SDMX parquet.

This stage now does what stage 9 + 12 used to do together:
  1. Read the original CSV (text labels, commas mangled to double spaces).
  2. Map each dimension value: time dims via parse_time_period(), everything
     else via a normalised-label lookup against sdmx_codes. No match -> keep
     the cleaned original text and record it in unmapped_labels (never NULL).
  3. Rename columns via sdmx_column_map (value -> OBS_VALUE).
  4. Write to a temp file, then atomic rename onto the final path.

12-parquet-to-sdmx.py (deprecated) used to do step 2-3 as a second pass over
data/parquet-v2/, which was a dead, lossy Feb-2026 snapshot — see
docs/stage9-sdmx-migration-spec.md for the full history and design.

CORPUS_PARQUET_DIR is the live corpus (data/corpus/parquet/) by default —
pass --out-dir with a shadow path for any development/verification run.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from duckdb_config import (
    METAS_DIR,
    CSV_SOURCE_DIR,
    CORPUS_PARQUET_DIR,
    LOGS_DIR,
    DB_FILE,
    PARQUET_COMPRESSION,
    PROGRESS_INTERVAL,
    TEST_LIMIT,
    sanitize_column_name,
)
from sdmx_labels import norm_label, norm_label_cs, clean_label, parse_time_period

# Exit non-zero for a single matrix only when unmatched cells exceed this —
# spec §2.3: "that threshold means something structural broke, not that a
# few new options appeared."
UNMATCHED_EXIT_THRESHOLD = 0.50

_DIACRITICS = str.maketrans("ăâîșțĂÂÎȘȚ", "aaistAAIST")

UNMAPPED_LABELS_SCHEMA = """
CREATE TABLE IF NOT EXISTS unmapped_labels (
    matrix_code VARCHAR NOT NULL,
    dim_column_name VARCHAR NOT NULL,
    raw_label VARCHAR NOT NULL,
    row_count BIGINT NOT NULL,
    seen_at TIMESTAMP NOT NULL
);
"""


def _fallback_column_name(label: str) -> str:
    """Pure syntactic SDMX-ish name, used only when sdmx_column_map has no
    entry for a dimension (matrix missing from the map entirely, or one
    column within an otherwise-mapped matrix). Never falls back to the raw
    *_nom_id name — spec §2.4 calls that out as the stage-12 bug to avoid."""
    s = re.sub(r'^UM:\s*', '', label).translate(_DIACRITICS)
    s = re.sub(r'[^a-zA-Z0-9\s]', '', s)
    s = '_'.join(s.upper().split())
    if len(s) > 40:
        s = s[:40].rstrip('_')
    return s or "DIM"


def _uniquify(name: str, used: set) -> str:
    """Disambiguate a repeated target column name instead of silently
    collapsing dimensions into one column — repo trap #4: INT109C has four
    CAEN dimensions (sectiuni/diviziuni/grupe/clase) that all classify to
    ECON_ACTIVITY; sdmx_column_map only kept one because it deduped on the
    truncated *_nom_id name before uniquifying. Here every position gets a
    name: ECON_ACTIVITY, ECON_ACTIVITY_2, ECON_ACTIVITY_3, ECON_ACTIVITY_4."""
    if name not in used:
        used.add(name)
        return name
    i = 2
    while f"{name}_{i}" in used:
        i += 1
    unique = f"{name}_{i}"
    used.add(unique)
    return unique


# ── Metadata loading ─────────────────────────────────────────────────────────

def load_dimension_labels(matrix_code: str) -> list:
    """Dimension labels in CSV column order, from the metadata JSON."""
    json_file = METAS_DIR / f"{matrix_code}.json"
    if not json_file.exists():
        raise FileNotFoundError(f"Metadata not found: {json_file}")
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    dims = data.get('dimensionsMap', [])
    if not dims:
        raise ValueError(f"No dimensions found in metadata for {matrix_code}")
    return [d['label'] for d in dims]


class Lookups:
    """Everything needed from metadata.duckdb, loaded once per run.

    The connection is closed right after this — every matrix conversion after
    that is pure CSV + in-memory dict work, so a shadow run never needs the
    live DB open while it writes (repo trap #2: only one DuckDB writer).
    """

    def __init__(self, conn):
        self.parent_of = dict(conn.execute(
            "SELECT matrix_code, parent_matrix_code FROM matrices "
            "WHERE parent_matrix_code IS NOT NULL").fetchall())

        self.column_map = {}
        for mc, old, new in conn.execute(
            "SELECT matrix_code, old_column_name, sdmx_column_name FROM sdmx_column_map"
        ).fetchall():
            self.column_map.setdefault(mc, {})[old] = new

        # Two lookups per dimension: exact-case first, case-insensitive as
        # fallback. Some dimensions have two genuinely distinct nom_item_ids
        # that differ only by case (AGR208A has both 'PLANTATII' — a section
        # header — and 'Plantatii' — a line item); a single lowercased
        # lookup would silently conflate them. Trying the case-preserving
        # key first keeps both distinct while still catching a CSV/metadata
        # mismatch that really is case-only.
        self.value_map_cs = {}
        self.value_map_ci = {}
        for mc, dim_code, option_label, sdmx_value in conn.execute("""
            SELECT d.matrix_code, d.dim_code, o.option_label, s.sdmx_value
            FROM dimensions d
            JOIN dimension_options o ON o.dimension_id = d.dimension_id
            LEFT JOIN sdmx_codes s ON s.nom_item_id = o.nom_item_id
        """).fetchall():
            target = sdmx_value if sdmx_value is not None else clean_label(option_label)
            self.value_map_cs.setdefault(mc, {}).setdefault(dim_code, {})[norm_label_cs(option_label)] = target
            self.value_map_ci.setdefault(mc, {}).setdefault(dim_code, {})[norm_label(option_label)] = target

        self.dim_count = dict(conn.execute(
            "SELECT matrix_code, COUNT(*) FROM dimensions GROUP BY matrix_code").fetchall())

        # Keyed by dim_code (position), not by label text — dim_column_name
        # is *_nom_id for matrices sdmx_column_map hasn't resolved yet, and
        # already the final SDMX name for the rest (see class docstring below
        # on why we don't recompute this from the current label).
        self.dim_column_name = {}
        for mc, dim_code, dcn in conn.execute(
            "SELECT matrix_code, dim_code, dim_column_name FROM dimensions"
        ).fetchall():
            self.dim_column_name.setdefault(mc, {})[dim_code] = dcn


def resolve_column_names(matrix_code: str, labels: list, lookups: Lookups):
    """Final SDMX column name per CSV dimension position.

    Returns (names, unmapped_old_names, is_time_flags). Every position gets a
    name; an unmapped column is recorded, never left with its raw name.

    Column identity is resolved by dim_code (position), via
    dimensions.dim_column_name, not by re-sanitising the *current* metadata
    label. INS renames dimension labels between fetches (e.g. INT109C's and
    ART101C's time dimension is "Ani" today but was "Perioade" when
    dimensions/sdmx_column_map were built as "perioade_nom_id") — a fresh
    sanitize_column_name(label) on the current JSON would silently miss the
    sdmx_column_map row that already exists under the old name, and every
    such dimension would wrongly fall back to an ad hoc name instead of its
    real SDMX one. dim_code doesn't drift when only the label text does.
    """
    lookup_matrix = lookups.parent_of.get(matrix_code, matrix_code)
    colmap = lookups.column_map.get(lookup_matrix, {})
    db_names = lookups.dim_column_name.get(matrix_code, {})
    used = set()
    names, unmapped, is_time = [], [], []
    unmapped_positions = []
    for i, label in enumerate(labels):
        dim_code = i + 1
        db_name = db_names.get(dim_code)
        old = db_name if db_name is not None else sanitize_column_name(label)
        if db_name is not None and not db_name.endswith('_nom_id'):
            base = db_name  # dimensions row already carries the resolved SDMX name
        else:
            base = colmap.get(old)
            if base is None:
                base = _fallback_column_name(label)
                unmapped_positions.append(i)
        is_time.append(base == "TIME_PERIOD")
        names.append(_uniquify(base, used))
    unmapped = [names[i] for i in unmapped_positions]
    return names, unmapped, is_time


# ── Per-matrix conversion ───────────────────────────────────────────────────

def convert_matrix(matrix_code: str, lookups: Lookups, conn, out_dir: Path) -> dict:
    """Convert one CSV to a canonical SDMX parquet. Never writes NULL for an
    unmatched dimension value — the cleaned original text is kept instead."""
    stats = {
        'matrix_code': matrix_code, 'success': False, 'error': None,
        'rows': 0, 'total_cells': 0, 'unmatched_cells': 0, 'unmatched_pct': 0.0,
        'unmapped_columns': [], 'columns': [], 'unmapped_rows': [],
    }

    csv_file = CSV_SOURCE_DIR / f"{matrix_code}.csv"
    if not csv_file.exists():
        stats['error'] = "CSV file not found"
        return stats

    # A header-only CSV (no data rows) leaves auto_detect nothing to sniff,
    # so read_csv degrades to a single VARCHAR column and the CAST-based
    # SELECT below fails with a confusing binder error instead of a clear
    # one. Catch it here — seen on EXP101F / EXP102F.
    with open(csv_file, 'r', encoding='utf-8', errors='replace') as f:
        f.readline()
        if f.readline() == '':
            stats['error'] = "CSV file is empty"
            return stats

    try:
        labels = load_dimension_labels(matrix_code)
    except Exception as e:
        stats['error'] = f"Metadata error: {e}"
        return stats

    num_dims = len(labels)
    db_dim_count = lookups.dim_count.get(matrix_code)
    if db_dim_count is not None and db_dim_count != num_dims:
        stats['error'] = (f"dim_code order mismatch: metadata JSON has {num_dims} dims, "
                           f"DB `dimensions` has {db_dim_count} for {matrix_code}")
        return stats

    names, unmapped_cols, is_time = resolve_column_names(matrix_code, labels, lookups)

    dim_casts = ", ".join(f"CAST(column{i} AS VARCHAR) AS column{i}" for i in range(num_dims))
    try:
        conn.execute(f"""
            CREATE OR REPLACE TEMP TABLE csv_tmp AS
            SELECT {dim_casts}, column{num_dims} AS value_raw
            FROM read_csv('{csv_file}', header=false, skip=1, delim=',', auto_detect=true)
        """)
    except Exception as e:
        stats['error'] = f"CSV read error: {e}"
        return stats

    total_rows = conn.execute("SELECT COUNT(*) FROM csv_tmp").fetchone()[0]
    if total_rows == 0:
        stats['error'] = "CSV file is empty"
        return stats

    value_lut_cs_all = lookups.value_map_cs.get(matrix_code, {})
    value_lut_ci_all = lookups.value_map_ci.get(matrix_code, {})
    select_parts = []
    join_parts = []
    total_unmatched = 0
    unmapped_rows = []  # (dim_column_name, raw_label, row_count) for unmapped_labels

    try:
        for i in range(num_dims):
            dim_code = i + 1
            lut_cs = value_lut_cs_all.get(dim_code, {})
            lut_ci = value_lut_ci_all.get(dim_code, {})
            distincts = conn.execute(
                f"SELECT column{i} AS raw, COUNT(*) AS cnt FROM csv_tmp GROUP BY column{i}"
            ).fetchall()

            mapped_rows = []
            for raw, cnt in distincts:
                raw_s = raw if raw is not None else ""
                final = parse_time_period(raw_s.strip()) if is_time[i] else None
                if final is None:
                    final = lut_cs.get(norm_label_cs(raw_s))
                if final is None:
                    final = lut_ci.get(norm_label(raw_s))
                if final is None and not is_time[i]:
                    # Opportunistic: a column with no sdmx_column_map entry
                    # (spec §8's 47 unfixed matrices) never gets is_time=True,
                    # so a genuinely time-shaped value here would otherwise
                    # fall through to clean_label unmatched even though the
                    # parser would happily read it. Cheap and can't false
                    # -positive — the patterns are narrow and anchored.
                    final = parse_time_period(raw_s.strip())
                if final is None:
                    final = clean_label(raw_s)
                    total_unmatched += cnt
                    unmapped_rows.append((names[i], raw_s, cnt))
                mapped_rows.append((raw, final))

            map_df = pd.DataFrame(mapped_rows, columns=["raw", "mapped"])
            conn.register(f"dimmap_{i}", map_df)
            select_parts.append(f'dimmap_{i}.mapped AS "{names[i]}"')
            join_parts.append(f'LEFT JOIN dimmap_{i} ON csv_tmp.column{i} IS NOT DISTINCT FROM dimmap_{i}.raw')

        select_parts.append('TRY_CAST(csv_tmp.value_raw AS DOUBLE) AS OBS_VALUE')

        out_dir.mkdir(parents=True, exist_ok=True)
        final_path = out_dir / f"{matrix_code}.parquet"
        tmp_path = out_dir / f"{matrix_code}.parquet.tmp"

        sql = f"""
            COPY (
                SELECT {', '.join(select_parts)}
                FROM csv_tmp
                {' '.join(join_parts)}
            ) TO '{tmp_path}' (FORMAT PARQUET, COMPRESSION '{PARQUET_COMPRESSION}')
        """
        conn.execute(sql)
        os.replace(tmp_path, final_path)
    except Exception as e:
        stats['error'] = f"Write error: {e}"
        tmp_path = out_dir / f"{matrix_code}.parquet.tmp"
        if tmp_path.exists():
            tmp_path.unlink()
        return stats
    finally:
        for i in range(num_dims):
            try:
                conn.unregister(f"dimmap_{i}")
            except Exception:
                pass

    stats['rows'] = total_rows
    stats['total_cells'] = total_rows * num_dims
    stats['unmatched_cells'] = total_unmatched
    stats['unmatched_pct'] = (total_unmatched / stats['total_cells']) if stats['total_cells'] else 0.0
    stats['unmapped_columns'] = unmapped_cols
    stats['columns'] = names
    stats['unmapped_rows'] = unmapped_rows
    for old_col in unmapped_cols:
        stats['unmapped_rows'].append((old_col, '<column>', total_rows))
    stats['success'] = True

    if stats['unmatched_pct'] > UNMATCHED_EXIT_THRESHOLD:
        stats['success'] = False
        stats['error'] = (f"{total_unmatched:,} unmatched of {stats['total_cells']:,} cells "
                           f"({stats['unmatched_pct']:.1%}) — structural mismatch, exceeds "
                           f"{UNMATCHED_EXIT_THRESHOLD:.0%} threshold")

    return stats


def write_unmapped_labels(db_conn, rows_by_matrix: dict):
    """Replace each matrix's unmapped_labels rows — no accumulation across runs."""
    db_conn.execute(UNMAPPED_LABELS_SCHEMA)
    now = datetime.now(timezone.utc)
    for matrix_code, rows in rows_by_matrix.items():
        db_conn.execute("DELETE FROM unmapped_labels WHERE matrix_code = ?", [matrix_code])
        if rows:
            db_conn.executemany(
                "INSERT INTO unmapped_labels VALUES (?, ?, ?, ?, ?)",
                [(matrix_code, col, raw, cnt, now) for col, raw, cnt in rows],
            )


def main():
    parser = argparse.ArgumentParser(description="Convert CSVs directly to canonical SDMX parquet")
    parser.add_argument('--matrix', help="Process a single matrix (e.g. TUR104C)")
    parser.add_argument('--force', action='store_true', help="Re-process existing files")
    parser.add_argument('--out-dir', type=Path, default=CORPUS_PARQUET_DIR,
                         help="Output directory. Defaults to the live corpus — "
                              "pass a shadow path for any dev/verification run.")
    parser.add_argument('--limit', type=int, help="Process only first N matrices (testing)")
    args = parser.parse_args()

    out_dir = args.out_dir
    is_shadow = out_dir.resolve() != CORPUS_PARQUET_DIR.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("CSV to SDMX Parquet Conversion" + (" [SHADOW]" if is_shadow else " [LIVE CORPUS]"))
    print("=" * 70)
    print(f"Output: {out_dir}")

    meta_conn = duckdb.connect(str(DB_FILE), read_only=True)
    lookups = Lookups(meta_conn)
    meta_conn.close()

    if args.matrix:
        matrices = [args.matrix]
    else:
        json_files = sorted(METAS_DIR.glob("*.json"))
        matrices = [f.stem for f in json_files if (CSV_SOURCE_DIR / f"{f.stem}.csv").exists()]
        if TEST_LIMIT:
            matrices = matrices[:TEST_LIMIT]
        if args.limit:
            matrices = matrices[:args.limit]
        print(f"Found {len(matrices)} matrices with a source CSV")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"sdmx-conversion-{timestamp}.log"
    unmapped_json = LOGS_DIR / f"unmapped-labels-{timestamp}.json"

    conn = duckdb.connect()  # in-memory, CSV processing only

    processed = skipped = errors = structural_failures = 0
    unmapped_by_matrix = {}

    with open(log_file, 'w', encoding='utf-8') as log:
        log.write(f"SDMX parquet conversion log - {timestamp} - out_dir={out_dir}\n\n")

        for idx, matrix_code in enumerate(matrices, 1):
            final_path = out_dir / f"{matrix_code}.parquet"
            if final_path.exists() and not args.force:
                skipped += 1
                if idx % PROGRESS_INTERVAL == 0:
                    print(f"Progress: {idx}/{len(matrices)} (ok:{processed} skip:{skipped} err:{errors})")
                continue

            stats = convert_matrix(matrix_code, lookups, conn, out_dir)
            unmapped_by_matrix[matrix_code] = stats['unmapped_rows']

            if stats['success']:
                processed += 1
                msg = (f"OK {matrix_code}: {stats['rows']:,} rows, "
                       f"{stats['unmatched_cells']:,}/{stats['total_cells']:,} unmatched "
                       f"({stats['unmatched_pct']:.1%})")
                if stats['unmapped_columns']:
                    msg += f", {len(stats['unmapped_columns'])} unmapped column(s)"
            else:
                errors += 1
                if stats['unmatched_pct'] > UNMATCHED_EXIT_THRESHOLD:
                    structural_failures += 1
                msg = f"FAIL {matrix_code}: {stats['error']}"

            print(msg)
            log.write(msg + "\n")

            if idx % PROGRESS_INTERVAL == 0:
                print(f"Progress: {idx}/{len(matrices)} (ok:{processed} skip:{skipped} err:{errors})")

    conn.close()

    with open(unmapped_json, 'w', encoding='utf-8') as f:
        json.dump(
            {mc: [{"column": c, "raw_label": r, "row_count": n} for c, r, n in rows]
             for mc, rows in unmapped_by_matrix.items() if rows},
            f, ensure_ascii=False, indent=2,
        )

    if not is_shadow and unmapped_by_matrix:
        db_conn = duckdb.connect(str(DB_FILE))
        write_unmapped_labels(db_conn, unmapped_by_matrix)
        db_conn.close()
        print(f"\nunmapped_labels table updated for {len(unmapped_by_matrix)} matrices")
    elif unmapped_by_matrix:
        print(f"\n[SHADOW] unmapped_labels DB write skipped — see {unmapped_json}")

    summary = f"""
{'=' * 70}
Conversion Summary
{'=' * 70}
Total matrices: {len(matrices)}
Processed: {processed}
Skipped: {skipped}
Errors: {errors}  (of which {structural_failures} exceeded the {UNMATCHED_EXIT_THRESHOLD:.0%} unmatched threshold)

Output directory: {out_dir}
Log file: {log_file}
Unmapped-labels report: {unmapped_json}
"""
    print(summary)
    with open(log_file, 'a', encoding='utf-8') as log:
        log.write(summary + "\n")

    if errors and (args.matrix or processed == 0):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
