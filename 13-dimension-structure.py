"""
Dimension Structure Profiler for INS TEMPO datasets.

Answers, per (dataset, dimension): what do this dimension's options *mean*?

The chart engine has always reduced a dimension to (dim_type, option_count).
That is why POP107D reports Romania's population as 38.8M — its AGE dim holds
two complete overlapping partitions (85 single years AND 17 five-year bands),
so an unfiltered SUM counts everybody twice; and why ART101C's ranking tile
draws the same 3 libraries three times, once per geo nesting level.

This profiler splits each dimension's options into verified LEVELS — sets of
options that tile the domain without overlapping — plus the aggregate option
that rolls them up. The composer can then group by / pin one level instead of
mixing them.

Method: structure proposes, data disposes.
  Proposers (metadata only, cheap) suggest candidate partitions from parsed
  age intervals, geo levels, parent_id depth, label indentation, "- total"
  suffixes and CAEN code depth.
  Verification (one GROUP BY per dim, on the 3 most recent periods) keeps only
  the partitions whose sums actually agree. Anything unconfirmed is stored as
  'proposed' and the composer ignores it — the profiler must never make a
  chart worse than it is today.

Writes: dimension_structure (one row per matrix_code × dim_column).
"""

import argparse
import json
import math
import os
import re
import statistics
import time
from collections import defaultdict

import duckdb

from duckdb_config import DB_FILE, CORPUS_PARQUET_DIR

DB_PATH = str(DB_FILE)
FALLBACK_DB = "data/dimension_structure.duckdb"
PROGRESS_INTERVAL = 200

# Sums of two partitions of the same domain agree within this relative gap.
TOLERANCE = 0.02
# Periods sampled for verification. One bad year must not flip a dataset.
SAMPLE_PERIODS = 3
MIN_PERIODS_AGREE = 2
# Columns that are never dimensions.
NON_DIM_COLS = {"OBS_VALUE", "value"}

TABLE = "dimension_structure"

DDL = f"""
CREATE TABLE {TABLE} (
    matrix_code VARCHAR,
    dim_column VARCHAR,
    dim_type VARCHAR,
    levels VARCHAR,              -- JSON [{{level_id,name,kind,members,verified,n}}]
    default_level VARCHAR,
    n_levels INTEGER,
    aggregate_value VARCHAR,     -- verified total option's data value, or NULL
    aggregate_verified BOOLEAN,
    additive BOOLEAN,            -- NULL when undecidable
    nests_in VARCHAR,
    n_effective INTEGER,
    discrimination DOUBLE,       -- CV of option sums at the default level
    dominance DOUBLE,            -- largest option's share of the level total
    source VARCHAR,              -- which proposer produced the levels
    confidence VARCHAR,          -- verified | proposed | flat
    created_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (matrix_code, dim_column)
)
"""

COLS = [
    "matrix_code", "dim_column", "dim_type", "levels", "default_level",
    "n_levels", "aggregate_value", "aggregate_verified", "additive",
    "nests_in", "n_effective", "discrimination", "dominance",
    "source", "confidence",
]

# Mirrors chart_selector.TOTAL_RE — kept local so the pipeline does not import
# from app/. Any change must be made in both places.
TOTAL_RE = re.compile(
    r'^(total|toate|ambele sexe|ambele|urban\s*\+\s*rural|m\s*\+\s*f)\b', re.I)
TOTAL_SUFFIX_RE = re.compile(r'-\s*total\s*$', re.I)
# Leading CAEN-style numeric code: "02 Silvicultura", "0211 Exploatare"
CAEN_CODE_RE = re.compile(r'^\s*(\d{1,4})\s+\S')

GEO_LEVEL_ORDER = ["macroregion", "region", "county", "locality"]
# Level names surface verbatim in the grain switcher, so they are the RO
# terms a reader of the site already sees on the options themselves.
GEO_LEVEL_NAMES = {
    "macroregion": "macroregiuni",
    "region": "regiuni",
    "county": "judete",
    "locality": "localitati",
}


