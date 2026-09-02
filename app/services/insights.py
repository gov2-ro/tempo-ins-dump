"""Per-dataset insights: KPI headline values + template-based sentences.

Computed lazily (the metadata endpoint stays parquet-scan-free) and cached
with a TTL like headlines.py. All queries go through query_builder /
dashboard_composer slice rules, so totals pinning, whitespace variants and
SDMX time values behave exactly like the dashboard tiles.
"""
import json
import re
import time
import logging

from app.config import PARQUET_DIR
from app.db import get_conn
from app.services.chart_selector import TOTAL_RE as _TOTAL_RE
from app.services.dataset_meta import get_dataset_meta, _parquet_dim_values
from app.services.dashboard_composer import (
    _build_slice, _effective, _total_entry, primary_time_dim,
    NON_ADDITIVE_UNIT_TYPES)
from app.services.query_builder import (
    build_data_query, resolve_parquet_schema, adapt_to_parquet)
from app.services import dimension_structure as dstruct

log = logging.getLogger(__name__)

_cache: dict = {}
CACHE_TTL = 3600
CACHE_MAX = 512

# SDMX-normalized periods: "2025" (annual) or "2025-03" / "2025-Q1" (sub-annual)
_PERIOD_RE = re.compile(r'^(\d{4})(-.+)?$')

T = {
    'ro': {
        'latest': 'Ultima valoare',
        'yoy': 'Față de perioada anterioară',
        'yoy_year': 'Față de anul anterior',
        'overall': 'Schimbare totală',
        'trend': 'Tendință',
        'coverage': 'Acoperire',
        'trend_badge': {'increasing': 'în creștere', 'decreasing': 'în scădere',
                        'flat': 'stabilă', 'volatile': 'volatilă'},
        's_up': 'A crescut cu {pct}% față de {prev}.',
        's_down': 'A scăzut cu {pct}% față de {prev}.',
        's_overall_up': 'Din {first} până în {last}, valoarea a crescut cu {pct}%.',
        's_overall_down': 'Din {first} până în {last}, valoarea a scăzut cu {pct}%.',
        's_geo': '{top} are cea mai ridicată valoare ({top_val}); {bottom} — cea mai scăzută ({bottom_val}).',
        's_break': 'Schimbare de tendință în {years}.',
        's_break_many': 'Schimbări de tendință în {years}.',
        's_top_cat': '„{top}" are cea mai mare valoare ({top_val}).',
    },
    'en': {
        'latest': 'Latest value',
        'yoy': 'vs. previous period',
        'yoy_year': 'vs. previous year',
        'overall': 'Overall change',
        'trend': 'Trend',
        'coverage': 'Coverage',
        'trend_badge': {'increasing': 'increasing', 'decreasing': 'decreasing',
                        'flat': 'flat', 'volatile': 'volatile'},
        's_up': 'Up {pct}% vs. {prev}.',
        's_down': 'Down {pct}% vs. {prev}.',
        's_overall_up': 'From {first} to {last}, the value grew by {pct}%.',
        's_overall_down': 'From {first} to {last}, the value fell by {pct}%.',
        's_geo': '{top} has the highest value ({top_val}); {bottom} the lowest ({bottom_val}).',
        's_break': 'Trend change in {years}.',
        's_break_many': 'Trend changes in {years}.',
        's_top_cat': '"{top}" has the largest value ({top_val}).',
    },
}


def _fmt(v, lang='ro'):
    """Compact human number: 1.234.567 (ro) / 1,234,567 (en)."""
    if v is None:
        return '—'
    if abs(v) >= 100 or v == int(v):
        s = f"{v:,.0f}"
    else:
        s = f"{v:,.1f}"
    if lang == 'ro':
        s = s.replace(',', '§').replace('.', ',').replace('§', '.')
    return s


def _period_label(p):
    return str(p).replace('Anul ', '').strip() if p is not None else None


def _seasonal_prev(period_totals: list, latest_p: str):
    """(period, value) for the same sub-period one year earlier, or None.

    For monthly/quarterly data, comparing the last two periods is MoM/QoQ —
    the honest year-over-year comparison is against the same month/quarter
    of the previous year ("2025-03" → "2024-03"). Annual periods (no
    sub-part) and non-SDMX labels return None.
    """
    m = _PERIOD_RE.match(str(latest_p).strip())
    if not m or not m.group(2):
        return None
    target = f"{int(m.group(1)) - 1}{m.group(2)}"
    for p, v in period_totals:
        if p == target:
            return p, v
    return None


