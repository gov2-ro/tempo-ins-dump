"""Deterministic post-check of an Ask answer against its tool results (FIX-08 item 7).

Pure functions, no model calls and nothing in the prompt: the agent loop hands
over the final text and the tool trace, and gets back what can be verified.

* ``valid_queries`` — `tempo-tools/1` results of the data tools (query_data,
  compare_periods, run_recipe) that returned values (status ok / partial).
* ``find_numbers`` / ``uncited_numbers`` — numeric claims in the answer that no
  valid result contains (within rounding/scale tolerance; a sign is not compared,
  so "fell by 50" matches a change of -50).
* ``bind_claims`` — each numeric claim tied, by the server, to the JSON Pointer of
  the result cell it matches, with that cell's entity, period and unit. A number
  that merely occurs somewhere is not semantic verification: when the cell belongs
  to a named entity the claim's sentence must name that entity, otherwise the
  claim stays ``unverified`` and the answer is not called verified because of it.
* ``approximation_notes`` — deterministic wording that keeps an unweighted mean
  from being presented as an official statistic.
"""
from __future__ import annotations

import re
import unicodedata

DATA_TOOLS = ('query_data', 'compare_periods', 'run_recipe')
MAX_CLAIMS = 20

# number token: 1.234.567,8 | 1,234,567.8 | 12 345 | 3,5 | 42
_NUM_RE = re.compile(
    r'(?<![\w.,/-])(\d{1,3}(?:[.,  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)'
    r'(?![\w])\s*(%|procente?|percent|milioane|milion|million|miliarde|miliard|billion|'
    r'mii\b|thousand|mld\.?|mil\.?)?', re.I)
_SCALE = {'milioane': 1e6, 'milion': 1e6, 'million': 1e6, 'mil': 1e6, 'mil.': 1e6,
          'miliarde': 1e9, 'miliard': 1e9, 'billion': 1e9, 'mld': 1e9, 'mld.': 1e9,
          'mii': 1e3, 'thousand': 1e3}
_APPROX_WORDS = re.compile(r'aproxim|approximat|neponderat|unweighted|estimat', re.I)

_RO_HINTS = {'ce', 'cat', 'cate', 'cati', 'care', 'în', 'in', 'este', 'sunt', 'pe', 'din',
             'populatia', 'populația', 'rata', 'județe', 'judete', 'anul', 'cum', 'unde'}
_EN_HINTS = {'what', 'how', 'many', 'much', 'the', 'is', 'are', 'of', 'in', 'by', 'for',
             'population', 'rate', 'which', 'where'}


def guess_lang(text: str) -> str:
    toks = re.findall(r"[a-zăâîșțşţ]+", (text or '').lower())
    if re.search(r'[ăâîșțşţ]', text or ''):
        return 'ro'
    ro = sum(t in _RO_HINTS for t in toks)
    en = sum(t in _EN_HINTS for t in toks)
    return 'ro' if ro > en else 'en'


def _is_envelope(r) -> bool:
    return isinstance(r, dict) and r.get('contract') == 'tempo-tools/1'


def valid_queries(tool_trace: list[dict]) -> list[dict]:
    """Outputs of the data tools that returned usable values."""
    out = []
    for t in tool_trace:
        o = t.get('output')
        if (t.get('tool') in DATA_TOOLS and _is_envelope(o)
                and o.get('status') in ('ok', 'partial') and numeric_leaves(o, t.get('id'))):
            out.append(o)
    return out


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _aliases(data: dict) -> dict:
    """value -> label for the columns whose labels differ from their values."""
    out = {}
    for col, m in (data.get('column_labels') or {}).items():
        if isinstance(m, dict):
            out.setdefault(col, {}).update({str(k): str(v) for k, v in m.items()})
    return out