# ---------------------------------------------------------------------------
# Metadata loading
# ---------------------------------------------------------------------------

def load_dims(conn, matrix_code):
    """Dimensions of one matrix with their options and parsed attributes.

    dim_column_name is sometimes legacy v2 (*_nom_id) and sometimes SDMX,
    depending on which pipeline phase last touched the row — resolve it the
    same way dataset_meta.py does.
    """
    dims_raw = conn.execute("""
        SELECT d.dim_label, d.dim_column_name, d.dimension_id
        FROM dimensions d WHERE d.matrix_code = ? ORDER BY d.dim_code
    """, [matrix_code]).fetchall()
    if not dims_raw:
        return []

    col_map = {}
    if any(r[1].endswith('_nom_id') for r in dims_raw):
        parent = conn.execute(
            "SELECT parent_matrix_code FROM matrices WHERE matrix_code = ?",
            [matrix_code]).fetchone()
        lookup = (parent[0] or matrix_code) if parent else matrix_code
        col_map = dict(conn.execute("""
            SELECT old_column_name, sdmx_column_name
            FROM sdmx_column_map WHERE matrix_code = ?
        """, [lookup]).fetchall())

    dims = []
    for dim_label, col_raw, dim_id in dims_raw:
        col = col_map.get(col_raw, col_raw) if col_raw.endswith('_nom_id') else col_raw
        opts = conn.execute("""
            SELECT o.option_label, o.option_offset, o.parent_id, o.nom_item_id,
                   p.dim_type, p.geo_level, p.age_min, p.age_max,
                   sc.sdmx_value
            FROM dimension_options o
            LEFT JOIN dimension_options_parsed p ON o.nom_item_id = p.nom_item_id
            LEFT JOIN sdmx_codes sc ON o.nom_item_id = sc.nom_item_id
            WHERE o.dimension_id = ? ORDER BY o.option_offset
        """, [dim_id]).fetchall()

        type_counts = defaultdict(int)
        options = []
        for label, offset, parent_id, nom_id, dt, geo_lvl, amin, amax, sdmx in opts:
            if dt:
                type_counts[dt] += 1
            options.append({
                'label': label or '', 'offset': offset, 'parent_id': parent_id,
                'nom_item_id': nom_id, 'geo_level': geo_lvl,
                'age_min': amin, 'age_max': amax, 'sdmx_value': sdmx,
            })
        dim_type = max(type_counts, key=type_counts.get) if type_counts else 'indicator'
        dims.append({'dim_label': dim_label, 'dim_column': col,
                     'dim_type': dim_type, 'options': options})
    return dims


def match_options(options, data_values):
    """Map each parquet value to its metadata option.

    Same precedence as dashboard_composer._effective: sdmx_value, then label,
    then the trimmed label. Returns {data_value: option}; unmatched parquet
    values get a synthetic option so they still take part in the partitions.
    """
    by_key = {}
    for o in options:
        for cand in (o.get('sdmx_value'), o['label'], o['label'].strip()):
            if cand:
                by_key.setdefault(str(cand), o)
    out = {}
    for v in data_values:
        s = str(v)
        out[v] = by_key.get(s) or by_key.get(s.strip()) or {
            'label': s, 'offset': None, 'parent_id': None, 'nom_item_id': None,
            'geo_level': None, 'age_min': None, 'age_max': None,
            'sdmx_value': None,
        }
    return out


# ---------------------------------------------------------------------------
# Proposers — candidate partitions from structure alone
# ---------------------------------------------------------------------------

