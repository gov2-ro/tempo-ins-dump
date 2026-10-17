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
  result contains (within rounding/scale tolerance; ``uncited_numbers`` compares magnitudes,
  so "fell by 50" matches a change of -50). What is a claim depends on context: a list
  position, a year, a code or the user's own premise is not, "2 înnoptări pe locuitor" is.
* ``bind_claims`` — each numeric claim tied, by the server, to the JSON Pointer of
  the result cell it matches, with that cell's entity, period and unit. A number
  that merely occurs somewhere is not semantic verification: the wording around the
  number must name the cell's entity and fit its year, unit, direction and population
  definition. Several distinct cells that still fit are ``unverified`` /
  ``ambiguous_binding`` (the first is never chosen); a contradiction in
  ``CONTRADICTIONS`` withholds the prose, every other doubt only leaves the claim unverified.
* ``approximation_notes`` — deterministic wording that keeps an unweighted mean
  from being presented as an official statistic.
"""
from __future__ import annotations

import re
import unicodedata

DATA_TOOLS = ('rank_entities', 'query_data', 'compare_periods', 'run_recipe')
MAX_CLAIMS = 20
MAX_LEAVES = 50_000     # cells considered by bind_claims (a result is <= 32 KiB; this only bounds a pathological trace)
MAX_NAMES = 5_000       # distinct entity names searched for in each sentence that holds a claim

# number token: 1.234.567,8 | 1,234,567.8 | 12 345 | 3,5 | 42
_NUM_RE = re.compile(
    r'(?<![\w.,/])(?<![\w.,/]-)(\d{1,3}(?:[.,  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)'
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


_LANG_LETTERS = 'ăâîșțşţ'


def lang_signal(text: str) -> str | None:
    """The language a question itself shows: 'ro' on a Romanian letter or more Romanian than
    English hint words, 'en' on more English ones, None on a tie (no hint words at all included:
    "PIB Cluj 2023" says nothing)."""
    t = (text or '').lower()
    if re.search(f'[{_LANG_LETTERS}]', t):
        return 'ro'
    toks = re.findall(f'[a-z{_LANG_LETTERS}]+', t)
    ro = sum(w in _RO_HINTS for w in toks)
    en = sum(w in _EN_HINTS for w in toks)
    return 'ro' if ro > en else 'en' if en > ro else None


def guess_lang(text: str, default: str | None = None) -> str:
    """`lang_signal`, or `default` when the text has none. Without a default a tie reads 'en'
    (what this function always returned); `resolve_lang` is the one that weighs the site."""
    return lang_signal(text) or default or 'en'


def resolve_lang(question: str, site: str | None = None) -> tuple[str, str]:
    """The language an Ask turn is written in, and where it came from: a clear signal in the
    question wins ('question'), an ambiguous question follows the site's language ('site', the
    request's `lang`), and with neither the default is Romanian ('default')."""
    sig = lang_signal(question)
    if sig:
        return sig, 'question'
    if site in ('ro', 'en'):
        return site, 'site'
    return 'ro', 'default'


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
    endpoint year), change_absolute / change_percent (spanning period_from..period_to), and for a
    recipe reconstruction (the cross-check of a published value). `key` is the
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
            name = str(row.get('label') or row.get('area') or '')
            key, year = {'area': str(row.get('geo_id') or name)}, (str(data.get('year')) if data.get('year') else None)
            unit_text = row.get('unit') or u_text
            if _num(row.get('value')):
                leaves.append(leaf(f'/data/rows/{m}/value', row['value'], [name], key, year, text=unit_text))
            if _num(row.get('reconstructed')):      # the cross-check of a published value, in the same unit
                leaves.append(leaf(f'/data/rows/{m}/reconstructed', row['reconstructed'], [name], key, year,
                                   metric='reconstruction', text=unit_text))
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


# What makes a number a claim. Context, not a blanket rule: a list position, a year, a code or the
# user's own premise is not a measured value, but "2 înnoptări pe locuitor" or "0 persoane" is.
_SCOPE_BEFORE = re.compile(r'\b(?:pentru|for|peste|sub|over|under|above|below|than|decat|din|dintre|'
                           r'cel putin|cel mult|at least|at most|up to|pana la|de la|from)\s*$|'
                           r'\bnu(?:\s+\w+){0,2}\s*$|\bnot(?:\s+\w+)?\s*$')      # a denied premise (nu sunt 4000)
_IDENT_BEFORE = re.compile(r'\b(?:cod(?:ul)?|code|siruta|id|nr|no|locul|locului|loc|rank|pozitia|pozitie|place|'
                           r'position|top|primele|primii|first|ultimele|ultimii|last|bottom)\s*[:#.]?\s*$')