def numeric_leaves(env: dict, call_id: str | None = None) -> list[dict]:
    """Every measure value of a data-tool result with where it is and what it describes:
    [{path, value, entity: [labels], period, unit}]. Only value cells count (a rank, a row
    count or a dimension code is not a statistic the answer may quote)."""
    tool, data = env.get('tool'), env.get('data') or {}
    srcs = (env.get('provenance') or {}).get('sources') or []
    unit = data.get('unit') or (srcs[0].get('unit') if srcs else None)
    leaves = []
    if tool == 'query_data':
        cols, labels = data.get('columns') or [], _aliases(data)
        vi = cols.index('OBS_VALUE') if 'OBS_VALUE' in cols else None
        ti = cols.index('TIME_PERIOD') if 'TIME_PERIOD' in cols else None
        for i, row in enumerate(data.get('rows') or []):
            for j, cell in enumerate(row):
                if not _num(cell) or (vi is not None and j != vi):
                    continue
                ent = []
                for k, c in enumerate(cols):
                    if k in (j, ti) or _num(row[k]):
                        continue
                    ent += [str(row[k])] + ([labels[c][str(row[k])]] if str(row[k]) in labels.get(c, {}) else [])
                leaves.append({'path': f'/data/rows/{i}/{j}', 'value': float(cell), 'entity': ent,
                               'period': str(row[ti]) if ti is not None else None, 'unit': unit})
    elif tool == 'compare_periods':
        for k, iv in enumerate(data.get('intervals') or []):
            period = f"{iv.get('from')}→{iv.get('to')}"
            for m, row in enumerate(iv.get('rows') or []):
                ent = [str(v) for v in (row.get('entity') or {}).values()]
                for f in ('from_value', 'to_value', 'absolute', 'percent'):
                    if _num(row.get(f)):
                        leaves.append({'path': f'/data/intervals/{k}/rows/{m}/{f}',
                                       'value': float(row[f]), 'entity': ent, 'period': period,
                                       'unit': '%' if f == 'percent' else unit})
    elif tool == 'run_recipe':
        for m, row in enumerate(data.get('rows') or []):
            if _num(row.get('value')):
                leaves.append({'path': f'/data/rows/{m}/value', 'value': float(row['value']),
                               'entity': [str(row.get('label') or row.get('area') or '')],
                               'period': str(data.get('year')) if data.get('year') else None,
                               'unit': row.get('unit') or unit})
    return leaves


def result_values(results: list[dict]) -> list[float]:
    vals = []
    for r in results:
        if _is_envelope(r):
            vals += [lf['value'] for lf in numeric_leaves(r)]
            continue
        for row in r.get('rows') or []:       # a bare {rows: [[...]]} table
            for c in row:
                if _num(c):
                    vals.append(float(c))
    return vals


def _interpretations(tok: str) -> list[tuple[float, int]]:
    """(value, printed decimals) readings of a number token (RO and EN styles)."""
    t = tok.replace(' ', ' ')
    seps = re.findall(r'[.,\s]', t)
    reads: list[tuple[float, int]] = []

    def add(s, dec):
        try:
            reads.append((float(s), dec))
        except ValueError:
            pass

    if not seps:
        add(t, 0)
        return reads
    last_sep = max(t.rfind('.'), t.rfind(','), t.rfind(' '))
    tail = t[last_sep + 1:]
    head = re.sub(r'[.,\s]', '', t[:last_sep])
    if len(seps) > 1 and len(set(seps)) == 1 and tail.isdigit() and len(tail) == 3:
        add(head + tail, 0)            # 1.234.567 — pure thousands
    elif len(tail) == 3 and tail.isdigit():
        add(head + tail, 0)            # 1.234 as thousands
        if t[last_sep] in '.,':
            add(f'{head}.{tail}', 3)   # ... or a decimal with 3 digits
    else:
        add(f'{head}.{tail}', len(tail))
    return reads


def find_numbers(text: str, ignore_text: str = '') -> list[dict]:
    """Numeric claims worth verifying: [{raw, readings, scale, percent}].

    Skipped: years, plain small integers (list numbers, counts of regions...),
    anything glued to letters (matrix codes) and numbers the question itself
    contained.
    """
    asked = {m.group(1) for m in _NUM_RE.finditer(ignore_text or '')}
    out = []
    for m in _NUM_RE.finditer(text or ''):
        raw, suffix = m.group(1), (m.group(2) or '').lower().strip()
        if raw in asked:
            continue
        pct = suffix in ('%', 'procent', 'procente', 'percent')
        scale = 1.0 if pct else _SCALE.get(suffix, 1.0)
        plain_int = bool(re.fullmatch(r'\d+', raw))
        if plain_int and not suffix:
            n = int(raw)
            if n <= 31 or (1900 <= n <= 2100 and len(raw) == 4):
                continue
        if plain_int and pct is False and scale == 1.0 and len(raw) == 4 \
                and 1900 <= int(raw) <= 2100:
            continue
        reads = _interpretations(raw)
        if reads:
            out.append({'raw': (raw + (' ' + suffix if suffix else '')).strip(),
                        'readings': reads, 'scale': scale, 'percent': pct})
    return out


def _matches_value(claim: dict, v: float) -> bool:
    for val, dec in claim['readings']:
        c = val * claim['scale']
        half_ulp = 0.5 * (10 ** -dec) * claim['scale']
        tol = max(half_ulp, 0.005 * abs(v))
        if abs(abs(c) - abs(v)) <= tol:       # "fell by 50" is a claim about a change of -50
            return True
    return False