def propose_age(matched):
    """Levels from parsed age intervals.

    POP107D's AGE holds [0,0],[1,1],…,[84,84],[85,999] AND
    [0,4],[5,9],…,[80,84],[85,999] — two covers of the same 0..999 span.
    Repeated greedy interval cover separates them. Intervals that overlap a
    kept cover without tiling it (Eurostat-style roll-ups: 15-64 alongside
    15-24/25-54/55-64) are aggregates, not a level of their own.
    """
    iv = []
    for v, o in matched.items():
        a, b = o.get('age_min'), o.get('age_max')
        if a is None or b is None:
            return None, []
        iv.append((a, b, v))
    if len(iv) < 3:
        return None, []

    span_max = max(b for _, b, _ in iv)
    span_min = min(a for a, _, _ in iv)
    full = [v for a, b, v in iv if a <= span_min and b >= span_max]
    rest = [(a, b, v) for a, b, v in iv if v not in set(full)]
    if not rest:
        return None, []

    pool = sorted(rest)
    lo = min(a for a, _, _ in pool)
    hi = max(b for _, b, _ in pool)

    covers, remaining = [], list(pool)
    while remaining:
        cover, last = [], lo - 1
        for a, b, v in remaining:
            if a == last + 1:
                cover.append((a, b, v))
                last = b
        claimed = {v for _, _, v in cover}
        # An open-ended top band ("85 ani si peste") belongs to every grain,
        # so a cover may borrow intervals another cover already claimed
        # rather than being written off as incomplete.
        while last < hi:
            nxt = next((x for x in pool if x[0] == last + 1), None)
            if nxt is None:
                break
            cover.append(nxt)
            last = nxt[1]
        # A cover assembled purely from borrowed intervals is one we already
        # emitted, and claiming nothing would leave `remaining` unchanged
        # forever. TFX0531's overlapping bands (15-24, 25-54, 35-54, 55-64)
        # hit exactly that: the leftovers are roll-ups, not another grain.
        if len(cover) < 2 or last < hi or not claimed:
            break
        covers.append(cover)
        remaining = [x for x in remaining if x[2] not in claimed]

    levels, leftovers = [], [v for _, _, v in remaining]
    for cover in covers:
        widths = [b - a + 1 for a, b, _ in cover if b < 900]
        w = int(statistics.median(widths)) if widths else 1
        levels.append({
            'level_id': f'age_w{w}',
            'name': 'ani individuali' if w <= 1 else f'grupe de {w} ani',
            'kind': 'age',
            'members': [v for _, _, v in cover],
        })
    return (levels or None), full + leftovers


def propose_geo(matched):
    """Levels from parsed geo_level; 'national' is the aggregate."""
    by_lvl = defaultdict(list)
    for v, o in matched.items():
        by_lvl[o.get('geo_level') or 'unknown'].append(v)
    aggregates = by_lvl.pop('national', [])
    known = [l for l in GEO_LEVEL_ORDER if len(by_lvl.get(l, [])) >= 2]
    if len(known) < 2:
        return None, aggregates
    return [{'level_id': f'geo_{l}', 'name': GEO_LEVEL_NAMES.get(l, l),
             'kind': 'geo', 'members': by_lvl[l]} for l in known], aggregates


def propose_parent_id(matched):
    """Levels from parent_id depth — a real tree when >50% of options have one."""
    have = [o for o in matched.values() if o.get('parent_id')]
    if len(have) <= len(matched) / 2:
        return None, []
    by_nid = {o['nom_item_id']: o for o in matched.values() if o.get('nom_item_id')}
    depth_of = {}

    def depth(o, guard=0):
        nid = o.get('nom_item_id')
        if nid in depth_of:
            return depth_of[nid]
        p = o.get('parent_id')
        d = 0 if (not p or p not in by_nid or guard > 12) else depth(by_nid[p], guard + 1) + 1
        depth_of[nid] = d
        return d

    by_depth = defaultdict(list)
    for v, o in matched.items():
        by_depth[depth(o)].append(v)
    levels = [{'level_id': f'tree_d{d}', 'name': f'nivel {d + 1}', 'kind': 'tree',
               'members': by_depth[d]}
              for d in sorted(by_depth) if len(by_depth[d]) >= 2]
    return (levels if len(levels) >= 2 else None), []


