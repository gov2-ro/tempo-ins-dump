"""Deterministic post-check of an Ask answer against its tool results (FIX-08 item 7).

Pure functions, no model calls and nothing in the prompt: the agent loop hands
over the final text and the tool trace, and gets back what can be verified.

* ``valid_queries`` — `tempo-tools/2` results of the data tools (query_data,
  compare_periods, run_recipe) that returned values (status ok / partial).
* ``numeric_leaves`` — every measure value of a result with its evidence coordinates:
  JSON Pointer, full entity key, period (a change keeps both endpoints), metric
  (observation / from_value / to_value / change_absolute / change_percent) and the unit
  normalized into measure, currency, scale and denominator. Units and the population
  definition come from reviewed source metadata, recipes and concepts, never from the
  model's own words.
* ``find_numbers`` / ``uncited_numbers`` — numeric claims in the answer that no valid
  result contains (within rounding/scale tolerance; a sign is not compared, so "fell by
  50" matches a change of -50).
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

DATA_TOOLS = ('rank_entities', 'query_data', 'compare_periods', 'run_recipe')
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
    return isinstance(r, dict) and r.get('contract') == 'tempo-tools/2'


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


# ------------------------------------------------------------ units and definitions

_UNKNOWN_UNIT = {'measure': None, 'currency': None, 'scale': None, 'denominator': None, 'known': False}
_SCALE_WORD = {'mii': 1e3, 'thousand': 1e3, 'milioane': 1e6, 'milion': 1e6, 'million': 1e6,
               'miliarde': 1e9, 'miliard': 1e9, 'billion': 1e9}
# Source unit texts INS and the reviewed recipes use, as a full match on the folded text (after an
# optional scale word). Anything else stays unknown: no guessing from fragments ("Mii tone", "Ore").
_UNIT_BASES = tuple((re.compile(p), m, c) for p, m, c in (
    (r'(?:numar )?(?:persoane|persons|people|locuitori|inhabitants)', 'persons', None),
    (r'numar|number', 'count', None),
    (r'(?:numar )?(?:innoptari|overnight stays|nights)', 'stays', None),
    (r'(?:lei|ron)(?: (?:lei|ron))?', 'currency', 'RON'),
    (r'euro|eur', 'currency', 'EUR'),
    (r'dolari(?: \(usd\))?|usd', 'currency', 'USD'),
    (r'puncte procentuale|percentage points?', 'percentage_points', None),
    (r'procente?|percent(?:age)?|%', 'percent', None),
    (r'hectare|hectares|ha', 'area_ha', None),
    (r'kilometri patrati|km2|square kilomet(?:re|er)s?', 'area_km2', None)))
_UNIT_PER = re.compile(r'(?P<num>.+?) ?(?:/| pe | per | la (?:un )?) ?(?:(?P<one>locuitor|persoana|rezident|resident|'
                       r'inhabitant|person|capita)|(?P<k>(?:1000|1 000|mia de|mie de) (?:de )?'
                       r'(?:locuitori|inhabitants|persoane|people)))')
_TYPE_UNIT = {'percentage': 'percent', 'count': 'count'}     # profile unit_type, a hint when no unit text


def _fold(text) -> str:
    t = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().casefold()
    return re.sub(r'\s+', ' ', t).strip()


def normalize_unit(text=None, unit_type=None) -> dict:
    """A source unit as {measure, currency, scale, denominator, known}. `measure` is persons, count,
    stays, currency, percent, percentage_points, area_ha or area_km2; `scale` multiplies a stored
    value into base units (Mii persoane: 1000); `denominator` is person or thousand_persons. Percentage
    points are not percent and hectares are not square kilometres; no conversion between them.
    Unknown text stays unknown (known False, every field None)."""
    t = _fold(text)
    if not t:
        measure = _TYPE_UNIT.get(unit_type)
        return {'measure': measure, 'currency': None, 'scale': 1.0, 'denominator': None,
                'known': True} if measure else dict(_UNKNOWN_UNIT)
    den = None
    m = _UNIT_PER.fullmatch(t)
    if m:
        t, den = m['num'].strip(), 'thousand_persons' if m['k'] else 'person'
    scale = 1.0
    sm = re.fullmatch(r'(mii|milioane|miliarde|thousand|million|billion) (.+)', t)
    if sm:
        scale, t = _SCALE_WORD[sm[1]], sm[2]
    for rx, measure, currency in _UNIT_BASES:
        if rx.fullmatch(t):
            return {'measure': measure, 'currency': currency, 'scale': scale, 'denominator': den,
                    'known': True}
    if den:        # a rate whose numerator is not classified: the denominator is still stated
        return {'measure': None, 'currency': None, 'scale': None, 'denominator': den, 'known': True}
    return dict(_UNKNOWN_UNIT)


def _change_unit(base: dict, metric: str) -> dict:
    """The unit of a change: a relative change is percent; an absolute change of a percent series is
    percentage points; otherwise the source unit."""
    if metric == 'change_percent':
        return {'measure': 'percent', 'currency': None, 'scale': 1.0, 'denominator': None, 'known': True}
    if metric == 'change_absolute' and base['measure'] == 'percent':
        return {**base, 'measure': 'percentage_points'}
    return base


# Population definitions are carried only where a reviewed mapping establishes them: the
# concepts' dataset families (concepts.json), a recipe source's reviewed concept, or the locality
# series the AT-05 city ranking selects as domicile population. A title or definition text that
# happens to contain "domicile" or "resident" classifies nothing.
_CONCEPT_POPULATION = {'resident_population': 'resident', 'resident_population_july': 'resident',
                       'domicile_population': 'domicile'}
_SERIES_POPULATION = {'POP107D': 'domicile'}


def _family_population() -> dict:
    from app.services import concept_search
    out = dict(_SERIES_POPULATION)
    try:
        for c in concept_search.load_concepts():
            d = _CONCEPT_POPULATION.get(c.get('id'))
            if d and c.get('family'):
                out[c['family']] = d
    except (OSError, ValueError, KeyError):
        pass
    return out


def _population_of(env: dict, dataset) -> str | None:
    """'resident' | 'domicile' | None for the statistic a result reports."""
    srcs = (env.get('provenance') or {}).get('sources') or []
    families = _family_population()
    found = set()
    if env.get('tool') == 'run_recipe':
        for s in srcs:
            d = _CONCEPT_POPULATION.get(s.get('concept')) or families.get(str(s.get('dataset') or '').split('_')[0])
            if d:
                found.add(d)
    elif dataset:
        d = families.get(str(dataset).split('_')[0])
        if d:
            found.add(d)
    return next(iter(found)) if len(found) == 1 else None


def _pinned_unit(env: dict) -> str | None:
    prov = env.get('provenance') or {}
    for sel in (prov.get('effective_selection'), prov.get('selection')):
        v = ((sel or {}).get('filters') or {}).get('UNIT_MEASURE') or []
        if len(v) == 1:
            return str(v[0])
    return None


def _key_names(key: dict) -> list[str]:
    """The names a sentence can use for an entity key: its finest geographic value, else every
    value. Independent of the dictionary's insertion order."""
    for col in ('REF_AREA_2', 'REF_AREA'):
        if col in key:
            return [key[col]]
    return [key[c] for c in sorted(key)]


