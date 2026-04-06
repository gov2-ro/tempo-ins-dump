#!/usr/bin/env python3
"""
Build lightweight keyword and category indexes from available local datasets.
- Scans data/indexes/matrices.csv to discover dataset IDs (restrict to those with both CSV and metas available locally)
- Extracts keywords using simple heuristics from metas and meta-detected files
- Emits JSON files under data/indexes/: keywords.json and themes.json

Run:
  python3 tools/build_indexes.py
"""
from __future__ import annotations
import csv
import json
import os
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ROOT, 'data')

MATRICES = os.path.join(DATA, 'indexes', 'matrices.csv')
CONTEXT = os.path.join(DATA, 'indexes', 'context.json')
METAS = os.path.join(DATA, 'metas')
DETECTED = os.path.join(DATA, 'meta-detected')
DATASETS = os.path.join(DATA, 'datasets')
OUT_DIR = os.path.join(DATA, 'indexes')

STOP = set(map(str.lower, [
    'the','and','or','for','of','in','to','a','an','on','by','with','from','as','at','is','are','be','per',
    'la','si','sau','din','ale','al','un','o','cu','de','pe','in','anul','ani','rata','numar','numărul','nr','total','medie'
]))


def split_words(text: str) -> list[str]:
    return [t for t in ''.join(c if c.isalnum() or c.isspace() else ' ' for c in (text or '')).split() if t]


def get_context_map() -> dict:
    with open(CONTEXT, 'r', encoding='utf-8') as f:
        items = json.load(f)
    m = {}
    for it in items:
        ctx = it.get('context') or {}
        code = ctx.get('code')
        if not code:
            continue
        m[code] = {
            'code': code,
            'name': ctx.get('name'),
            'parentCode': it.get('parentCode'),
        }
    return m


def get_root_code(context_map: dict, code: str) -> str | None:
    cur = context_map.get(code)
    last = cur
    while cur and cur.get('parentCode') and cur.get('parentCode') != '0':
        next_code = cur['parentCode']
        last = context_map.get(next_code, last)
        cur = context_map.get(next_code)
    return (last or {}).get('code') or code


def derive_keywords(meta: dict, detected: dict | None, title: str) -> list[str]:
    words = []
    if title:
        words += split_words(title)
    if meta:
        if meta.get('matrixName'):
            words += split_words(meta['matrixName'])
        if meta.get('definitie'):
            words += split_words(meta['definitie'][:200])
        for d in meta.get('periodicitati', []) or []:
            words += split_words(d)
        for d in meta.get('dimensionsMap', []) or []:
            if d.get('label'):
                words += split_words(d['label'])
        for s in meta.get('surseDeDate', []) or []:
            if s.get('nume'):
                words += split_words(s['nume'])
    if detected:
        fc = detected.get('file_checks') or {}
        for k in ('um_label', 'um_value', 'um_classification'):
            if fc.get(k):
                words += split_words(fc[k])
        for col in detected.get('columns') or []:
            for k in ('column_name','guessed_type','semantic_categories','functional_types'):
                if col.get(k):
                    words += split_words(col[k])
    uniq = []
    seen = set()
    for w in (t.lower() for t in words):
        if len(w) <= 2 or w in STOP:
            continue
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return uniq


def main():
    # read matrices index
    with open(MATRICES, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    context_map = get_context_map()

    keywords_counter = Counter()
    theme_counts = defaultdict(int)
    dataset_keywords = {}

    for row in rows:
        fid = (row.get('filename') or '').strip()
        if not fid:
            continue
        meta_path = os.path.join(METAS, f'{fid}.json')
        csv_path = os.path.join(DATASETS, f'{fid}.csv')
        if not (os.path.exists(meta_path) and os.path.exists(csv_path)):
            continue
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        det = None
        det_path = os.path.join(DETECTED, f'{fid}.json')
        if os.path.exists(det_path):
            try:
                with open(det_path, 'r', encoding='utf-8') as f:
                    det = json.load(f)
            except Exception:
                det = None
        title = row.get('matrixName') or ''
        kws = derive_keywords(meta, det, title)
        dataset_keywords[fid] = kws
        keywords_counter.update(kws)

        root = get_root_code(context_map, row.get('context-code'))
        if root:
            theme_counts[root] += 1

    # Write indexes
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, 'keywords.json'), 'w', encoding='utf-8') as f:
        json.dump({ 'keywords': keywords_counter.most_common(), 'datasets': dataset_keywords }, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, 'themes.json'), 'w', encoding='utf-8') as f:
        json.dump(theme_counts, f, ensure_ascii=False, indent=2)

    print(f'Wrote {len(dataset_keywords)} datasets to indexes; {len(keywords_counter)} unique keywords.')


if __name__ == '__main__':
    main()