def propose_indent(matched):
    """Levels from label indentation — INS encodes trees as leading spaces."""
    by_depth = defaultdict(list)
    for v, o in matched.items():
        lbl = o['label']
        by_depth[len(lbl) - len(lbl.lstrip())].append(v)
    if len(by_depth) < 2:
        return None, []
    levels = [{'level_id': f'indent_{d}', 'name': f'nivel {i + 1}',
               'kind': 'indent', 'members': by_depth[d]}
              for i, d in enumerate(sorted(by_depth)) if len(by_depth[d]) >= 2]
    return (levels if len(levels) >= 2 else None), []


def propose_caen(matched):
    """Levels from CAEN code depth: '02 Silvicultura' vs '0210 Silvicultura'."""
    by_len = defaultdict(list)
    for v, o in matched.items():
        m = CAEN_CODE_RE.match(o['label'])
        if not m:
            return None, []
        by_len[len(m.group(1))].append(v)
    levels = [{'level_id': f'caen_{n}', 'name': f'cod {n} cifre', 'kind': 'caen',
               'members': by_len[n]} for n in sorted(by_len) if len(by_len[n]) >= 2]
    return (levels if len(levels) >= 2 else None), []


def propose_aggregates(matched):
    """Options that look like roll-ups: 'Total', 'Taurine - total'."""
    out = []
    for v, o in matched.items():
        lbl = o['label'].strip()
        if TOTAL_RE.match(lbl) or TOTAL_SUFFIX_RE.search(lbl):
            out.append(v)
    return out


PROPOSERS = [
    ('age', propose_age),
    ('geo', propose_geo),
    ('parent_id', propose_parent_id),
    ('caen', propose_caen),
    ('indent', propose_indent),
]


# ---------------------------------------------------------------------------
# Verification — the data decides
# ---------------------------------------------------------------------------

def close(a, b):
    m = max(abs(a), abs(b))
    return m == 0 or abs(a - b) / m <= TOLERANCE


def verify_levels(levels, sums_by_period):
    """Keep the largest group of levels whose per-period sums agree.

    Agreement must hold in at least MIN_PERIODS_AGREE of the sampled periods,
    so a level that simply has no data in one year is not disqualified.
    """
    if len(levels) < 2:
        return levels, len(levels) == 1

    def agree(a, b):
        hits = 0
        for sums in sums_by_period:
            sa = sum(sums.get(v, 0) or 0 for v in a['members'])
            sb = sum(sums.get(v, 0) or 0 for v in b['members'])
            if sa == 0 and sb == 0:
                continue
            if close(sa, sb):
                hits += 1
        return hits >= min(MIN_PERIODS_AGREE, len(sums_by_period))

    best = []
    for i, base in enumerate(levels):
        group = [base] + [l for j, l in enumerate(levels) if j != i and agree(base, l)]
        if len(group) > len(best):
            best = group
    if len(best) < 2:
        return [], False
    return best, True


def verify_partition(levels, all_values, agg_values, sums_by_period):
    """A complete partition whose leftovers are a drill-down, not a rival grain.

    ART101C's "Categorii de biblioteci" is Nationale / Ale institutiilor /
    Specializate / Scolare / Publice, and then Judetene + Municipale +
    Comunale — which sum to *Publice alone* (1,758), not to the whole
    dimension. `verify_levels` correctly refuses to call those two an
    alternative grain, but the shallow level is still the honest partition:
    summing all eight gives 9,863 where the truth is 8,105.

    Returns (level, True) when one candidate's leftovers tile a single member
    of it, so the level can be summed exactly once.
    """
    agg = set(map(str, agg_values or []))
    for cand in levels:
        members = [m for m in cand['members'] if str(m) not in agg]
        if len(members) < 2:
            continue
        rest = [v for v in all_values
                if v not in set(members) and str(v) not in agg]
        if not rest:
            continue
        hits = 0
        for sums in sums_by_period:
            r = sum(sums.get(v, 0) or 0 for v in rest)
            if r == 0:
                continue
            # the leftovers must equal exactly one member of the level
            if any(close(r, sums.get(m, 0) or 0) for m in members):
                hits += 1
        if hits >= min(MIN_PERIODS_AGREE, len(sums_by_period)):
            return {**cand, 'members': members, 'kind': 'partition'}, True
    return None, False