def _fetch_slice(conn, matrix_code, dimensions, spec, agg_func, schema=None):
    """Run one composed slice (filters are data-grounded by the composer).

    The composer names dimensions in SDMX terms; 188 parquets are still v2
    and name them `*_nom_id` with a `value` column. Without this translation
    every one of those datasets logged a Binder Error here and fell back to a
    single coverage KPI with no headline and no sentences.
    """
    schema = schema or resolve_parquet_schema(conn, matrix_code)
    dims, group_by, filters = adapt_to_parquet(
        schema, dimensions, spec['group_by'], spec.get('filters', {}))
    sql = build_data_query(matrix_code, dims, filters, 50000,
                           group_by=group_by, agg_func=agg_func,
                           value_column=schema['value_column'])
    try:
        return conn.execute(sql).fetchall()
    except Exception as e:
        log.warning("Insights slice failed for %s: %s", matrix_code, e)
        return []


def _mixes_units(dimensions, spec, actual_values) -> bool:
    """Does this slice add together more than one unit of measure?

    PMI113A spans tonnes, thousand lei and lei per tonne; summing them gives
    2.3 billion of nothing. dim_type alone does not identify the unit column
    there — it classifies UNIT_MEASURE as an indicator — so the canonical
    name counts too. Rare in practice: 74 datasets have such a slice and all
    but 4 are already suppressed for another reason.
    """
    filters = spec.get('filters') or {}
    for d in dimensions:
        col = d['dim_column_name']
        if d.get('dim_type') != 'unit' and col != 'UNIT_MEASURE':
            continue
        picked = filters.get(col)
        n = len(picked) if picked else len(actual_values.get(col)
                                           or d.get('options') or [])
        if n > 1:
            return True
    return False