_DATE_RE = re.compile(r'\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b')
_COUNT_NOUN = re.compile(r'(?:de\s+)?(?:judet|oras|municipi|comun|localit|regiun|citi|counti|town|region|place|'
                         r'municipalit|entit|rand|rows?\b|ani\b|years?\b|luni|months?\b|zile|days?\b|datasets?\b|seturi)')
_RATE_BEFORE = re.compile(r'(?<!de )(?<!pana )\bla\s*$|\bper\s*$|\bpe\s*$|/\s*$')
_RATE_AFTER = re.compile(r'(?:de\s+)?(?:locuitori|inhabitants|nascuti vii|live births)')
_YEAR_PREP = re.compile(r'\b(?:in|din|pentru|for|anul|anului|year|until|pana|since|from|to|between|intre|si|and|'
                        r'de la|la|pe|by|of|at)\s*$')
_MEASURE_CUE = re.compile(r'\b(?:rata|rate|raport\w*|ratio|valoare\w*|value|media|average|mean|indic\w*|index|'
                          r'scor\w*|score)\b(?:\s+(?:de|este|a fost|of|is|was|at|la))?\s*[:=]?\s*$')


def _sign_before(text: str, s: int) -> int:
    """-1 / +1 for an explicit sign directly before the digits (after a space or an opening
    bracket, so a range like 2020-2025 or a name like Cluj-55 has none), else 0."""
    if s and text[s - 1] in '-−–—+' and (s == 1 or text[s - 2] in ' \t\n([:;='):
        return 1 if text[s - 1] == '+' else -1
    return 0


def _states_unit(text: str, end: int) -> bool:
    """Do the words right after the number (to the end of its clause) state a unit?"""
    after = re.split(r'[,;]|\.\s|\n', text[end:end + 48])[0]
    u = claimed_unit(re.split(r'\d', after)[0])           # a unit after the NEXT number is that number's ("0–4 ... 110 persons")
    return bool(u['measure'] or u['denominator'] or claimed_unit(after)['denominator'] == 'thousand_persons')


def _not_a_claim(text, m, raw, plain, asked, codes, date_spans) -> bool:
    """`plain`: an integer with no scale/percent suffix and no sign (the only kind the year, small
    integer and item-count rules apply to)."""
    s = m.start(1)
    suffixed = bool(m.group(2)) or bool(_sign_before(text, s))
    before = _fold(text[max(0, s - 40):s])
    after = _fold(text[m.end(1):m.end(1) + 40])
    if raw in asked and _SCOPE_BEFORE.search(before):
        return True                       # the user's own premise ("for 5000 persons"), not a result
    if suffixed:
        return False
    if any(a <= s < b for a, b in date_spans):
        return True
    if _IDENT_BEFORE.search(before) or (plain and raw in codes):
        return True                       # a rank, list position or identifier (SIRUTA code)
    digits = re.sub(r'\D', '', raw) if re.fullmatch(r'[\d.,\s]+', raw) else ''
    if digits in ('1000', '10000', '100000', '1000000') and _RATE_BEFORE.search(before) \
            and _RATE_AFTER.match(after):
        return True                       # "per 1000 inhabitants" names the base of a rate
    if not plain:
        return False
    if int(raw) <= 100 and _COUNT_NOUN.match(after):
        return True                       # "30 de orașe": how many items, not a statistic of one
    if len(raw) == 4 and 1900 <= int(raw) <= 2100:
        return not (_states_unit(text, m.end(1)) and not _YEAR_PREP.search(before))
    if int(raw) <= 31:                    # a small integer is a value only with a unit or a cue
        return not (_states_unit(text, m.end(1)) or _MEASURE_CUE.search(before))
    return False


def find_numbers(text: str, ignore_text: str = '', codes=frozenset()) -> list[dict]:
    """Numeric claims worth verifying: [{raw, readings, scale, percent, sign, start, end}].

    Skipped by context: years (unless followed by a unit), plain small integers without a unit or a
    measure cue (list numbers, counts of regions), ranks and identifiers (`codes` are the numeric
    codes of the result's entities, e.g. SIRUTA), dates, rate bases ("la 1000 de locuitori"),
    "N de județe"-style item counts, anything glued to letters (matrix codes), and a number the
    question itself contained when the answer only repeats it as a premise ("pentru 5000 de
    persoane"). A number the question contained that the answer states as a result is still a claim.
    """
    asked = {m.group(1) for m in _NUM_RE.finditer(ignore_text or '')}
    date_spans = [(d.start(), d.end()) for d in _DATE_RE.finditer(text or '')]
    out = []
    for m in _NUM_RE.finditer(text or ''):
        raw, suffix = m.group(1), (m.group(2) or '').lower().strip()
        sign = _sign_before(text, m.start(1))
        pct = suffix in ('%', 'procent', 'procente', 'percent')
        scale = 1.0 if pct else _SCALE.get(suffix, 1.0)
        plain_int = bool(re.fullmatch(r'\d+', raw)) and not suffix and not sign
        if _not_a_claim(text, m, raw, plain_int, asked, codes, date_spans):
            continue
        reads = _interpretations(raw)
        if reads:
            out.append({'raw': (raw + (' ' + suffix if suffix else '')).strip(),
                        'readings': reads, 'scale': scale, 'percent': pct, 'sign': sign,
                        'start': m.start(), 'end': m.end()})
    return out