def verify_aggregate(agg_values, level, sums_by_period):
    """The aggregate is real when it equals the level's sum, not when it is
    merely spelled 'Total'. This is what rejects 'Total fructe'."""
    if not agg_values or not level:
        return None, False
    for v in agg_values:
        hits = 0
        for sums in sums_by_period:
            a = sums.get(v)
            s = sum(sums.get(x, 0) or 0 for x in level['members'])
            if a is None or (a == 0 and s == 0):
                continue
            if close(a, s):
                hits += 1
        if hits >= min(MIN_PERIODS_AGREE, len(sums_by_period)):
            return v, True
    return agg_values[0], False


def pick_default(levels, dim_type):
    """Which level the composer uses when nothing asks for another.

    Geo wants the finest mappable grain — a 4-shape macroregion map is not a
    map, and a 4-bar ranking is not a ranking. Everything else wants the
    coarsest grain, because a first overview should be readable.
    """
    if not levels:
        return None
    if dim_type == 'geo':
        big = [l for l in levels if len(l['members']) >= 8]
        return max(big or levels, key=lambda l: len(l['members']))['level_id']
    return min(levels, key=lambda l: len(l['members']))['level_id']


# ---------------------------------------------------------------------------
# Per-dimension profiling
# ---------------------------------------------------------------------------

def profile_dim(pconn, path, dim, value_col, time_col, periods):
    col = dim['dim_column']
    where = ""
    params = [path]
    if time_col and periods:
        marks = ", ".join("?" for _ in periods)
        where = f'WHERE "{time_col}" IN ({marks})'
        params += list(periods)

    period_sel = f'"{time_col}"' if time_col else "'_'"
    sql = (f'SELECT "{col}" AS k, {period_sel} AS p, SUM("{value_col}") AS v '
           f'FROM read_parquet(?) {where} GROUP BY 1, 2')
    rows = pconn.execute(sql, params).fetchall()

    sums_by_period = defaultdict(dict)
    overall = defaultdict(float)
    for k, p, v in rows:
        if k is None:
            continue
        sums_by_period[p][k] = v
        overall[k] += (v or 0)
    if not overall:
        return None
    periods_sums = list(sums_by_period.values()) or [dict(overall)]

    matched = match_options(dim['options'], list(overall.keys()))
    agg_candidates = propose_aggregates(matched)

    levels, source, extra_agg = None, 'flat', []
    for name, fn in PROPOSERS:
        proposed, aggs = fn(matched)
        if proposed and len(proposed) >= 2:
            levels, source, extra_agg = proposed, name, aggs
            break
        if aggs and not extra_agg:
            extra_agg = aggs
    agg_candidates = list(dict.fromkeys(extra_agg + agg_candidates))

    # Members are partitions of the non-aggregate options only.
    agg_set = set(agg_candidates)
    if levels:
        for l in levels:
            l['members'] = [m for m in l['members'] if m not in agg_set]
        levels = [l for l in levels if len(l['members']) >= 2]

    verified = False
    proposed = list(levels or [])
    if proposed and len(proposed) >= 2:
        levels, verified = verify_levels(proposed, periods_sums)
    else:
        levels = []
    if not verified and proposed:
        # No rival grain — but the shallowest depth may still be the complete
        # partition, with the rest drilling into one of its members.
        one, verified = verify_partition(proposed, list(overall.keys()),
                                         agg_candidates, periods_sums)
        levels = [one] if verified else []

    if not levels:
        # Flat dim: one implicit level holding every non-aggregate option.
        members = [v for v in overall if v not in agg_set]
        levels = [{'level_id': 'all', 'name': 'toate', 'kind': 'flat',
                   'members': members}] if members else []
        source, verified = 'flat', False

    for l in levels:
        l['verified'] = verified
        l['n'] = len(l['members'])

    default_id = pick_default(levels, dim['dim_type'])
    default = next((l for l in levels if l['level_id'] == default_id), None)
    agg_value, agg_ok = verify_aggregate(agg_candidates, default, periods_sums)

    # Additivity is only decidable against a confirmed aggregate.
    additive = True if agg_ok else None

    disc = dom = None
    if default:
        vals = [overall.get(m, 0) or 0 for m in default['members']]
        tot = sum(vals)
        if len(vals) >= 2 and tot:
            mu = tot / len(vals)
            if mu:
                disc = round(
                    math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals)) / abs(mu), 4)
            dom = round(max(vals) / tot, 4)

    return {
        'dim_column': col,
        'dim_type': dim['dim_type'],
        'levels': levels,
        'default_level': default_id,
        'n_levels': len([l for l in levels if l['kind'] != 'flat']),
        'aggregate_value': str(agg_value) if agg_value is not None else None,
        'aggregate_verified': agg_ok,
        'additive': additive,
        'n_effective': len(overall),
        'discrimination': disc,
        'dominance': dom,
        'source': source,
        'confidence': 'verified' if verified else ('flat' if source == 'flat' else 'proposed'),
    }