def compute_insights(matrix_code: str, lang: str = 'ro') -> dict | None:
    now = time.time()
    key = f"{matrix_code}_{lang}"
    hit = _cache.get(key)
    if hit and now - hit['ts'] < CACHE_TTL:
        return hit['data']

    meta = get_dataset_meta(matrix_code, lang=lang)
    if meta is None:
        return None

    conn = get_conn()
    dimensions = meta['dimensions']
    profile = meta.get('profile') or {}
    cfg = meta.get('chart_config') or {}
    tr = T[lang if lang in T else 'ro']

    unit_type = cfg.get('primary_unit_type') or 'count'
    agg_func = 'AVG' if unit_type in ('percentage', 'time_unit') else 'SUM'
    non_additive = unit_type in NON_ADDITIVE_UNIT_TYPES
    actual_values = _parquet_dim_values(conn, matrix_code, dimensions)
    # Same level/aggregate rules the tiles use, or the headline number and
    # the hero chart disagree about the same dataset.
    struct = dstruct.load(conn, matrix_code)
    schema = resolve_parquet_schema(conn, matrix_code)

    time_dim = primary_time_dim(dimensions)
    geo_dim = next((d for d in dimensions if d['dim_type'] == 'geo'), None)
    unit_dim = next((d for d in dimensions if d['dim_type'] == 'unit'), None)
    unit_label = (unit_dim['options'][0]['label']
                  if unit_dim and unit_dim.get('options') else '')

    trend_row = _fetch_row(conn, 'dataset_trends', matrix_code)
    coverage_row = _fetch_row(conn, 'dataset_coverage', matrix_code)

    kpis = []
    # Sentence slots, assembled in priority order at the end. The overall
    # change is a KPI card only — repeating it as a sentence wastes a slot.
    s_yoy = s_geo = s_break = None

    # ---- national/total series over time -----------------------------------
    period_totals = []
    pinned_context = []
    mixed_units = False
    if time_dim:
        spec = _build_slice({'x_axis': time_dim['dim_column_name']},
                            dimensions, time_dim,
                            actual_values=actual_values,
                            non_additive=non_additive, struct=struct)
        rows = _fetch_slice(conn, matrix_code, dimensions, spec, agg_func, schema)
        mixed_units = _mixes_units(dimensions, spec, actual_values)
        period_totals = sorted(
            [(str(r[0]), r[1]) for r in rows if r[0] is not None and r[1] is not None])
        # Pins to a non-total option (data has no aggregate) make the series
        # partial — say so on the KPI card instead of presenting a "Masculin"
        # average as the dataset's headline value.
        #
        # A level restriction is not a pin: it keeps every option of one
        # grain, so the value is complete and naming its first member
        # ("0- 4 ani", "Cluj") would misdescribe a national total.
        for d in dimensions:
            if d.get('dim_type') in ('time', 'unit'):
                continue
            col = d['dim_column_name']
            vals = spec.get('filters', {}).get(col)
            if not vals or len(vals) > 1 or dstruct.is_multi_level(struct, col):
                continue
            if not _TOTAL_RE.match(str(vals[0]).strip()):
                pinned_context.append(str(vals[0]).strip())

    # An arbitrary pin is not a headline. When some dimension has no total and
    # no verified partition, the composer holds it at one option so the series
    # is *a* slice, not the dataset — CON111D would otherwise headline
    # "02 Silvicultura" on two dims at once. The number, its period-on-period
    # change and its overall change all inherit that pin, so all three go.
    if pinned_context or mixed_units:
        period_totals = []

    if period_totals:
        latest_p, latest_v = period_totals[-1]
        prev = period_totals[-2] if len(period_totals) > 1 else None
        first = period_totals[0]

        kpis.append({
            'key': 'latest', 'label': tr['latest'],
            'value': latest_v, 'period': _period_label(latest_p),
            'unit': unit_label, 'format': 'number',
            'context': pinned_context,
            'sparkline': [v for _, v in period_totals[-12:]],
        })

        seasonal = _seasonal_prev(period_totals, latest_p)
        if seasonal and seasonal[1]:
            # Sub-annual data: headline change = same period last year;
            # the previous-period change (MoM/QoQ) is a secondary card.
            pct = round((latest_v - seasonal[1]) / abs(seasonal[1]) * 100, 1)
            kpis.append({'key': 'yoy', 'label': tr['yoy_year'], 'value': pct,
                         'format': 'pct', 'direction': 'up' if pct >= 0 else 'down'})
            tmpl = tr['s_up'] if pct >= 0 else tr['s_down']
            s_yoy = tmpl.format(pct=_fmt(abs(pct), lang),
                                prev=_period_label(seasonal[0]))
            if prev and prev[1]:
                pct2 = round((latest_v - prev[1]) / abs(prev[1]) * 100, 1)
                kpis.append({'key': 'prev', 'label': tr['yoy'], 'value': pct2,
                             'format': 'pct',
                             'direction': 'up' if pct2 >= 0 else 'down'})
        elif prev and prev[1]:
            pct = round((latest_v - prev[1]) / abs(prev[1]) * 100, 1)
            kpis.append({'key': 'yoy', 'label': tr['yoy'], 'value': pct,
                         'format': 'pct', 'direction': 'up' if pct >= 0 else 'down'})
            tmpl = tr['s_up'] if pct >= 0 else tr['s_down']
            s_yoy = tmpl.format(pct=_fmt(abs(pct), lang),
                                prev=_period_label(prev[0]))

        if len(period_totals) >= 3 and first[1]:
            pct = round((latest_v - first[1]) / abs(first[1]) * 100, 1)
            overall_dir = 'up' if pct >= 0 else 'down'
            kpis.append({'key': 'overall', 'label': tr['overall'], 'value': pct,
                         'format': 'pct', 'direction': overall_dir,
                         'since': _period_label(first[0])})

    # ---- trend badge --------------------------------------------------------
    # Only when it adds signal beyond the overall-change card: volatile/flat
    # always, increasing/decreasing only if they contradict the overall % (a
    # "în creștere" badge next to "+865%" is noise).
    direction = (trend_row or {}).get('trend_direction')
    overall_dir = next((k['direction'] for k in kpis if k['key'] == 'overall'), None)
    redundant = (direction == 'increasing' and overall_dir == 'up') or \
                (direction == 'decreasing' and overall_dir == 'down')
    if direction and direction in tr['trend_badge'] and not redundant:
        kpis.append({'key': 'trend', 'label': tr['trend'],
                     'badge': direction, 'badge_label': tr['trend_badge'][direction]})

    # ---- coverage -----------------------------------------------------------
    y0, y1 = profile.get('time_year_min'), profile.get('time_year_max')
    if y0 and y1:
        parts = [f"{y0}–{y1}"]
        geo_n = (coverage_row or {}).get('geo_county_count')
        if geo_n:
            parts.append(f"{geo_n} {'județe' if lang == 'ro' else 'counties'}")
        kpis.append({'key': 'coverage', 'label': tr['coverage'],
                     'value': ' · '.join(parts),
                     'fill_rate': (coverage_row or {}).get('fill_rate')})

    # ---- breakpoints ---------------------------------------------------------
    breaks = (trend_row or {}).get('breakpoint_years')
    try:
        breaks = json.loads(breaks) if isinstance(breaks, str) else (breaks or [])
    except (json.JSONDecodeError, TypeError):
        breaks = []
    if breaks:
        years = ', '.join(str(y) for y in breaks[:3])
        s_break = (tr['s_break'] if len(breaks) == 1
                   else tr['s_break_many']).format(years=years)

    # ---- top/bottom geo (or top category) -----------------------------------
    # Also emitted as structured `notables` — actionable slices the frontend
    # renders as clickable chips (values are exact data strings, so applying
    # them as filters always matches).
    notables = []
    rank_dim = geo_dim or _largest_cat_dim(dimensions)
    if rank_dim:
        spec = _build_slice({'x_axis': rank_dim['dim_column_name']},
                            dimensions, time_dim, 'horizontal_bar',
                            actual_values, non_additive, struct)
        rows = _fetch_slice(conn, matrix_code, dimensions, spec, agg_func, schema)
        exclude = _aggregate_labels(rank_dim)
        ranked = sorted(
            [(str(r[0]), r[1]) for r in rows
             if r[0] is not None and r[1] is not None
             and str(r[0]).strip() not in exclude],
            key=lambda x: x[1], reverse=True)
        if len(ranked) >= 3:
            top, bottom = ranked[0], ranked[-1]
            col = rank_dim['dim_column_name']
            notables.append({'type': 'top', 'column': col, 'value': top[0],
                             'label': top[0].strip(),
                             'amount': _fmt(top[1], lang)})
            if geo_dim:
                notables.append({'type': 'bottom', 'column': col,
                                 'value': bottom[0], 'label': bottom[0].strip(),
                                 'amount': _fmt(bottom[1], lang)})
                s_geo = tr['s_geo'].format(
                    top=top[0], top_val=_fmt(top[1], lang),
                    bottom=bottom[0], bottom_val=_fmt(bottom[1], lang))
            else:
                s_geo = tr['s_top_cat'].format(
                    top=top[0].strip(), top_val=_fmt(top[1], lang))

    sentences = [s for s in (s_yoy, s_geo, s_break) if s]
    data = {'kpis': kpis, 'sentences': sentences[:3], 'notables': notables}

    if len(_cache) > CACHE_MAX:
        _cache.clear()
    _cache[key] = {'data': data, 'ts': now}
    return data