def numeric_leaves(env: dict, call_id: str | None = None) -> list[dict]:
    """Every measure value of a data-tool result with where it is and what it describes:
    [{path, call, value, entity: [labels], period, unit, metric, period_from, period_to, key,
    unit_norm, scaled, population, dataset, tool}]. Only value cells count (a rank, a row count, a SIRUTA code
    or a dimension code is not a statistic the answer may quote).

    `metric` says what the number is: observation, from_value / to_value (the value at that single
    endpoint year), change_absolute / change_percent (spanning period_from..period_to). `key` is the
    full entity key as {column: value}; `unit_norm` the normalized source unit; `scaled` the value in
    base units when the source unit has a scale (Mii persoane); `population` the reviewed definition."""
    tool, data = env.get('tool'), env.get('data') or {}
    prov = env.get('provenance') or {}
    srcs = prov.get('sources') or []
    src0 = srcs[0] if srcs else {}
    u_text = (data.get('unit') or (data.get('recipe') or {}).get('unit') or src0.get('unit')
              or _pinned_unit(env))
    u_type = src0.get('unit_type')
    dataset = (prov.get('selection') or {}).get('dataset') or data.get('dataset') \
        or (data.get('recipe') or {}).get('id')
    population = _population_of(env, dataset)

    def leaf(path, value, entity, key, period, *, metric='observation', start=None, end=None,
             text=u_text, label=None):
        norm = _change_unit(normalize_unit(text, u_type), metric)
        v = float(value)
        return {'path': path, 'call': call_id, 'value': v, 'entity': entity, 'period': period,
                'unit': label if label is not None else (text or u_type), 'tool': tool,
                'dataset': dataset, 'metric': metric, 'key': dict(sorted(key.items())),
                'period_from': period if start is None else start,
                'period_to': period if end is None else end, 'unit_norm': norm,
                'scaled': v * norm['scale'] if norm['scale'] not in (None, 1.0) else None,
                'population': population}

    leaves = []
    if tool == 'query_data':
        cols, labels = data.get('columns') or [], _aliases(data)
        vi = cols.index('OBS_VALUE') if 'OBS_VALUE' in cols else None
        ti = cols.index('TIME_PERIOD') if 'TIME_PERIOD' in cols else None
        ui = cols.index('UNIT_MEASURE') if 'UNIT_MEASURE' in cols else None
        for i, row in enumerate(data.get('rows') or []):
            for j, cell in enumerate(row):
                if not _num(cell) or (vi is not None and j != vi):
                    continue
                ent = []
                for k, c in enumerate(cols):
                    if k in (j, ti, ui) or _num(row[k]):
                        continue
                    ent += [str(row[k])] + ([labels[c][str(row[k])]] if str(row[k]) in labels.get(c, {}) else [])
                geo = [cols.index(c) for c in ('REF_AREA', 'REF_AREA_2') if c in cols]
                if geo:
                    area = row[geo[-1]]
                    ent = [str(area)] + ([labels[cols[geo[-1]]][str(area)]] if str(area) in labels.get(cols[geo[-1]], {}) else [])
                key = {c: str(row[k]) for k, c in enumerate(cols) if k not in (j, ti) and row[k] is not None}
                leaves.append(leaf(f'/data/rows/{i}/{j}', cell, ent, key,
                                   str(row[ti]) if ti is not None else _selection_period(env),
                                   text=str(row[ui]) if ui is not None and row[ui] else u_text))
    elif tool == 'compare_periods':
        for k, iv in enumerate(data.get('intervals') or []):
            f, t = str(iv.get('from')), str(iv.get('to'))
            span = f'{f}→{t}'
            for m, row in enumerate(iv.get('rows') or []):
                key = {str(c): str(v) for c, v in (row.get('entity') or {}).items()}
                ent = _key_names(key)
                for field, metric, period, start, end, label in (
                        ('from_value', 'from_value', f, f, f, None), ('to_value', 'to_value', t, t, t, None),
                        ('absolute', 'change_absolute', span, f, t, None),
                        ('percent', 'change_percent', span, f, t, '%')):
                    if _num(row.get(field)):
                        leaves.append(leaf(f'/data/intervals/{k}/rows/{m}/{field}', row[field], ent, key,
                                           period, metric=metric, start=start, end=end, label=label))
    elif tool == 'rank_entities':
        for m, row in enumerate(data.get('rows') or []):
            if _num(row.get('value')):
                key = {str(c): str(v) for c, v in (row.get('entity') or {}).items()}
                leaves.append(leaf(f'/data/rows/{m}/value', row['value'], _key_names(key), key,
                                   data.get('year')))
    elif tool == 'run_recipe':
        for m, row in enumerate(data.get('rows') or []):
            if _num(row.get('value')):
                name = str(row.get('label') or row.get('area') or '')
                leaves.append(leaf(f'/data/rows/{m}/value', row['value'], [name],
                                   {'area': str(row.get('geo_id') or name)},
                                   str(data.get('year')) if data.get('year') else None,
                                   text=row.get('unit') or u_text))
    return leaves