def _matches(claim: dict, values: list[float]) -> bool:
    return any(_matches_value(claim, v) for v in values)


def uncited_numbers(answer: str, results: list[dict], question: str = '') -> list[str]:
    """Numbers in `answer` that no valid query result contains."""
    values = result_values(results)
    return [c['raw'] for c in find_numbers(answer, question)
            if not _matches(c, values)]


def has_value_claims(answer: str, question: str = '') -> bool:
    return bool(find_numbers(answer, question))


NOTICES = {
    'ro': {
        'withheld': ('Nu am putut obține valori dintr-o interogare validă a datelor INS, '
                     'așa că nu pot indica cifre. Reformulați întrebarea sau precizați '
                     'setul de date și filtrele (de ex. un singur nivel de vârstă sau '
                     'zonă geografică).'),
        'approx': ('Notă: valoarea pentru {code} este o medie neponderată (aproximare), '
                   'nu o rată sau o statistică oficială INS.'),
    },
    'en': {
        'withheld': ('I could not obtain values from a valid query of the INS data, so I '
                     'cannot state figures. Please rephrase or name the dataset and '
                     'filters (e.g. a single age level or geographic level).'),
        'approx': ('Note: the value for {code} is an unweighted mean (an approximation), '
                   'not an official INS rate or statistic.'),
    },
}


def approximation_notes(answer: str, tool_trace: list[dict], lang: str) -> list[str]:
    """Deterministic notes for approximate query results the answer did not
    already qualify."""
    if _APPROX_WORDS.search(answer or ''):
        return []
    codes = []
    for t in tool_trace:
        o = t.get('output')
        if (t.get('tool') == 'query_data' and _is_envelope(o)
                and (o.get('provenance') or {}).get('aggregation', {}).get('approximation')):
            code = ((o['provenance'].get('selection') or {}).get('dataset')) or ''
            if code not in codes:
                codes.append(code)
    tmpl = NOTICES.get(lang, NOTICES['en'])['approx']
    return [tmpl.format(code=c) for c in codes]


# ---------------------------------------------------------------- claim binding

def _norm(text: str) -> str:
    t = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().casefold()
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', t)).strip()


def _sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?;])\s+|\n+', text or '')
    return [p.strip() for p in parts if p and p.strip()]


def _entity_named(sentence: str, sentence_norm: str, entity: list[str]) -> bool:
    """Does the sentence name one of the cell's entities? A name of two or more characters
    matches accent- and case-insensitively; a one-letter name (a code) must stand alone, with
    the same case, so the Romanian word "a" is not mistaken for entity A."""
    names = [e for e in entity if e and not _num_like(e)]
    for e in names:
        n = _norm(e)
        if len(n) >= 2 and n in sentence_norm:
            return True
        if len(e.strip()) == 1 and re.search(rf'(?<![\w]){re.escape(e.strip())}(?![\w])', sentence):
            return True
    return False


def _num_like(s: str) -> bool:
    return bool(re.fullmatch(r'[\d.,\s-]+', s or ''))


def bind_claims(answer: str, question: str, tool_trace: list[dict]) -> list[dict]:
    """Bind each numeric claim of `answer` to a result cell, deterministically.

    Returns up to MAX_CLAIMS entries {text, tool_call_id, path, entity, period, unit, check}.
    ``check`` is ``matched`` only when a cell holds the number AND (the cell has no named
    entity, or the sentence names it); otherwise ``unverified`` with no references. Nothing the
    model wrote about its own sources is used."""
    leaves = []
    for t in tool_trace:
        o = t.get('output')
        if t.get('tool') in DATA_TOOLS and _is_envelope(o) and o.get('status') in ('ok', 'partial'):
            for lf in numeric_leaves(o, t.get('id')):
                leaves.append({**lf, 'call': t.get('id')})
    claims = []
    for sent in _sentences(answer):
        found = find_numbers(sent, question)
        if not found:
            continue
        snorm = _norm(sent)
        for c in found:
            cands = [lf for lf in leaves if _matches_value(c, lf['value'])]
            pick = next((lf for lf in cands
                         if not lf['entity'] or _entity_named(sent, snorm, lf['entity'])), None)
            entry = {'text': sent[:200], 'tool_call_id': None, 'path': None, 'entity': None,
                     'period': None, 'unit': None, 'check': 'unverified'}
            if pick:
                entry.update(tool_call_id=pick['call'], path=pick['path'],
                             entity=' · '.join(dict.fromkeys(pick['entity'])) or None,
                             period=pick['period'], unit=pick['unit'], check='matched')
            claims.append(entry)
            if len(claims) >= MAX_CLAIMS:
                return claims
    return claims
