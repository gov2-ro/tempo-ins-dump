"""Deterministic post-check of an Ask answer against its tool results (FIX-08 item 7).

Pure functions, no model calls and nothing in the prompt: the agent loop hands
over the final text and the tool trace, and gets back what can be verified.

* ``valid_queries`` — query_dataset_data results that actually returned rows
  under an available aggregation outcome (ok / approximation).
* ``find_numbers`` / ``uncited_numbers`` — numeric claims in the answer that no
  valid query result contains (within rounding/scale tolerance).
* ``approximation_notes`` — deterministic wording that keeps an unweighted mean
  from being presented as an official statistic.
"""
from __future__ import annotations

import re

QUERY_TOOL = 'query_dataset_data'

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


def valid_queries(tool_trace: list[dict]) -> list[dict]:
    out = []
    for t in tool_trace:
        o = t.get('output')
        if (t.get('tool') == QUERY_TOOL and isinstance(o, dict)
                and o.get('status') in ('ok', 'approximation')
                and o.get('rows')):
            out.append(o)
    return out


def result_values(results: list[dict]) -> list[float]:
    vals = []
    for r in results:
        for row in r.get('rows') or []:
            for c in row:
                if isinstance(c, (int, float)) and not isinstance(c, bool):
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


def _matches(claim: dict, values: list[float]) -> bool:
    for val, dec in claim['readings']:
        c = val * claim['scale']
        half_ulp = 0.5 * (10 ** -dec) * claim['scale']
        for v in values:
            tol = max(half_ulp, 0.005 * abs(v))
            if abs(c - v) <= tol:
                return True
    return False


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
        if (t.get('tool') == QUERY_TOOL and isinstance(o, dict)
                and o.get('status') == 'approximation'):
            code = o.get('matrix_code') or ''
            if code not in codes:
                codes.append(code)
    tmpl = NOTICES.get(lang, NOTICES['en'])['approx']
    return [tmpl.format(code=c) for c in codes]