def _fetch_row(conn, table, matrix_code):
    row = conn.execute(f"SELECT * FROM {table} WHERE matrix_code = ?",
                       [matrix_code]).fetchone()
    if not row:
        return {}
    cols = [d[0] for d in conn.execute(f"DESCRIBE {table}").fetchall()]
    return dict(zip(cols, row))


def _largest_cat_dim(dimensions):
    cats = [d for d in dimensions if d['dim_type'] == 'indicator'
            and 3 <= (d.get('option_count') or 0) <= 60]
    return max(cats, key=lambda d: d.get('option_count') or 0, default=None)


def _aggregate_labels(dim) -> set:
    """Trimmed labels of total/aggregate options to drop from rankings.

    For geo dims, only the most granular level present is ranked — mixing
    counties with their region/macroregion aggregates would be misleading.
    """
    out = set()
    total = _total_entry(dim, _effective(dim, None))
    if total:
        out.add((total[0].get('label') or '').strip())

    levels = {}
    for o in dim.get('options', []):
        lvl = (o.get('parsed') or {}).get('geo_level')
        if lvl:
            levels.setdefault(lvl, []).append((o.get('label') or '').strip())

    keep = next((lvl for lvl in ('county', 'region', 'macroregion')
                 if lvl in levels), None)
    for lvl, labels in levels.items():
        if lvl != keep:
            out.update(labels)

    for o in dim.get('options', []):
        lbl = (o.get('label') or '').strip()
        if _TOTAL_RE.match(lbl):
            out.add(lbl)
    return out
