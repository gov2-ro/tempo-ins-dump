#!/usr/bin/env python3
"""
Internal Data Explorer server

Serves:
- /api/datasets           -> list datasets with basic metadata and aggregated flags
- /api/datasets/<id>      -> full combined JSON
- /api/datasets/<id>/preview -> first 15 rows of the CSV as JSON records
- /api/flags              -> known flags and counts across datasets

Static UI under / (explorer.html, explorer.js, explorer.css)

Config (env vars):
- COMBINED_DIR: Directory of combined JSONs (defaults to first existing among:
        - data/profiling/combined/ (repo-level)
        - ../data/profiling/combined/ (project-level)
    )
- DEBUG: '1' to enable verbose logging
"""

from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

from flask import Flask, jsonify, send_from_directory, request, abort

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRS = [
    REPO_ROOT / 'data' / 'profiling' / 'combined',           # ./data/profiling/combined
    REPO_ROOT.parent / 'data' / 'profiling' / 'combined',    # ../data/profiling/combined
]


def resolve_combined_dir() -> Path:
    env = os.getenv('COMBINED_DIR')
    if env:
        p = Path(env).expanduser().resolve()
        if p.exists():
            return p
    for p in DEFAULT_DIRS:
        if p.exists():
            return p
    # Fallback: create repo-level path
    fallback = DEFAULT_DIRS[1]
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


COMBINED_DIR = resolve_combined_dir()
DEBUG = os.getenv('DEBUG', '0') == '1'

app = Flask(__name__, static_folder='.', static_url_path='')
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)
logger = logging.getLogger("explorer")


def _load_dataset(path: Path) -> Dict[str, Any]:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def _index_datasets() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for p in sorted(COMBINED_DIR.glob('*.json')):
        try:
            data = _load_dataset(p)
            ds_id = p.stem
            source_csv = data.get('source_csv')
            file_checks = data.get('file_checks', {})
            vsummary = file_checks.get('validation_summary', {})

            # Aggregate flags across columns
            flags = set()
            for col in data.get('columns', []):
                for fl in col.get('validation_flags', []) or []:
                    flags.add(fl)

            items.append({
                'id': ds_id,
                'name': os.path.basename(source_csv) if source_csv else ds_id,
                'source_csv': source_csv,
                'um_label': file_checks.get('um_label'),
                'validation_summary': vsummary,
                'flags': sorted(flags),
                'columns_count': len(data.get('columns', [])),
            })
        except Exception as e:
            logger.warning("Failed to load %s: %s", p.name, e)
    return items


def _collect_flag_counts(items: List[Dict[str, Any]]) -> Dict[str, int]:
    from collections import Counter
    c = Counter()
    for it in items:
        for fl in it.get('flags', []):
            c[fl] += 1
    return dict(sorted(c.items()))


@app.route('/')
def root():
    return send_from_directory(app.static_folder, 'explorer.html')


@app.route('/explorer.js')
def js():
    return send_from_directory(app.static_folder, 'explorer.js')


@app.route('/explorer.css')
def css():
    return send_from_directory(app.static_folder, 'explorer.css')


@app.route('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'combined_dir': str(COMBINED_DIR),
        'count': len(list(COMBINED_DIR.glob('*.json')))
    })


@app.route('/api/datasets')
def list_datasets():
    # Query params
    q = (request.args.get('q') or '').strip().lower()
    flags = [f for f in (request.args.get('flags') or '').split(',') if f]
    limit = int(request.args.get('limit') or 50)
    offset = int(request.args.get('offset') or 0)

    idx = _index_datasets()

    def matches(it: Dict[str, Any]) -> bool:
        if q:
            hay = ' '.join([
                it.get('id', ''),
                it.get('name', ''),
                it.get('um_label', '') or ''
            ]).lower()
            if q not in hay:
                return False
        if flags:
            have = set(it.get('flags', []))
            for f in flags:
                if f not in have:
                    return False
        return True

    filtered = [it for it in idx if matches(it)]
    total = len(filtered)
    page = filtered[offset:offset+limit]

    return jsonify({
        'total': total,
        'limit': limit,
        'offset': offset,
        'items': page
    })


@app.route('/api/flags')
def list_flags():
    idx = _index_datasets()
    return jsonify({
        'counts': _collect_flag_counts(idx)
    })


@app.route('/api/datasets/<ds_id>')
def dataset_detail(ds_id: str):
    path = COMBINED_DIR / f'{ds_id}.json'
    if not path.exists():
        abort(404, description='Dataset not found')
    data = _load_dataset(path)
    return jsonify(data)


@app.route('/api/datasets/<ds_id>/preview')
def dataset_preview(ds_id: str):
    path = COMBINED_DIR / f'{ds_id}.json'
    if not path.exists():
        abort(404, description='Dataset not found')
    data = _load_dataset(path)
    source_csv = data.get('source_csv')
    if not source_csv or not os.path.exists(source_csv):
        abort(404, description='Source CSV not reachable')
    try:
        df = pd.read_csv(source_csv, nrows=15)
        rows = df.to_dict(orient='records')
        return jsonify({'rows': rows, 'columns': list(df.columns)})
    except Exception as e:
        abort(500, description=f'Failed to read CSV preview: {e}')


def main():
    logger.info("Using combined dir: %s", COMBINED_DIR)
    app.run(host='127.0.0.1', port=5050, debug=DEBUG)


if __name__ == '__main__':
    main()