def result_values(results: list[dict]) -> list[float]:
    vals = []
    for r in results:
        if _is_envelope(r):
            for lf in numeric_leaves(r):
                vals += [lf['value']] + ([lf['scaled']] if lf['scaled'] is not None else [])
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
                        'readings': reads, 'scale': scale, 'percent': pct, 'start': m.start(), 'end': m.end()})
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
        n = re.sub(r'^(?:\d+ )?(?:municipiul |orasul |oras )?', '', _norm(e))
        if len(n) >= 2 and n in sentence_norm:
            return True
        if len(e.strip()) == 1 and re.search(rf'(?<![\w]){re.escape(e.strip())}(?![\w])', sentence):
            return True
    return False


def _num_like(s: str) -> bool:
    return bool(re.fullmatch(r'[\d.,\s-]+', s or ''))


def _selection_period(env):
    filters = ((env.get('provenance') or {}).get('effective_selection') or {}).get('filters') or \
              ((env.get('provenance') or {}).get('selection') or {}).get('filters') or {}
    values = filters.get('TIME_PERIOD') or []
    return str(values[0]) if len(values) == 1 else None


# What a claim's own words say about its unit. Missing words are "not stated", never a conflict.
_CLAIM_DEN = (
    (re.compile(r'\b(?:pe|per|la(?: un)?) (?:cap de )?(?:locuitor|rezident|resident|inhabitant|capita|persoana|person)\b'),
     'person'),
    (re.compile(r'\b(?:mia|mie) de locuitori\b|\b(?:la|per) (?:1000|1 000) (?:de )?(?:locuitori|inhabitants|persoane|people)\b|'
                r'\bper (?:thousand|1000) (?:inhabitants|people|residents)\b'), 'thousand_persons'))
