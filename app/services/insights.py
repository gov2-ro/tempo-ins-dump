"""Per-dataset insights: KPI headline values + template-based sentences.

Computed lazily (the metadata endpoint stays parquet-scan-free) and cached
with a TTL like headlines.py. All queries go through query_builder /
dashboard_composer slice rules, so totals pinning, whitespace variants and
SDMX time values behave exactly like the dashboard tiles.
"""
import json
import time
import logging

from app.config import PARQUET_DIR
from app.db import get_conn
from app.services.chart_selector import TOTAL_RE as _TOTAL_RE
from app.services.dataset_meta import get_dataset_meta, _parquet_dim_values
from app.services.dashboard_composer import (
    _build_slice, _effective, _total_entry, primary_time_dim, spec_decision)
from app.services import aggregation_policy as ap
from app.services.query_builder import (
    build_data_query, resolve_parquet_schema, adapt_to_parquet)
from app.services import dimension_structure as dstruct

log = logging.getLogger(__name__)

_cache: dict = {}
CACHE_TTL = 3600
CACHE_MAX = 512

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
    # One shared non-additive policy (aggregation_policy); the aggregate
    # function comes from the decision, never from a local unit list.
    non_additive = ap.is_non_additive_unit(unit_type)
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
    # Every number below goes through the shared aggregation decision (the
    # same one the composer tiles use). When it refuses, the KPIs are
    # withheld and the reason is reported under `suppressed`, never replaced
    # by an unverified sum.
    suppressed = []
    period_totals = []
    pinned_context = []
    decision = None
    if time_dim:
        spec = _build_slice({'x_axis': time_dim['dim_column_name']},
                            dimensions, time_dim,
                            actual_values=actual_values,
                            non_additive=non_additive, struct=struct)
        decision = spec_decision(spec, dimensions, actual_values, struct,
                                 non_additive)
        if decision.available:
            rows = _fetch_slice(conn, matrix_code, dimensions, spec,
                                decision.agg_func or 'SUM', schema)
            period_totals = sorted(
                [(str(r[0]), r[1]) for r in rows
                 if r[0] is not None and r[1] is not None])
            # An arbitrary pin is not a headline. When some dimension has no
            # total and no verified partition the composer holds it at one
            # option, so the series is *a* slice, not the dataset — CON111D
            # would otherwise headline "02 Silvicultura" on two dims at once.
            # The number and both of its changes inherit that pin, so all go.
            # (A level restriction is not a pin: it keeps every option of one
            # grain, so the value is complete.)
            pinned_context = [
                str(spec['filters'][a['column']][0]).strip()
                for a in decision.dimensions if a['treatment'] == 'pinned_value']
            if pinned_context:
                suppressed.append({'key': 'latest', 'outcome': ap.UNAVAILABLE,
                                   'reason': 'arbitrary_pin', 'column': None})
                period_totals = []
        else:
            suppressed.append({'key': 'latest', 'outcome': decision.outcome,
                               'reason': decision.reason,
                               'column': decision.blocking_dimension})

    if period_totals:
        latest_p, latest_v = period_totals[-1]
        first = period_totals[0]
        period = _period_label(latest_p)

        def _prov(comparison=None):
            return ap.provenance(decision, source_code=matrix_code, period=period,
                                 unit=unit_label, comparison=comparison)

        kpis.append({
            'key': 'latest', 'label': tr['latest'],
            'value': latest_v, 'period': period,
            'unit': unit_label, 'format': 'number',
            'context': pinned_context,
            'sparkline': [v for _, v in period_totals[-12:]],
            'provenance': _prov(),
        })

        # Headline change: same period last year for sub-annual data, else the
        # previous point. Zero/missing comparators are reported, not divided.
        change = ap.compute_change(period_totals)
        if change['status'] == 'ok':
            pct = change['value']
            sub_annual = change['basis'] == 'yoy' and \
                period_totals[-2][0] != change['from_period']
            kpis.append({'key': 'yoy',
                         'label': tr['yoy_year'] if change['basis'] == 'yoy' else tr['yoy'],
                         'value': pct, 'format': 'pct',
                         'direction': 'up' if pct >= 0 else 'down',
                         'provenance': _prov(ap.comparison_of(change))})
            tmpl = tr['s_up'] if pct >= 0 else tr['s_down']
            s_yoy = tmpl.format(pct=_fmt(abs(pct), lang),
                                prev=_period_label(change['from_period']))
            if sub_annual:
                # Secondary card: previous period (MoM/QoQ).
                step = ap.compute_change(period_totals, prefer_yoy=False)
                if step['status'] == 'ok':
                    kpis.append({'key': 'prev', 'label': tr['yoy'],
                                 'value': step['value'], 'format': 'pct',
                                 'direction': 'up' if step['value'] >= 0 else 'down',
                                 'provenance': _prov(ap.comparison_of(step))})
                else:
                    suppressed.append({'key': 'prev', 'outcome': ap.UNAVAILABLE,
                                       'reason': step['reason'], 'column': None})
        else:
            suppressed.append({'key': 'yoy', 'outcome': ap.UNAVAILABLE,
                               'reason': change['reason'], 'column': None})

        if len(period_totals) >= 3:
            overall = ap.compute_change_against(
                latest_p, latest_v, first[0], first[1], 'since_first')
            if overall['status'] == 'ok':
                pct = overall['value']
                kpis.append({'key': 'overall', 'label': tr['overall'], 'value': pct,
                             'format': 'pct',
                             'direction': 'up' if pct >= 0 else 'down',
                             'since': _period_label(first[0]),
                             'provenance': _prov(ap.comparison_of(overall))})
            else:
                suppressed.append({'key': 'overall', 'outcome': ap.UNAVAILABLE,
                                   'reason': overall['reason'], 'column': None})

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
        rank_decision = spec_decision(spec, dimensions, actual_values, struct,
                                      non_additive)
        if rank_decision.available:
            rows = _fetch_slice(conn, matrix_code, dimensions, spec,
                                rank_decision.agg_func or 'SUM', schema)
        else:
            rows = []
            suppressed.append({'key': 'ranking', 'outcome': rank_decision.outcome,
                               'reason': rank_decision.reason,
                               'column': rank_decision.blocking_dimension})
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
    data = {'kpis': kpis, 'sentences': sentences[:3], 'notables': notables,
            'suppressed': suppressed}

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