def detect_nesting(pconn, path, dims, present, cards, time_col, periods):
    """child -> parent when every child value belongs to exactly one parent.

    SOM101E carries REF_AREA (41 counties) and REF_AREA_2 (3,179 localities);
    knowing the second nests in the first is what lets the UI offer a
    drill-down instead of a 3,179-entry dropdown.

    Restricted to the sampled periods like every other probe here: a locality
    belongs to one county in every year or none, and scanning POP107D's 21.6M
    rows per candidate pair costs gigabytes to learn the same thing.
    """
    out = {}
    where, base = "", [path]
    if time_col and periods:
        marks = ", ".join("?" for _ in periods)
        where = f'AND "{time_col}" IN ({marks})'
        base = [path] + list(periods)
    # A unit dim is never a hierarchy parent: "every product is measured in
    # one unit" is a functional dependency, not a containment.
    cand = [d['dim_column'] for d in dims
            if d['dim_column'] in present and cards.get(d['dim_column'], 0) >= 2
            and d['dim_type'] != 'unit']
    parents = [d['dim_column'] for d in dims
               if d['dim_column'] in cand and d['dim_type'] != 'unit']
    for child in cand:
        for parent in parents:
            if child == parent or cards[child] <= cards[parent] * 2:
                continue
            row = pconn.execute(
                f'SELECT MAX(n) FROM (SELECT COUNT(DISTINCT "{parent}") AS n '
                f'FROM read_parquet(?) WHERE "{child}" IS NOT NULL {where} '
                f'GROUP BY "{child}")', base).fetchone()
            if row and row[0] == 1:
                out[child] = parent
                break
    return out