_CLAIM_MEASURES = (
    (re.compile(r'\bpuncte? procentuale?\b|\bpercentage points?\b|\bpp\b|\bp\.p\b'), 'percentage_points', None),
    (re.compile(r'%|\bprocent\w*|\bpercent\w*'), 'percent', None),
    (re.compile(r'\b(?:lei|leu|ron)\b'), 'currency', 'RON'),
    (re.compile(r'\b(?:euro|eur)\b|€'), 'currency', 'EUR'),
    (re.compile(r'\b(?:usd|dolari|dollars?)\b|\$'), 'currency', 'USD'),
    (re.compile(r'\bkm2\b|\bkmp\b|\bkilometri patrati\b|\bsquare kilomet(?:re|er)s?\b|\bsq\.? ?km\b'), 'area_km2', None),
    (re.compile(r'\b(?:hectare|hectares|ha)\b'), 'area_ha', None),
    (re.compile(r'\b(?:persoane|persoana|persons?|people|locuitori|inhabitants|oameni|rezidenti|residents)\b'),
     'persons', None),
    (re.compile(r'\b(?:innoptari\w*|overnight stays?|nights|stays)\b'), 'stays', None))
_UNSTATED_UNIT = {'measure': None, 'currency': None, 'denominator': None}


def claimed_unit(text: str) -> dict:
    """The unit a stretch of the answer states: {measure, currency, denominator}, each None when
    the words do not say. The first measure word wins; a "per resident" phrase is a denominator
    and is not also read as a measure of persons."""
    t = _fold(text).replace('%', ' % ')
    out = dict(_UNSTATED_UNIT)
    for rx, den in _CLAIM_DEN:
        m = rx.search(t)
        if m:
            out['denominator'] = den
            t = t[:m.start()] + ' ' + t[m.end():]
            break
    first = None
    for rx, measure, currency in _CLAIM_MEASURES:
        m = rx.search(t)
        if m and (first is None or m.start() < first[0]):
            first = (m.start(), measure, currency)
    if first:
        out['measure'], out['currency'] = first[1], first[2]
    return out