def _looks_rounded(val: float, dec: int) -> bool:
    """Does the printed number end in a zero digit (2.751.000, 4,90, 1010)? Only such a number
    reads as an approximation; 1011 or 58.085 are meant exactly."""
    return round(abs(val) * 10 ** dec) % 10 == 0


def _matches_value(claim: dict, v: float, strict: bool = False) -> bool:
    """Does the claim's number read as v? Within the rounding of the digits it prints, or (not
    `strict`) within 0.5% of v when the number looks rounded."""
    for val, dec in claim['readings']:
        c = val * claim['scale']
        half_ulp = 0.5 * (10 ** -dec) * claim['scale']
        tol = half_ulp if strict or not _looks_rounded(val, dec) else max(half_ulp, 0.005 * abs(v))
        if abs(abs(c) - abs(v)) <= tol:       # "fell by 50" is a claim about a change of -50
            return True
    return False


def _is_exact(claim: dict, v: float) -> bool:
    """The printed number is v itself (not merely v rounded): 10 for 10.0, not for 9.9."""
    return claim['scale'] == 1.0 and any(abs(abs(val) - abs(v)) <= 1e-9 * max(1.0, abs(v))
                                         for val, _ in claim['readings'])


def _matches(claim: dict, values: list[float]) -> bool:
    return any(_matches_value(claim, v) for v in values)