def profile_matrix(rconn, pconn, matrix_code):
    path = str(CORPUS_PARQUET_DIR / f"{matrix_code}.parquet")
    if not os.path.exists(path):
        return []
    dims = load_dims(rconn, matrix_code)
    if not dims:
        return []

    cols = [c[0] for c in pconn.execute(
        'DESCRIBE SELECT * FROM read_parquet(?)', [path]).fetchall()]
    present = set(cols)
    value_col = 'OBS_VALUE' if 'OBS_VALUE' in present else (
        'value' if 'value' in present else None)
    if not value_col:
        return []

    time_dims = [d for d in dims
                 if d['dim_type'] == 'time' and d['dim_column'] in present]
    time_col = max(time_dims, key=lambda d: len(d['options']),
                   default=None)
    time_col = time_col['dim_column'] if time_col else None

    periods = []
    if time_col:
        periods = [r[0] for r in pconn.execute(
            f'SELECT DISTINCT "{time_col}" FROM read_parquet(?) '
            f'WHERE "{time_col}" IS NOT NULL ORDER BY 1 DESC LIMIT {SAMPLE_PERIODS}',
            [path]).fetchall()]

    recs, cards = [], {}
    for dim in dims:
        col = dim['dim_column']
        if col not in present or col in NON_DIM_COLS or col == time_col:
            continue
        try:
            rec = profile_dim(pconn, path, dim, value_col, time_col, periods)
        except Exception:
            rec = None
        if rec:
            rec['matrix_code'] = matrix_code
            cards[col] = rec['n_effective']
            recs.append(rec)

    nesting = detect_nesting(pconn, path, dims, present, cards, time_col, periods)
    for r in recs:
        r['nests_in'] = nesting.get(r['dim_column'])
    return recs


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def open_write_conn():
    try:
        conn = duckdb.connect(DB_PATH, read_only=False)
        print(f"Writing to main DB: {DB_PATH}")
        return conn, True
    except duckdb.IOException:
        print(f"Main DB locked, writing to fallback: {FALLBACK_DB}")
        return duckdb.connect(FALLBACK_DB), False


def to_row(rec):
    return [
        rec['matrix_code'], rec['dim_column'], rec['dim_type'],
        json.dumps(rec['levels'], ensure_ascii=False), rec['default_level'],
        rec['n_levels'], rec['aggregate_value'], rec['aggregate_verified'],
        rec['additive'], rec.get('nests_in'), rec['n_effective'],
        rec['discrimination'], rec['dominance'], rec['source'], rec['confidence'],
    ]


def print_summary(conn):
    print("\n--- Confidence ---")
    for r in conn.execute(
            f"SELECT confidence, COUNT(*) FROM {TABLE} GROUP BY 1 ORDER BY 2 DESC").fetchall():
        print(f"  {r[0]:>10}: {r[1]}")
    print("\n--- Multi-level dimensions by source ---")
    for r in conn.execute(
            f"SELECT source, COUNT(*) FROM {TABLE} WHERE confidence='verified' "
            f"AND n_levels >= 2 GROUP BY 1 ORDER BY 2 DESC").fetchall():
        print(f"  {r[0]:>10}: {r[1]}")
    n = conn.execute(
        f"SELECT COUNT(DISTINCT matrix_code) FROM {TABLE} "
        f"WHERE confidence='verified' AND n_levels >= 2").fetchone()[0]
    print(f"\n  datasets with >=1 multi-level dim: {n}")
    print("\n--- Verified aggregates ---")
    r = conn.execute(
        f"SELECT COUNT(*) FILTER (WHERE aggregate_verified), "
        f"COUNT(*) FILTER (WHERE aggregate_value IS NOT NULL AND NOT aggregate_verified) "
        f"FROM {TABLE}").fetchone()
    print(f"  confirmed: {r[0]}   rejected (label says total, sums disagree): {r[1]}")
    print("\n--- Nesting ---")
    for r in conn.execute(
            f"SELECT dim_column, nests_in, COUNT(*) FROM {TABLE} "
            f"WHERE nests_in IS NOT NULL GROUP BY 1,2 ORDER BY 3 DESC LIMIT 8").fetchall():
        print(f"  {r[0]} -> {r[1]}: {r[2]}")