_STRICT_MEASURES = {'percent', 'percentage_points', 'currency', 'area_ha', 'area_km2'}
_COMPATIBLE = {'percent': {'percent'}, 'percentage_points': {'percentage_points'},
               'currency': {'currency'}, 'area_ha': {'area_ha'}, 'area_km2': {'area_km2'},
               'persons': {'persons', 'count'}, 'stays': {'stays', 'count'}}

# Verdicts: unit_mismatch and period_mismatch are explicit contradictions and withhold the prose
# (agent._check_answer). Everything else a verdict can say only keeps the claim unverified.
CONTRADICTIONS = frozenset({'unit_mismatch', 'period_mismatch'})


def _unit_verdict(claimed: dict, leaf: dict, claim: dict | None, form: str) -> str | None:
    """None when the claim's unit words agree with (or do not touch) the cell's unit; unit_mismatch
    for a stated unit that is not the cell's; unit_unverified when the cell's unit is unknown and the
    claim states a strict one (percent, currency, area); scale_mismatch for a scaled source whose
    scale the claim dropped (560,3 persoane for Mii persoane)."""
    cm, cd = claimed['measure'], claimed['denominator']
    if cm is None and cd is None:
        return None
    u = leaf.get('unit_norm') or _UNKNOWN_UNIT
    if cd:
        if not u['known']:
            return 'unit_unverified'
        if u['denominator'] != cd:
            return 'unit_mismatch'
    elif u['denominator'] and cm:             # a ratio phrased as a count or an amount
        return 'unit_mismatch'
    if cm is None:
        return None
    lm = u['measure']
    if lm in _COMPATIBLE[cm]:
        if cm == 'currency' and claimed['currency']:
            if not u['currency']:
                return 'unit_unverified'
            if u['currency'] != claimed['currency']:
                return 'unit_mismatch'
        if form == 'raw' and claim and claim['scale'] == 1.0 and u['scale'] not in (None, 1.0):
            return 'scale_mismatch'
        return None
    if lm == 'percentage_points' and cm == 'percent':
        return 'unit_unverified'              # a bare "%" may mean points; the cell says points
    if lm is None:
        return 'unit_unverified' if cm in _STRICT_MEASURES else None
    return 'unit_mismatch'


def _years_of(text) -> set:
    return set(re.findall(r'\b(?:19|20)\d{2}\b', str(text or '')))


def _year_verdict(years: set, leaf: dict) -> str | None:
    """One stated year must be a year the cell covers: the endpoint's own year for from_value /
    to_value, either endpoint of a change."""
    if len(years) != 1:
        return None
    actual = _years_of(leaf.get('period_from')) | _years_of(leaf.get('period_to')) \
        or _years_of(leaf.get('period'))
    return 'period_mismatch' if actual and not years <= actual else None


_RESIDENT_WORDS = re.compile(r'\b(?:rezident\w*|resedinta obisnuita|usual residen\w*|residents?)\b')
_DOMICILE_WORDS = re.compile(r'\b(?:domiciliu\w*|domicile\w*|registered population|legal address)\b')
_POPULATION_WORDS = re.compile(r'\b(?:populati\w*|population|locuitori|inhabitants|residents?|rezident\w*|'
                               r'domiciliu\w*|domicile\w*)\b')


def stated_definition(text: str) -> str | None:
    """'resident' or 'domicile' when the text names exactly one population definition. A "per
    resident" ratio phrase is a denominator, not a definition."""
    t = _fold(text)
    for rx, _ in _CLAIM_DEN:
        t = rx.sub(' ', t)
    res, dom = bool(_RESIDENT_WORDS.search(t)), bool(_DOMICILE_WORDS.search(t))
    return 'resident' if res and not dom else 'domicile' if dom and not res else None


