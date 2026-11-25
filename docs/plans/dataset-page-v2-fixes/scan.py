#!/usr/bin/env python
"""DP-01 Part 1 Step 1: read-only scan for "... total ..." options.

Lists every option, in every canonical dataset dimension, whose label contains the
word `total` (\\btotal\\b, case-insensitive; `totale` does not match) anywhere but at
the start, and that TOTAL_RE / TOTAL_SUFFIX_RE do not already match. For each one,
checks whether its value is >= every other option's value in every cell (period x
slice of the other dimensions). Writes scan.json and scan.md next to this file.

Read-only: DuckDB opened read_only, parquet files resolved by code
(duckdb_config.corpus_parquet logic: <corpus>/parquet/<code>.parquet).

Usage: python scan.py [--corpus /path/to/data/corpus]
"""
import argparse
import json
import re
from pathlib import Path

import duckdb

# Same patterns as app/services/chart_selector.py:17 and aggregation_policy.py:104.
TOTAL_RE = re.compile(
    r'^(total|toate|ambele sexe|ambele|urban\s*\+\s*rural|m\s*\+\s*f)\b', re.I)
TOTAL_SUFFIX_RE = re.compile(r'-\s*total\s*$', re.I)
WORD_RE = re.compile(r'\btotal\b', re.I)

HERE = Path(__file__).resolve().parent
NON_DIM = {'OBS_VALUE', 'TIME_PERIOD'}


def q(name):
    return '"' + name.replace('"', '""') + '"'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', default='/Users/pax/devbox/gov2/tempo-ins-dump/data/corpus')
    args = ap.parse_args()
    corpus = Path(args.corpus)
    con = duckdb.connect(str(corpus / 'metadata.duckdb'), read_only=True)
    mats = con.execute(
        "select matrix_code, matrix_name from matrices where is_canonical").fetchall()

    cands, skipped, scanned = [], [], 0
    for code, name in mats:
        pq = corpus / 'parquet' / f'{code}.parquet'
        if not pq.exists():
            skipped.append((code, 'no parquet'))
            continue
        path = str(pq).replace("'", "''")
        cols = [r[0] for r in con.execute(f"describe select * from read_parquet('{path}')").fetchall()]
        if 'OBS_VALUE' not in cols or 'TIME_PERIOD' not in cols:
            skipped.append((code, 'legacy shape'))
            continue
        scanned += 1
        dims = [c for c in cols if c not in NON_DIM]
        for col in dims:
            vals = [r[0] for r in con.execute(
                f"select distinct {q(col)} from read_parquet('{path}')").fetchall() if r[0] is not None]
            found = [v for v in vals if WORD_RE.search(str(v))
                     and not TOTAL_RE.match(str(v).strip())
                     and not TOTAL_SUFFIX_RE.search(str(v))]
            if not found:
                continue
            others = [c for c in cols if c not in (col, 'OBS_VALUE')]
            keys = ', '.join(q(c) for c in others)
            unit_col = 'UNIT_MEASURE' if 'UNIT_MEASURE' in cols and col != 'UNIT_MEASURE' else None
            for v in found:
                lit = str(v).replace("'", "''")
                r = con.execute(f"""
                    with cells as (
                      select {keys},
                             max(case when {q(col)} = '{lit}' then "OBS_VALUE" end) as cv,
                             max(case when {q(col)} <> '{lit}' then "OBS_VALUE" end) as om
                      from read_parquet('{path}') group by {keys})
                    select count(*) filter (where cv is not null and om is not null),
                           count(*) filter (where cv is not null and om is not null and om > cv),
                           count(*) filter (where cv is null and om is not null),
                           (select count(*) from read_parquet('{path}')
                              where {q(col)} = '{lit}' and "OBS_VALUE" < 0)
                    from cells""").fetchone()
                units = []
                if unit_col:
                    units = [u[0] for u in con.execute(
                        f"select distinct {q(unit_col)} from read_parquet('{path}') "
                        f"where {q(col)} = '{lit}' limit 3").fetchall()]
                comparable, fails, missing, neg = r
                cands.append({
                    'code': code, 'column': col, 'label': str(v).strip(),
                    'unit': '; '.join(str(u) for u in units if u) or None,
                    'n_options': len(vals), 'n_candidates_in_dim': len(found),
                    'cells_compared': comparable, 'cells_fail': fails,
                    'cells_total_missing': missing, 'negative_values': neg,
                    'dominates': comparable > 0 and fails == 0,
                    'matrix_name': name,
                })
    cands.sort(key=lambda c: (not c['dominates'], c['n_candidates_in_dim'], c['code']))
    out = {'canonical_matrices': len(mats), 'scanned': scanned, 'skipped': skipped,
           'candidates': cands}
    (HERE / 'scan.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')

    dom = [c for c in cands if c['dominates']]
    sole = [c for c in dom if c['n_candidates_in_dim'] == 1]
    md = [f"# DP-01 scan: options with `total` inside the label\n",
          f"Canonical datasets: {len(mats)}; scanned: {scanned}; skipped: {len(skipped)} "
          f"({', '.join(sorted({s[1] for s in skipped}))}).\n",
          f"- Candidates: {len(cands)}",
          f"- Dominate in every compared cell: {len(dom)}",
          f"- Dominate and are the only candidate in the dimension (Step 2 rule): {len(sole)}",
          f"- Dominate with a missing total in some cell (other options have data): "
          f"{sum(1 for c in dom if c['cells_total_missing'])}\n",
          "| code | column | label | unit | opts | cand | cells | fail | total missing | dominates |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for c in cands:
        md.append(f"| {c['code']} | {c['column']} | {c['label']} | {c['unit'] or ''} | {c['n_options']} | "
                  f"{c['n_candidates_in_dim']} | {c['cells_compared']} | {c['cells_fail']} | "
                  f"{c['cells_total_missing']} | {'yes' if c['dominates'] else 'no'} |")
    (HERE / 'scan.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(len(cands), 'candidates;', len(dom), 'dominate;', len(sole), 'sole+dominate; skipped', len(skipped))


if __name__ == '__main__':
    main()
