#!/usr/bin/env python3
"""
Build script for the static TEMPO INS explorer.

Exports all metadata from DuckDB into static JSON files, copies parquet data
and GeoJSON assets, and assembles the complete static site in _site/.

The generated site needs no backend — metadata is served as static JSON,
and dataset queries run via DuckDB-WASM in the browser against parquet files.

Usage:
    python build-static-site.py
    python build-static-site.py --output-dir _site --symlink-parquet
    python build-static-site.py --skip-parquet --base-data-url https://r2.example.com/data

See docs/plans/static-site-migration.md for the full architecture.
"""
import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Allow importing app modules (chart_selector, chart_config)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from app.services.chart_selector import build_signature, select_charts, assign_roles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build-static")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DATA_DIR = Path(__file__).parent / "data"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "_site"
FRONTEND_SRC_DIR = Path(__file__).parent / "static-site"
GEO_SRC_DIR = Path(__file__).parent / "app" / "static" / "geo"

# Tables that may not exist in all DuckDB versions
OPTIONAL_TABLES = {"dataset_coverage", "dataset_value_profiles", "dataset_trends", "dataset_splits"}


def parse_args():
    p = argparse.ArgumentParser(description="Build static TEMPO explorer site")
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                   help="Path to data/ directory (default: data/)")
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                   help="Output directory for the static site (default: _site/)")
    p.add_argument("--lang", default="ro", choices=["ro", "en"],
                   help="Language (default: ro)")
    p.add_argument("--symlink-parquet", action="store_true",
                   help="Symlink parquet files instead of copying (for dev)")
    p.add_argument("--skip-parquet", action="store_true",
                   help="Don't copy/link parquet files (when hosted separately)")
    p.add_argument("--base-data-url", default=None,
                   help="Base URL for parquet files if on different host (e.g. https://r2.example.com)")
    p.add_argument("--clean", action="store_true",
                   help="Remove output directory before building")
    p.add_argument("--debug", action="store_true",
                   help="Verbose logging")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def open_db(data_dir: Path):
    """Open DuckDB in read-only mode, return connection."""
    import duckdb
    db_path = data_dir / "tempo_metadata.duckdb"
    if not db_path.exists():
        log.error(f"DuckDB file not found: {db_path}")
        sys.exit(1)
    conn = duckdb.connect(str(db_path), read_only=True)
    log.info(f"Opened DuckDB: {db_path} ({db_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return conn


def table_exists(conn, table_name: str) -> bool:
    try:
        conn.execute(f"SELECT 1 FROM {table_name} LIMIT 0")
        return True
    except Exception:
        return False


def fetch_dict(conn, sql, params=None):
    """Execute SQL and return list of dicts."""
    result = conn.execute(sql, params or [])
    cols = [d[0] for d in result.description]
    return [dict(zip(cols, row)) for row in result.fetchall()]


def fetch_one_dict(conn, sql, params=None):
    """Execute SQL and return single dict or empty dict."""
    result = conn.execute(sql, params or [])
    cols = [d[0] for d in result.description]
    row = result.fetchone()
    return dict(zip(cols, row)) if row else {}


def describe_table(conn, table_name: str):
    """Get column names for a table."""
    return [r[0] for r in conn.execute(f"DESCRIBE {table_name}").fetchall()]


# ---------------------------------------------------------------------------
# 1. Build categories.json
# ---------------------------------------------------------------------------

def build_categories(conn, output_dir: Path):
    """Export category tree as api/categories.json."""
    log.info("Building categories.json...")

    contexts = conn.execute("""
        SELECT context_code, parent_code, level, context_name
        FROM contexts ORDER BY level, context_code
    """).fetchall()

    counts = {}
    for code, cnt in conn.execute("""
        SELECT context_code, COUNT(*) as cnt
        FROM matrices WHERE context_code IS NOT NULL
        GROUP BY context_code
    """).fetchall():
        counts[str(code)] = cnt

    nodes = {}
    for code, parent, level, name in contexts:
        code_s = str(code)
        nodes[code_s] = {
            'code': code_s,
            'name': (name or '').strip(),
            'level': level,
            'parent': str(parent),
            'dataset_count': counts.get(code_s, 0),
            'children': [],
        }

    roots = []
    for code_s, node in nodes.items():
        parent = node.pop('parent')
        if parent in nodes:
            nodes[parent]['children'].append(node)
        else:
            roots.append(node)

    def _sum_counts(node):
        total = node['dataset_count']
        for child in node['children']:
            total += _sum_counts(child)
        node['total_datasets'] = total
        return total

    for root in roots:
        _sum_counts(root)

    out_path = output_dir / "api" / "categories.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(out_path, {'tree': roots})
    log.info(f"  → {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")


# ---------------------------------------------------------------------------
# 2. Build datasets/index.json (full dataset list)
# ---------------------------------------------------------------------------

def build_dataset_index(conn, output_dir: Path):
    """Export full dataset list as api/datasets/index.json."""
    log.info("Building datasets/index.json...")

    rows = conn.execute("""
        SELECT
            m.matrix_code, m.matrix_name, m.context_code,
            m.ultima_actualizare, m.row_count,
            m.mat_max_dim as dim_count,
            p.archetype, p.has_time, p.has_geo,
            p.time_year_min, p.time_year_max,
            p.primary_unit_type, p.time_granularity,
            m.is_split, m.parent_matrix_code,
            COUNT(ds.sub_matrix_code) as split_count
        FROM matrices m
        LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
        LEFT JOIN dataset_splits ds ON ds.parent_matrix_code = m.matrix_code
        WHERE m.parquet_path IS NOT NULL
        GROUP BY m.matrix_code, m.matrix_name, m.context_code,
                 m.ultima_actualizare, m.row_count, m.mat_max_dim,
                 p.archetype, p.has_time, p.has_geo,
                 p.time_year_min, p.time_year_max,
                 p.primary_unit_type, p.time_granularity,
                 m.is_split, m.parent_matrix_code
        ORDER BY m.ultima_actualizare DESC NULLS LAST
    """).fetchall()

    datasets = []
    for r in rows:
        time_range = None
        if r[9] and r[10]:
            time_range = f"{r[9]}-{r[10]}"
        datasets.append({
            'matrix_code': r[0],
            'matrix_name': r[1],
            'context_code': r[2],
            'ultima_actualizare': str(r[3]) if r[3] else None,
            'row_count': r[4],
            'dim_count': r[5],
            'archetype': r[6],
            'has_time': bool(r[7]) if r[7] is not None else None,
            'has_geo': bool(r[8]) if r[8] is not None else None,
            'time_range': time_range,
            'primary_unit_type': r[11],
            'time_granularity': r[12],
            'is_split': bool(r[13]),
            'parent_matrix_code': r[14],
            'split_count': r[15] or 0,
        })

    out_path = output_dir / "api" / "datasets" / "index.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(out_path, {'total': len(datasets), 'datasets': datasets})
    log.info(f"  → {out_path} ({out_path.stat().st_size / 1024:.0f} KB, {len(datasets)} datasets)")

    # Also build search index (lightweight, for Fuse.js)
    search_index = []
    for d in datasets:
        search_index.append({
            'c': d['matrix_code'],
            'n': d['matrix_name'],
            'x': d['context_code'] or '',
        })
    search_path = output_dir / "api" / "search-index.json"
    _write_json(search_path, search_index)
    log.info(f"  → {search_path} ({search_path.stat().st_size / 1024:.0f} KB)")

    return [d['matrix_code'] for d in datasets]


# ---------------------------------------------------------------------------
# 3. Build per-dataset metadata JSON
# ---------------------------------------------------------------------------

def build_dataset_meta(conn, matrix_code: str, output_dir: Path, has_tables: dict):
    """Export single dataset metadata as api/datasets/{code}.json.

    This mirrors the GET /api/datasets/{code} endpoint exactly.
    """
    # Fetch matrix info
    m = conn.execute("""
        SELECT matrix_code, matrix_name, context_code, ancestor_codes,
               definitie, metodologie, ultima_actualizare, observatii,
               row_count, mat_max_dim, is_split, parent_matrix_code
        FROM matrices WHERE matrix_code = ?
    """, [matrix_code]).fetchone()

    if not m:
        return False

    # Fetch profile
    profile = {}
    profile_row = conn.execute(
        "SELECT * FROM matrix_profiles WHERE matrix_code = ?", [matrix_code]
    ).fetchone()
    if profile_row:
        profile_cols = describe_table(conn, "matrix_profiles")
        profile = dict(zip(profile_cols, profile_row))
        # Convert non-serializable types
        profile = _sanitize_for_json(profile)

    # Fetch dimensions with options
    dims_raw = conn.execute("""
        SELECT d.dim_code, d.dim_label, d.dim_column_name,
               d.option_count, d.dimension_id
        FROM dimensions d
        WHERE d.matrix_code = ?
        ORDER BY d.dim_code
    """, [matrix_code]).fetchall()

    dimensions = []
    for dim_code, dim_label, dim_col, opt_count, dim_id in dims_raw:
        options = conn.execute("""
            SELECT o.nom_item_id, o.option_label, o.option_offset, o.parent_id,
                   p.dim_type, p.year, p.quarter, p.month,
                   p.geo_level, p.geo_name_clean, p.gender,
                   p.age_min, p.age_max, p.unit_type, p.unit_scale, p.parse_confidence
            FROM dimension_options o
            LEFT JOIN dimension_options_parsed p ON o.nom_item_id = p.nom_item_id
            WHERE o.dimension_id = ?
            ORDER BY o.option_offset
        """, [dim_id]).fetchall()

        type_counts = {}
        option_list = []
        for opt in options:
            nom_id, label, offset, parent_id, dt, year, q, mo, geo_lvl, geo_name, gender, age_min, age_max, unit_type, unit_scale, conf = opt
            if dt:
                type_counts[dt] = type_counts.get(dt, 0) + 1

            parsed = {}
            if dt == 'time':
                parsed = {'year': year, 'quarter': q, 'month': mo}
            elif dt == 'geo':
                parsed = {'geo_level': geo_lvl, 'geo_name_clean': geo_name}
            elif dt == 'gender':
                parsed = {'gender': gender}
            elif dt == 'age':
                parsed = {'age_min': age_min, 'age_max': age_max}
            elif dt == 'unit':
                parsed = {'unit_type': unit_type, 'unit_scale': unit_scale}
            elif dt == 'residence':
                parsed = {'geo_level': geo_lvl, 'geo_name_clean': geo_name}

            option_list.append({
                'nom_item_id': nom_id,
                'label': label,
                'offset': offset,
                'parent_id': parent_id,
                'dim_type': dt,
                'parsed': parsed,
            })

        dim_type = max(type_counts, key=type_counts.get) if type_counts else 'indicator'

        dimensions.append({
            'dim_code': dim_code,
            'dim_label': dim_label,
            'dim_column_name': dim_col,
            'dim_type': dim_type,
            'option_count': opt_count,
            'options': option_list,
        })

    # Context path
    ancestor_codes_raw = m[3]
    if not ancestor_codes_raw and m[11]:  # inherit from parent
        parent_row = conn.execute(
            "SELECT ancestor_codes FROM matrices WHERE matrix_code = ?", [m[11]]
        ).fetchone()
        if parent_row:
            ancestor_codes_raw = parent_row[0]

    context_path = []
    if ancestor_codes_raw:
        ancestor_codes = ancestor_codes_raw if isinstance(ancestor_codes_raw, list) else []
        for ac in ancestor_codes:
            r = conn.execute(
                "SELECT context_name FROM contexts WHERE context_code = ?", [str(ac)]
            ).fetchone()
            if r:
                context_path.append({'code': str(ac), 'name': r[0]})

    # Split info
    is_split = bool(m[10])
    parent_matrix_code = m[11]

    splits = []
    if has_tables.get('dataset_splits'):
        try:
            split_rows = conn.execute("""
                SELECT sub_matrix_code, split_value, row_count, split_dimensions
                FROM dataset_splits WHERE parent_matrix_code = ?
                ORDER BY sub_matrix_code
            """, [matrix_code]).fetchall()
            splits = [
                {"matrix_code": r[0], "label": r[1], "row_count": r[2],
                 "split_dimensions": json.loads(r[3]) if r[3] else None}
                for r in split_rows
            ]
        except Exception:
            pass

    parent_info = None
    if is_split and parent_matrix_code:
        pr = conn.execute(
            "SELECT matrix_code, matrix_name FROM matrices WHERE matrix_code = ?",
            [parent_matrix_code]
        ).fetchone()
        if pr:
            parent_info = {"matrix_code": pr[0], "matrix_name": pr[1]}

    # Enriched metadata for chart scoring
    def fetch_table_row(table):
        if not has_tables.get(table):
            return {}
        row = conn.execute(f"SELECT * FROM {table} WHERE matrix_code = ?", [matrix_code]).fetchone()
        if not row:
            return {}
        cols = describe_table(conn, table)
        return _sanitize_for_json(dict(zip(cols, row)))

    coverage = fetch_table_row('dataset_coverage')
    value_profile = fetch_table_row('dataset_value_profiles')
    trend = fetch_table_row('dataset_trends')

    # Build chart config via scoring engine (same logic as the FastAPI endpoint)
    sig = build_signature(profile, dimensions, coverage, value_profile, trend)
    ranked = select_charts(sig)
    for entry in ranked:
        entry['roles'] = assign_roles(entry['chart_type'], dimensions)

    primary = ranked[0]['chart_type'] if ranked else 'table'

    geo_dim = next((d for d in dimensions if d['dim_type'] == 'geo'), None)
    time_dim = next((d for d in dimensions if d['dim_type'] == 'time'), None)

    unit_types_raw = profile.get('unit_types', '[]') or '[]'
    try:
        unit_types = json.loads(unit_types_raw) if isinstance(unit_types_raw, str) else (unit_types_raw or [])
    except (json.JSONDecodeError, TypeError):
        unit_types = []

    chart_config = {
        'ranked_charts': ranked,
        'primary_chart': primary,
        'supports': [r['chart_type'] for r in ranked],
        'archetype': sig['_archetype'],
        'dataset_signature': {k: v for k, v in sig.items() if not k.startswith('_')},
        'geo_dim': geo_dim['dim_column_name'] if geo_dim else None,
        'time_dim': time_dim['dim_column_name'] if time_dim else None,
        'multi_unit': len(unit_types) > 1,
        'unit_types': unit_types,
        'primary_unit_type': profile.get('primary_unit_type', 'count'),
    }

    result = {
        'matrix_code': m[0],
        'matrix_name': m[1],
        'context_code': m[2],
        'context_path': context_path,
        'definitie': m[4],
        'metodologie': m[5],
        'ultima_actualizare': str(m[6]) if m[6] else None,
        'observatii': m[7],
        'row_count': m[8],
        'dim_count': m[9],
        'is_split': is_split,
        'parent_matrix_code': parent_matrix_code,
        'splits': splits,
        'parent': parent_info,
        'profile': profile,
        'dimensions': dimensions,
        'chart_config': chart_config,
    }

    out_path = output_dir / "api" / "datasets" / f"{matrix_code}.json"
    _write_json(out_path, result)
    return True


def build_all_dataset_metas(conn, matrix_codes: list, output_dir: Path):
    """Export metadata for all datasets."""
    log.info(f"Building per-dataset metadata ({len(matrix_codes)} datasets)...")

    # Check which optional tables exist
    has_tables = {t: table_exists(conn, t) for t in OPTIONAL_TABLES}
    for t, exists in has_tables.items():
        log.info(f"  Table {t}: {'found' if exists else 'missing'}")

    success = 0
    errors = 0
    t0 = time.time()

    for i, code in enumerate(matrix_codes):
        try:
            ok = build_dataset_meta(conn, code, output_dir, has_tables)
            if ok:
                success += 1
            else:
                errors += 1
        except Exception as e:
            log.warning(f"  Error building {code}: {e}")
            errors += 1

        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            log.info(f"  Progress: {i + 1}/{len(matrix_codes)} ({rate:.0f}/s)")

    elapsed = time.time() - t0
    log.info(f"  → {success} datasets built, {errors} errors ({elapsed:.1f}s)")


# ---------------------------------------------------------------------------
# 4. Copy static assets (parquet, geo, frontend)
# ---------------------------------------------------------------------------

def copy_parquet_files(data_dir: Path, output_dir: Path, symlink: bool, skip: bool, lang: str):
    """Copy or symlink parquet files to _site/data/."""
    if skip:
        log.info("Skipping parquet files (--skip-parquet)")
        return

    parquet_src = data_dir / "parquet-v3" / lang
    if not parquet_src.exists():
        parquet_src = data_dir / "parquet-v2" / lang
    if not parquet_src.exists():
        log.warning(f"No parquet directory found at {parquet_src}")
        return

    dest = output_dir / "data"
    dest.mkdir(parents=True, exist_ok=True)

    files = list(parquet_src.glob("*.parquet"))
    log.info(f"{'Symlinking' if symlink else 'Copying'} {len(files)} parquet files...")

    for f in files:
        target = dest / f.name
        if target.exists() or target.is_symlink():
            target.unlink()
        if symlink:
            target.symlink_to(f.resolve())
        else:
            shutil.copy2(f, target)

    log.info(f"  → {dest}/ ({len(files)} files)")


def copy_geo_files(output_dir: Path):
    """Copy GeoJSON files to _site/geo/."""
    if not GEO_SRC_DIR.exists():
        log.warning(f"GeoJSON source not found: {GEO_SRC_DIR}")
        return

    dest = output_dir / "geo"
    dest.mkdir(parents=True, exist_ok=True)

    for f in GEO_SRC_DIR.glob("*.geojson"):
        shutil.copy2(f, dest / f.name)
        log.info(f"  → {dest / f.name}")


def copy_frontend(output_dir: Path):
    """Copy static-site/ frontend source to _site/."""
    if not FRONTEND_SRC_DIR.exists():
        log.warning(f"Frontend source not found: {FRONTEND_SRC_DIR}")
        return

    for item in FRONTEND_SRC_DIR.iterdir():
        dest = output_dir / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    log.info(f"  → Copied frontend from {FRONTEND_SRC_DIR}")


# ---------------------------------------------------------------------------
# 5. Build site config
# ---------------------------------------------------------------------------

def build_site_config(output_dir: Path, args):
    """Generate site-config.json with runtime configuration."""
    config = {
        'lang': args.lang,
        'base_data_url': args.base_data_url or './data',
        'base_api_url': './api',
        'duckdb_wasm_cdn': 'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm/dist/',
        'max_data_rows': 50000,
        'large_dataset_threshold': 50000,
    }
    out_path = output_dir / "site-config.json"
    _write_json(out_path, config)
    log.info(f"  → {out_path}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data, indent=None):
    """Write JSON file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':') if indent is None else None,
                  indent=indent, default=str)


def _sanitize_for_json(d: dict) -> dict:
    """Convert non-JSON-serializable types (Decimal, date, etc.) to primitives."""
    out = {}
    for k, v in d.items():
        if v is None:
            out[k] = None
        elif isinstance(v, (int, float, str, bool)):
            out[k] = v
        elif isinstance(v, list):
            out[k] = v
        elif hasattr(v, 'isoformat'):  # date/datetime
            out[k] = v.isoformat()
        else:
            out[k] = str(v)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("=" * 60)
    log.info("Building static TEMPO explorer site")
    log.info(f"  Data dir:   {args.data_dir}")
    log.info(f"  Output dir: {args.output_dir}")
    log.info(f"  Language:   {args.lang}")
    log.info("=" * 60)

    t_start = time.time()

    # Clean output if requested
    if args.clean and args.output_dir.exists():
        shutil.rmtree(args.output_dir)
        log.info(f"Cleaned {args.output_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Open database
    conn = open_db(args.data_dir)

    # 1. Categories
    build_categories(conn, args.output_dir)

    # 2. Dataset index (returns list of matrix_codes)
    matrix_codes = build_dataset_index(conn, args.output_dir)

    # 3. Per-dataset metadata
    build_all_dataset_metas(conn, matrix_codes, args.output_dir)

    # 4. Static assets
    log.info("Copying static assets...")
    copy_parquet_files(args.data_dir, args.output_dir, args.symlink_parquet,
                       args.skip_parquet, args.lang)
    copy_geo_files(args.output_dir)
    copy_frontend(args.output_dir)

    # 5. Site config
    build_site_config(args.output_dir, args)

    conn.close()

    elapsed = time.time() - t_start
    log.info("=" * 60)
    log.info(f"Build complete in {elapsed:.1f}s")
    log.info(f"Output: {args.output_dir}")

    # Summary
    api_dir = args.output_dir / "api"
    if api_dir.exists():
        json_files = list(api_dir.rglob("*.json"))
        total_size = sum(f.stat().st_size for f in json_files)
        log.info(f"  {len(json_files)} JSON files ({total_size / 1024 / 1024:.1f} MB)")

    log.info("=" * 60)


if __name__ == "__main__":
    main()