def _definition_verdict(stated, requested, claimed, leaf, sentence) -> str | None:
    """A stated (or, for a population claim, the question's explicitly requested) definition must
    be the one a reviewed mapping gives the cell; an unclassified source cannot prove it."""
    have = leaf.get('population')
    if claimed['measure'] in (None, 'persons', 'count') and not claimed['denominator']:
        asks = stated or (requested if have or _POPULATION_WORDS.search(_fold(sentence)) else None)
    elif claimed['denominator'] and have:
        asks = stated or requested
    else:
        return None
    if asks is None:
        return None
    return 'definition_unverified' if have is None else None if have == asks else 'definition_mismatch'


def _semantic_conflict(sentence, leaf, unit_text=None, *, claim=None, form='raw', requested=None):
    """Why the claim cannot be this cell, or None. Explicit contradictions (see CONTRADICTIONS) and
    unverifiable context (unknown unit, unclassified population) have stable reasons; a missing unit,
    year or definition is not a contradiction and is reported as unstated by the caller."""
    claimed = claimed_unit(unit_text if unit_text is not None else sentence)
    return (_unit_verdict(claimed, leaf, claim, form)
            or _year_verdict(_years_of(sentence), leaf)
            or _definition_verdict(stated_definition(sentence), requested, claimed, leaf, sentence))


def _matches_leaf(claim: dict, leaf: dict) -> str | None:
    """'raw' when the claim's number is the stored value, 'scaled' when it is the value in base
    units of a scaled source (560 300 persoane for 560,3 in Mii persoane)."""
    if _matches_value(claim, leaf['value']):
        return 'raw'
    if leaf.get('scaled') is not None and _matches_value(claim, leaf['scaled']):
        return 'scaled'
    return None


def _first_reason(verdicts: list) -> str | None:
    """The reason to report when no candidate is free of conflict: a candidate that is merely
    unverifiable outranks one that contradicts, so an unknown unit never turns into an accusation."""
    reasons = [r for _, r in verdicts if r]
    return next((r for r in reasons if r not in CONTRADICTIONS), reasons[0] if reasons else None)


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
    requested = stated_definition(question)
    claims = []
    for sent in _sentences(answer):
        found = find_numbers(sent, question)
        if not found:
            continue
        snorm = _norm(sent)
        for index, c in enumerate(found):
            # Associate a suffix with its own statistic, not another number's
            # unit later in a comparison sentence. Prefix units remain usable.
            end = found[index + 1]['start'] if index + 1 < len(found) else len(sent)
            unit_text = sent[c['start']:end]
            if claimed_unit(unit_text)['measure'] is None and claimed_unit(unit_text)['denominator'] is None:
                begin = found[index - 1]['end'] if index else 0
                unit_text = sent[begin:c['start']]
            cands = [(lf, form) for lf in leaves if (form := _matches_leaf(c, lf))]
            located = [(lf, form) for lf, form in cands if not lf['entity'] or _entity_named(sent, snorm, lf['entity'])]
            verdicts = [(lf, _semantic_conflict(sent, lf, unit_text, claim=c, form=form, requested=requested))
                        for lf, form in located]
            pick = next((lf for lf, r in verdicts if r is None), None)
            conflict = None if pick else _first_reason(verdicts)
            entry = {'text': sent[:200], 'tool_call_id': None, 'path': None, 'entity': None,
                     'period': None, 'unit': None, 'check': 'unverified'}
            if conflict:
                entry['reason'] = conflict
            if pick:
                entry['semantic_check'] = 'no_explicit_conflict'
                entry.update(tool_call_id=pick['call'], path=pick['path'],
                             entity=' · '.join(dict.fromkeys(pick['entity'])) or None,
                             period=pick['period'], unit=pick['unit'], metric=pick['metric'], check='matched')
            claims.append(entry)
            if len(claims) >= MAX_CLAIMS:
                return claims
    return claims