def uncited_numbers(answer: str, results: list[dict], question: str = '') -> list[str]:
    """Numbers in `answer` that no valid query result contains."""
    values = result_values(results)
    codes = _entity_codes([lf for r in results if _is_envelope(r) for lf in numeric_leaves(r)])
    return [c['raw'] for c in find_numbers(answer, question, codes)
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


_ABBREVIATIONS = ('i.e.', 'e.g.', 'mil.', 'mld.', 'nr.', 'ex.', 'etc.', 'cca.', 'aprox.', 'approx.', 'vs.', 'ca.', 'sq.',
                  'no.')


def _sentence_parts(text: str) -> list[tuple[str, bool]]:
    """Sentences and lines of the answer, each with whether it continues the previous one (a ';'
    ended that: "valoarea 10 (celula publicată; reconstrucția dă 9,9)" is one sentence). An
    abbreviation ("i.e.", "mil.", "nr.") ends none: its number and unit stay together."""
    out, start, joined = [], 0, False
    for m in re.finditer(r'(?<=[.!?;])\s+|\n+', text or ''):
        head = text[start:m.start()].lower()
        abbr = next((a for a in _ABBREVIATIONS if head.endswith(a)), None)
        if abbr and not m.group().startswith('\n') and not head[:-len(abbr)][-1:].isalpha():
            continue
        out.append((text[start:m.start()], joined))
        joined = not m.group().startswith('\n') and head.endswith(';')
        start = m.end()
    out.append((text[start:], joined))
    return [(p.strip(), j) for p, j in out if p and p.strip()]


def _sentences(text: str) -> list[str]:
    return [p for p, _ in _sentence_parts(text)]


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


_RESIDENT_WORDS = re.compile(r'\b(?:rezident\w*|resedinta obisnuita|usual residen\w*|resident population|'
                             r'population resident)\b')
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


def _matches_leaf(claim: dict, leaf: dict, strict: bool = False) -> str | None:
    """'raw' when the claim's number is the stored value, 'scaled' when it is the value in base
    units of a scaled source (560 300 persoane for 560,3 in Mii persoane)."""
    if _matches_value(claim, leaf['value'], strict):
        return 'raw'
    if leaf.get('scaled') is not None and _matches_value(claim, leaf['scaled'], strict):
        return 'scaled'
    return None


def _match_tier(claim: dict, leaf: dict, form: str) -> int:
    """0 the printed number is the cell's value, 1 it is the value rounded to the digits printed,
    2 it is within the loose tolerance of a rounded-looking number."""
    v = leaf['value'] if form == 'raw' else leaf['scaled']
    return 0 if _is_exact(claim, v) else 1 if _matches_value(claim, v, strict=True) else 2


def _first_reason(verdicts: list) -> str | None:
    """The reason to report when no candidate is free of conflict: a candidate that is merely
    unverifiable outranks one that contradicts, so an unknown unit never turns into an accusation."""
    reasons = [r for _, r in verdicts if r]
    return next((r for r in reasons if r not in CONTRADICTIONS), reasons[0] if reasons else None)


# ---------------------------------------------------------------- wording anchors

def _pfold(text: str) -> str:
    """Lower-case, accent-free text of the SAME length: anything but a-z, 0-9 and '-' is a space,
    so a position in the folded text is a position in the original."""
    out = []
    for ch in text:
        d = unicodedata.normalize('NFKD', ch).encode('ascii', 'ignore').decode()[:1].lower()
        out.append(d if d.isalnum() or d == '-' else ' ')
    return ''.join(out)


_GENERIC_NAMES = frozenset({'total', 'toate', 'all'})
_NAME_ENDINGS = r'(?:ului|ilor|ul|lui|ele|ile|lor|ei|ii|le|i|e|u|a)?'      # Clujului, Brașovul, Iașii
_PLACE_TYPE = (r'(?P<type>(?:judetul|judetului|jud|county of|municipiul|municipiului|orasul|orasului|'
               r'comuna|comunei|city of|town of) +)?')
_COUNTY_AFTER = re.compile(r'\s*(?:county|judet)\b')
_CONNECTORS = re.compile(r'[\s,/&]*(?:(?:si|and|sau|or|ori|plus|vs)[\s,]*)?')
_LOCATIVE_GAP = re.compile(r'[^,;()]{0,45}?\b(?:in|la|din|pentru|for|at|of|from|across|within)\b'
                           r'(?:\s+(?:judetul|judetului|municipiul|municipiului|orasul|orasului|comuna|comunei|'
                           r'county|city|town|municipality|the))?\s*')
_YEAR_GAP = re.compile(r'(?:[^,;()]{0,40}?\b(?:in|din|pentru|for|la|pe|during|of|anul|anului|year|by|at)\s*'
                       r'(?:anul\s*|year\s*)?|[^,;]{0,30}?\(\s*(?:in\s+|la\s+)?(?:anul\s+)?)')
_YEAR_RANGE = re.compile(r'(?:-|–|—|to|la|si|and|pana in|pana la|until)')
_DOWN = r'(?:sca[dz]\w*|descresc\w*|diminu\w*|pierd\w*|pierder\w*|redu[cs]\w*|declin\w*|coborat\w*|fell|fall\w*|' \
        r'drop\w*|decreas\w*|lost|loss\w*|shr[iau]nk\w*)'
_UP = r'(?:cresc\w*|crest\w*|sporit\w*|adaug\w*|major\w*|urcat\w*|rose|rise[sn]?|rising|grew|grow\w*|increas\w*|' \
      r'gain\w*|jump\w*|surg\w*)'
_AMOUNT_OF = r'(?:cu|de|by|with|of|about|circa|aproximativ|approximately|around|nearly|almost)'
_DIRECTION = re.compile(rf'(?P<down>{_DOWN})\w*(?:\s+{_AMOUNT_OF})?\s*$|(?P<up>{_UP})\w*(?:\s+{_AMOUNT_OF})?\s*$|'
                        rf'(?P<down2>{_DOWN})\w*(?:\s+[a-z0-9-]+){{1,3}}\s+(?:cu|de|by|with|of)\s*$|'
                        rf'(?P<up2>{_UP})\w*(?:\s+[a-z0-9-]+){{1,3}}\s+(?:cu|de|by|with|of)\s*$')
_LEVEL_BEFORE = re.compile(r'\b(?:la|to|at|pana la|spre|from|de la|reaching|reached)\s*$')
_FROM_BEFORE = re.compile(r'\b(?:de la|from)\s*$')
_TO_BETWEEN = re.compile(r'(?:->|→|\b(?:pana la|la|to|until|up to|spre)\b)\W*$', re.I)
_FILLER = frozenset('si and iar sau or ori dar but cu de in la din pentru for plus respectiv adica the per pe '
                    'from then apoi until with'.split())


def _name_key(e) -> str | None:
    """How a sentence can mention an entity: its name without a leading code or place-type word
    (54975 MUNICIPIUL CLUJ-NAPOCA -> 'cluj napoca'); a one-letter name is a code ('code:A'). A pure
    number or code is never a name."""
    s = str(e).strip()
    if not s or _num_like(s):
        return None
    if len(s) == 1:
        return 'code:' + s
    n = re.sub(r'^(?:\d+ )?(?:(?:municipiul|orasul|oras|comuna|judetul) )?', '', _norm(s))
    return n if len(n) >= 2 else None


def _name_regex(key: str):
    toks = key.split()
    return re.compile(r'(?<![a-z0-9])' + _PLACE_TYPE + r'[ -]+'.join(map(re.escape, toks))
                      + (_NAME_ENDINGS if len(toks[-1]) >= 4 else '') + r'(?![a-z0-9])(?!-[a-z])')


def _mentions(sent: str, fold: str, keys, cache: dict) -> list:
    """Entity names of the trace found in the sentence: [(start, end, key, level)], longest first
    so Târgu Mureș is not also the county Mureș and Cluj-Napoca is not the county Cluj. A place-type
    word before the name belongs to the mention; `level` is 'county' for "județul Cluj", "county of
    Cluj" and "Cluj County". A one-letter code must stand alone, in its own case (the Romanian
    word "a" is not entity A)."""
    found = []
    for k in keys:
        if k.startswith('code:'):
            found += [(m.start(), m.end(), k, None)
                      for m in re.finditer(rf'(?<!\w){re.escape(k[5:])}(?!\w)', sent)]
        elif k.split(' ', 1)[0] in fold:
            rx = cache.get(k) or cache.setdefault(k, _name_regex(k))
            found += [(m.start(), m.end(), k,
                       'county' if (m.group('type') or '').startswith(('jud', 'county')) else None)
                      for m in rx.finditer(fold)]
    found.sort(key=lambda x: (x[0] - x[1], x[0]))
    kept = []
    for st, en, k, level in found:
        if not any(st < b and a < en for a, b, *_ in kept):
            kept.append((st, en, k, level))
    return [(st, en, k, level or ('county' if _COUNTY_AFTER.match(fold[en:en + 10]) else None))
            for st, en, k, level in sorted(kept)]


def _entity_group(pre: list, sent: str) -> list:
    """The mentions that share the number: the last one before it plus the names joined to it by
    nothing but commas and "și"/"and" ("Cluj și Iași au 1000"). A generic name (Total) yields to a
    real one."""
    group = [pre[-1]]
    for m in reversed(pre[:-1]):
        if _CONNECTORS.fullmatch(_fold(sent[m[1]:group[0][0]])):
            group.insert(0, m)
        else:
            break
    real = [m for m in group if m[2] not in _GENERIC_NAMES]
    return real or group


def _is_enumeration(sent: str, fold: str, lo: int, hi: int, mentions: list) -> bool:
    """Is the text between two numbers only names, units and connectors (so the second number
    continues the first one's entity, year and direction)?"""
    blank = list(sent[lo:hi])
    for st, en, *_ in mentions:
        for i in range(max(st, lo), min(en, hi)):
            blank[i - lo] = ' '
    gap = _pfold(''.join(blank))
    for rx, _ in _CLAIM_DEN:
        gap = rx.sub(' ', gap)
    for rx, *_ in _CLAIM_MEASURES:
        gap = rx.sub(' ', gap)
    return all(tok in _FILLER for tok in re.findall(r'[a-z]{3,}', gap))


def _sentence_contexts(sent: str, found: list, mentions: list, carry: dict | None = None) -> list:
    """What the wording around each number says about it: the entity mentions it belongs to, the
    years, the direction word, the from/to role. A mention or year right after a number that is
    joined to it by a locative ("300000 în Cluj") belongs to that number and not to the next one.
    Context continues across an enumeration (names, units and "și" only) and otherwise is lost;
    `carry` is the entity and years of the clause before a ';' when this clause names none.
    Each context records where it came from: stated | inherited | sentence."""
    fold = _pfold(sent)
    spans = [(c['start'], c['end']) for c in found]
    years = [(m.start(), m.group()) for m in re.finditer(r'(?<![0-9])(?:19|20)\d{2}(?![0-9])', fold)
             if not any(a <= m.start() < b for a, b in spans)]
    sent_years = {y for _, y in years}
    sentence_def = stated_definition(sent)          # one definition in the whole sentence covers its numbers
    used_m, used_y, out = set(), set(), []
    for i, c in enumerate(found):
        s, e = c['start'], c['end']
        lo = found[i - 1]['end'] if i else 0
        hi = found[i + 1]['start'] if i + 1 < len(found) else len(sent)
        prev = out[-1] if out else None
        enum = prev is not None and _is_enumeration(sent, fold, lo, s, mentions)
        # entity
        ents, ent_how = [], None
        pre = [m for m in mentions if max(lo, s - 160) <= m[0] and m[1] <= s and m[0] not in used_m]
        post = next((m for m in mentions if m[0] >= e and m[0] not in used_m), None)
        if pre:
            ents, ent_how = _entity_group(pre, sent), 'stated'
        elif post and post[1] <= hi and post[0] - e <= 60 and _LOCATIVE_GAP.fullmatch(_fold(sent[e:post[0]])):
            ents, ent_how = [post], 'stated'
            used_m.add(post[0])
        elif prev and prev['ents'] and enum:
            ents, ent_how = prev['ents'], 'inherited'
        elif carry and carry['ents'] and not mentions:
            ents, ent_how = carry['ents'], 'inherited'
        elif mentions:
            ents, ent_how = [m for m in mentions if m[2] not in _GENERIC_NAMES] or list(mentions), 'sentence'
        # years
        ys, y_how, y_hard = set(), None, False
        pre_y = [(p, y) for p, y in years if max(lo, s - 120) <= p and p + 4 <= s and p not in used_y]
        post_y = next(((p, y) for p, y in years if p >= e and p not in used_y), None)
        attached = bool(post_y and post_y[0] + 4 <= hi and post_y[0] - e <= 50
                        and _YEAR_GAP.fullmatch(_fold(sent[e:post_y[0]])))
        if pre_y:      # a year earlier in a sentence with other years may be the date of a source, not of the number
            ys, y_how, y_hard = {y for _, y in pre_y}, 'stated', len(sent_years) == 1
            if attached and i + 1 == len(found):      # the last number: that year cannot be the next one's
                ys.add(post_y[1])
                used_y.add(post_y[0])
                y_hard = True
        elif attached:
            ys, y_how, y_hard = {post_y[1]}, 'stated', True
            used_y.add(post_y[0])
            end_y = next(((p, y) for p, y in years if p > post_y[0]), None)       # "în 2020-2025", "2020 and 2025"
            if end_y and end_y[0] + 4 <= hi and _YEAR_RANGE.fullmatch(_fold(sent[post_y[0] + 4:end_y[0]])):
                ys.add(end_y[1])
                used_y.add(end_y[0])
        elif prev and prev['years'] and enum:
            ys, y_how = prev['years'], 'inherited'
        elif carry and carry['years'] and not sent_years:
            ys, y_how = carry['years'], 'inherited'
        elif len(sent_years) == 1:
            ys, y_how, y_hard = set(sent_years), 'sentence', True
        # direction of a change and from/to role
        before = fold[max(0, s - 70):s].rstrip() + ' '
        level = bool(_LEVEL_BEFORE.search(before))
        md = None if level else _DIRECTION.search(before.rstrip())
        carried = prev['carry'] if (prev and enum) else None        # "a scăzut de la 5 la 3, iar B cu 2"
        direction = ('down' if md.group('down') or md.group('down2') else 'up') if md else \
            None if level else carried
        role = 'from' if _FROM_BEFORE.search(before) else \
            'to' if prev and prev['role'] == 'from' and _TO_BETWEEN.search(sent[lo:s]) else None
        # the number's own unit words: after it up to the next number, else the words before it
        unit_text = sent[s:hi]
        u = claimed_unit(unit_text)
        if not (u['measure'] or u['denominator']):
            unit_text = sent[lo:s]
        stated = stated_definition(sent[lo:s]) or stated_definition(sent[e:min(hi, e + 40)]) or sentence_def
        out.append({'ents': ents, 'ent_how': ent_how, 'years': ys, 'year_how': y_how, 'year_hard': y_hard,
                    'dir': direction, 'carry': direction or carried, 'role': role, 'unit_text': unit_text,
                    'stated': stated, 'def_text': sent, 'sent_years': sent_years, 'enum': enum})
    return out


def _leaf_keys(lf: dict) -> frozenset:
    return frozenset(k for k in (_name_key(e) for e in lf['entity']) if k)


def _entity_verdict(ctx: dict, lf: dict) -> str | None:
    """A cell that belongs to a named entity needs that entity named for THIS number (nearest
    names, not just somewhere in the sentence). A county named as such cannot verify a locality
    row of that county."""
    group = ctx['ents']
    if not lf['keys']:               # not about a named entity; a named one before the number is not it
        return 'entity_mismatch' if group and ctx['ent_how'] == 'stated' else None
    if not group:
        return 'entity_unstated'
    locality = 'REF_AREA_2' in lf['key']
    named = any(m[2] in lf['keys'] and not (m[3] == 'county' and locality) for m in group)
    return None if named else 'entity_mismatch'


def _period_verdict(ctx: dict, lf: dict) -> str | None:
    """The years stated for this number must be years the cell covers (an endpoint's own year; both
    endpoints or either for a change). A from/to role (de la 140 la 100) must meet the endpoint."""
    actual = _years_of(lf.get('period_from')) | _years_of(lf.get('period_to'))
    ys = ctx['years']
    if actual and ys:
        change = lf['metric'] in ('change_absolute', 'change_percent')
        if not (ys <= actual if change else ys & actual):
            return 'period_mismatch' if ctx['year_hard'] else 'period_unverified'
    role = ctx['role']
    if role and lf['metric'] in ('from_value', 'to_value'):
        if lf['metric'] != ('from_value' if role == 'from' else 'to_value'):
            return 'endpoint_mismatch'
    elif role and lf['metric'] == 'observation' and actual:
        pool = ys if len(ys) > 1 else ctx['sent_years']
        if len(pool) > 1 and (min(pool) if role == 'from' else max(pool)) not in actual:
            return 'endpoint_mismatch'
    return None


def _sign_verdict(claim: dict, ctx: dict, lf: dict) -> str | None:
    """Signed cells keep their sign. A written sign decides; otherwise a direction word (fell by,
    scădere de, a loss of) must agree with the cell, and a negative cell needs direction evidence
    ("fell by 40" may refer to -40; a bare 40 may not)."""
    v = lf['value']
    if v == 0:
        return None
    want = claim['sign'] or {'up': 1, 'down': -1}.get(ctx['dir'], 0)
    if want:
        return None if (want > 0) == (v > 0) else 'direction_mismatch'
    return 'direction_unstated' if v < 0 else None


def _coordinate(lf: dict) -> tuple:
    """What a cell is: dataset, full key, period, unit. An observation and an endpoint value of the
    same series and year are one coordinate; the same cell cited by two calls dedupes."""
    level = lf['metric'] in ('observation', 'from_value', 'to_value')
    return (lf['dataset'], tuple(lf['key'].items()), 'level' if level else lf['metric'],
            lf['period_from'], lf['period_to'], lf['unit'])


_CHECK_CUE = re.compile(r'\b(?:reconstruc\w*|reconstitu\w*|verificare|cross[ -]?check|recomput\w*|recalcul\w*)\b')


def _metric_verdict(ctx: dict, lf: dict) -> str | None:
    """A reconstruction is only the cross-check of a published value: a sentence cites it by
    saying so, and does not present it as the figure."""
    if lf['metric'] == 'reconstruction' and not _CHECK_CUE.search(_fold(ctx['def_text'])):
        return 'metric_mismatch'
    return None


def _resolve(claim: dict, ctx: dict, leaves: list, requested, chain=()) -> dict:
    """Narrow the cells that hold the number by the wording around it; never pick between
    equals. `chain` holds the cells bound to the earlier numbers of the same enumeration: when
    the wording leaves a metric open (no unit, "B -50, A -20"), a candidate with a metric of the
    chain is preferred, and only if that leaves exactly one. Returns {leaf, form, reason,
    candidates} where leaf is set only for exactly one distinct coordinate."""
    claimed, stated = claimed_unit(ctx['unit_text']), ctx['stated']
    stages = (
        lambda lf, form: _entity_verdict(ctx, lf),
        lambda lf, form: _metric_verdict(ctx, lf),
        lambda lf, form: _unit_verdict(claimed, lf, claim, form),
        lambda lf, form: _period_verdict(ctx, lf),
        lambda lf, form: _sign_verdict(claim, ctx, lf),
        lambda lf, form: _definition_verdict(stated, requested, claimed, lf, ctx['def_text']))
    alive = [(lf, form) for lf in leaves if (form := _matches_leaf(claim, lf))]
    if not alive:
        return {'leaf': None, 'reason': None, 'candidates': 0}
    # A number printed as one cell's value is that cell's: a cell it only approximates (9.9 for "10",
    # 1012 for "1010", the neighbour's -58085 for "58.085") is not a candidate, so a swapped pair of
    # close values cannot slip through as a rounded match.
    tiers = [_match_tier(claim, lf, form) for lf, form in alive]
    alive = [c for c, t in zip(alive, tiers) if t == min(tiers)]
    for stage in stages:
        verdicts = [(lf, stage(lf, form)) for lf, form in alive]
        kept = [(lf, form) for (lf, form), (_, r) in zip(alive, verdicts) if r is None]
        if not kept:
            return {'leaf': None, 'reason': _first_reason(verdicts), 'candidates': 0}
        alive = kept
    distinct = {}
    for lf, form in alive:
        distinct.setdefault(_coordinate(lf), (lf, form))
    inherited = False
    if len(distinct) > 1 and chain:
        seen = {(_coordinate(c)[2], c['unit_norm']['measure']) for c in chain}
        same = {k: v for k, v in distinct.items() if (k[2], v[0]['unit_norm']['measure']) in seen}
        if len(same) == 1:
            distinct, inherited = same, True
    names = {m[2] for m in ctx['ents'] or []}
    shared = len(names) > 1 and any(lf['keys'] for lf, _ in alive)      # one number for several names
    if len(distinct) > 1 or shared:
        return {'leaf': None, 'reason': 'ambiguous_binding', 'candidates': max(len(distinct), len(names))}
    lf, form = next(iter(distinct.values()))
    return {'leaf': lf, 'form': form, 'reason': None, 'candidates': 1,
            'claimed': claimed, 'stated': stated, 'inherited_metric': inherited}


def _anchors(res: dict, ctx: dict) -> dict:
    """Which parts of the cell's meaning the wording actually fixed (the rest is not verified,
    only not contradicted) and whether that was all of it (`complete`). Detail beside
    `semantic_check: no_explicit_conflict`."""
    lf, claimed = res['leaf'], res['claimed']
    if claimed['measure'] or claimed['denominator']:
        unit = 'stated' if lf['unit_norm']['known'] else 'source_unknown'
    else:
        unit = 'inherited' if res['inherited_metric'] else 'unstated'
    out = {'entity': ctx['ent_how'] if lf['keys'] else 'not_needed',
           'period': (ctx['year_how'] or 'unstated')
           if (lf.get('period_from') or lf.get('period_to')) else 'not_needed',
           'unit': unit}
    if lf['value'] < 0:
        out['direction'] = 'stated' if ctx['dir'] else 'sign'
    if lf.get('population'):
        out['definition'] = 'stated' if res['stated'] else 'unstated'
    # complete: the wording itself fixed every part of the cell's meaning (not inherited, not left open)
    out['complete'] = (out['entity'] in ('stated', 'not_needed') and out['period'] in ('stated', 'sentence', 'not_needed')
                       and out['unit'] == 'stated' and out.get('definition', 'stated') == 'stated')
    return out


def _entity_codes(leaves: list) -> frozenset:
    """Numeric codes inside the cells' entity labels (54975 MUNICIPIUL CLUJ-NAPOCA): identifiers,
    not statistics, when they appear in the answer."""
    return frozenset(m.group(1) for lf in leaves for e in lf['entity']
                     if (m := re.match(r'\s*(\d{3,})\s+\S', str(e))))


def bind_claims(answer: str, question: str, tool_trace: list[dict]) -> list[dict]:
    """Bind each numeric claim of `answer` to a result cell, deterministically.

    Returns up to MAX_CLAIMS entries {text, tool_call_id, path, entity, period, unit, check}.
    ``check`` is ``matched`` only when exactly one distinct cell holds the number AND the wording
    around that number does not contradict it: the cell's entity is named for this number, its
    stated year, unit, direction and population definition fit. Otherwise ``unverified`` with a
    stable ``reason`` (``ambiguous_binding`` when several distinct cells remain; never the first of
    them). Matched entries add ``metric`` and ``anchors`` (what the wording fixed). Nothing the
    model wrote about its own sources is used."""
    leaves = []
    for t in tool_trace:
        o = t.get('output')
        if t.get('tool') in DATA_TOOLS and _is_envelope(o) and o.get('status') in ('ok', 'partial'):
            leaves += [{**lf, 'call': t.get('id')} for lf in numeric_leaves(o, t.get('id'))]
    leaves = leaves[:MAX_LEAVES]
    for lf in leaves:
        lf['keys'] = _leaf_keys(lf)
    keys = sorted({k for lf in leaves for k in lf['keys']})[:MAX_NAMES]
    codes, cache = _entity_codes(leaves), {}
    requested = stated_definition(question)
    claims, carry = [], None
    for sent, joined in _sentence_parts(answer):
        found = find_numbers(sent, question, codes)[:MAX_CLAIMS - len(claims)]      # work is bounded by the cap
        if not found:
            carry = None
            continue
        sent = sent[:found[-1]['end'] + 200]                  # nothing after the last bound claim is read
        mentions = _mentions(sent, _pfold(sent), keys, cache)
        contexts = _sentence_contexts(sent, found, mentions, carry if joined else None)
        carry, chain = {'ents': contexts[-1]['ents'], 'years': contexts[-1]['years']}, []
        for c, ctx in zip(found, contexts):
            if not ctx['enum']:
                chain = []                                   # a new enumeration starts here
            res = _resolve(c, ctx, leaves, requested, chain)
            entry = {'text': sent[:200], 'tool_call_id': None, 'path': None, 'entity': None,
                     'period': None, 'unit': None, 'check': 'unverified'}
            if res['reason']:
                entry['reason'] = res['reason']
            if res['reason'] == 'ambiguous_binding':
                entry['candidates'] = res['candidates']
            lf = res['leaf']
            if lf:
                chain.append(lf)
                entry['semantic_check'] = 'no_explicit_conflict'
                entry.update(tool_call_id=lf['call'], path=lf['path'],
                             entity=' · '.join(dict.fromkeys(lf['entity'])) or None,
                             period=lf['period'], unit=lf['unit'], metric=lf['metric'], check='matched',
                             anchors=_anchors(res, ctx))
            claims.append(entry)
            if len(claims) >= MAX_CLAIMS:
                return claims
    return claims