def validate(conn, pconn):
    """Assert the levels we shipped actually hold, on the data."""
    print("\n=== Validation ===")
    bad = 0
    rows = conn.execute(
        f"SELECT matrix_code, dim_column, levels, default_level, aggregate_value "
        f"FROM {TABLE} WHERE confidence='verified' AND aggregate_verified").fetchall()
    for mc, col, levels_json, default_id, agg in rows:
        levels = json.loads(levels_json)
        lvl = next((l for l in levels if l['level_id'] == default_id), None)
        if not lvl:
            continue
        path = str(CORPUS_PARQUET_DIR / f"{mc}.parquet")
        marks = ", ".join("?" for _ in lvl['members'])
        s = pconn.execute(
            f'SELECT SUM("OBS_VALUE") FROM read_parquet(?) '
            f'WHERE CAST("{col}" AS VARCHAR) IN ({marks})',
            [path] + [str(m) for m in lvl['members']]).fetchone()[0]
        a = pconn.execute(
            f'SELECT SUM("OBS_VALUE") FROM read_parquet(?) '
            f'WHERE CAST("{col}" AS VARCHAR) = ?', [path, str(agg)]).fetchone()[0]
        if s is not None and a is not None and not close(s, a):
            bad += 1
            if bad <= 10:
                print(f"  MISMATCH {mc}.{col}: level={s:,.0f} aggregate={a:,.0f}")
    print(f"  checked {len(rows)} verified aggregates, {bad} mismatched")
    return bad


def main():
    ap = argparse.ArgumentParser(description="Profile dimension structure.")
    ap.add_argument("--matrix", help="Comma-separated matrix codes")
    ap.add_argument("--all", action="store_true", help="Rebuild the whole table")
    ap.add_argument("--validate", action="store_true",
                    help="Re-check verified levels against the parquets")
    ap.add_argument("--dry-run", action="store_true", help="Profile but do not write")
    args = ap.parse_args()

    start = time.time()
    rconn = duckdb.connect(DB_PATH, read_only=True)
    pconn = duckdb.connect(config={'memory_limit': '2GB'})

    if args.matrix:
        codes = [c.strip() for c in args.matrix.split(",") if c.strip()]
    else:
        codes = [r[0] for r in rconn.execute(
            "SELECT matrix_code FROM matrices ORDER BY matrix_code").fetchall()]
        codes = [c for c in codes
                 if os.path.exists(CORPUS_PARQUET_DIR / f"{c}.parquet")]

    print(f"Profiling {len(codes)} datasets...")
    records, errors = [], 0
    for i, code in enumerate(codes, 1):
        if i % PROGRESS_INTERVAL == 0:
            print(f"  [{i}/{len(codes)}] {time.time() - start:.1f}s", flush=True)
        try:
            records += profile_matrix(rconn, pconn, code)
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  ERROR on {code}: {e}")

    print(f"\nProfiled {len(records)} dimensions in {time.time() - start:.1f}s "
          f"({errors} errors)")
    if args.dry_run:
        multi = [r for r in records if r['confidence'] == 'verified' and r['n_levels'] >= 2]
        print(f"[DRY-RUN] {len(multi)} multi-level dims; nothing written")
        for r in multi[:15]:
            print(f"  {r['matrix_code']}.{r['dim_column']} [{r['source']}] "
                  f"{[(l['level_id'], l['n']) for l in r['levels']]} "
                  f"default={r['default_level']}")
        return

    rconn.close()
    wconn, is_main = open_write_conn()
    if args.all or args.matrix is None:
        wconn.execute(f"DROP TABLE IF EXISTS {TABLE}")
    wconn.execute(DDL.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS"))
    if args.matrix:
        wconn.execute(
            f"DELETE FROM {TABLE} WHERE matrix_code IN "
            f"({', '.join('?' for _ in codes)})", codes)

    placeholders = ", ".join("?" for _ in COLS)
    insert = f"INSERT INTO {TABLE} ({', '.join(COLS)}) VALUES ({placeholders})"
    for rec in records:
        wconn.execute(insert, to_row(rec))

    print_summary(wconn)
    if args.validate:
        validate(wconn, pconn)
    if not is_main:
        print(f"\n*** Results in {FALLBACK_DB} (main DB was locked). "
              f"Merge with ATTACH + INSERT. ***")
    pconn.close()
    wconn.close()


if __name__ == "__main__":
    main()
