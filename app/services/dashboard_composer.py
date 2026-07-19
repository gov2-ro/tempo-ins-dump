"""Dashboard composition engine.

Arranges the chart_selector's ranked charts into a dashboard recipe: which
1-4 charts to render simultaneously, in which layout slots, each with a
declarative data-slice spec the frontend can fetch independently.

Selection stays in chart_selector (single source of ranking); this module
only *composes*. Charts are picked for information-axis diversity — at most
one chart per axis (temporal / spatial / ranking / structural) so each tile
answers a different question about the dataset.

Slices are grounded in the parquet's *actual* values (`actual_values`):
metadata routinely lists options the data lacks (Total rows, whole
categories), so pinning by metadata alone yields empty charts.
"""
import hashlib
import json
import re

from app.services.chart_selector import TOTAL_RE

# "Taurine - total" style aggregate options inside hierarchical dims
_TOTAL_SUFFIX_RE = re.compile(r'-\s*total\s*$', re.I)


# Information axis per chart type. bar_vertical is resolved dynamically
# (temporal when its x-axis is the time dim, ranking otherwise).
CHART_AXIS = {
    'line': 'temporal',
    'area_stacked': 'temporal',
    'small_multiples': 'temporal',
    'choropleth': 'spatial',
    'horizontal_bar': 'ranking',
    'population_pyramid': 'structural',
    'grouped_bar': 'structural',
    'stacked_bar': 'structural',
    'heatmap': 'structural',
}

# Desired companion axes per hero axis, in priority order. Used to
# synthesize a missing companion when no ranked candidate qualified.
COMPANION_AXES = {
    'spatial': ['temporal', 'ranking'],
    'structural': ['temporal', 'ranking'],
    'ranking': ['temporal'],
    'temporal': ['ranking'],
}

# Unit types whose values cannot be SUMmed across an unpinned dimension
# (means, shares, rates, base-100 indices; currency datasets are
# predominantly per-capita/monthly averages in TEMPO).
NON_ADDITIVE_UNIT_TYPES = {'currency', 'percentage', 'rate', 'ratio',
                           'index', 'time_unit'}

# A categorical dim needs at least this many real options to make a
# ranking bar worth a tile.
MIN_RANKING_OPTIONS = 6

LAYOUTS = {1: 'single_full', 2: 'hero_side', 3: 'hero_2side', 4: 'hero_2side_full'}
SLOTS = {
    1: ['full'],
    2: ['hero', 'side'],
    3: ['hero', 'side', 'side'],
    4: ['hero', 'side', 'side', 'full'],
}

# Dense overview charts: useful context, poor leads — never the hero, and
# they need horizontal room (a 68-column heatmap in a side tile is noise),
# so they're ordered last and given the full-width slot.
NON_HERO_CHARTS = {'heatmap'}
WIDE_CHARTS = {'heatmap'}
LAYOUTS_WIDE = {2: 'hero_full', 3: 'hero_side_full', 4: 'hero_2side_full'}
SLOTS_WIDE = {
    2: ['hero', 'full'],
    3: ['hero', 'side', 'full'],
    4: ['hero', 'side', 'side', 'full'],
}

MIN_SCORE = 0.5
MAX_CHARTS = 4

AXIS_TITLE_HINTS = {
    'temporal': 'evolution',
    'spatial': 'map',
    'ranking': 'ranking',
    'structural': 'structure',
}

# Single total-detection regex lives in chart_selector (mirrors filter-panel.js)
_TOTAL_RE = TOTAL_RE


def _col(dim):
    return dim['dim_column_name']


def primary_time_dim(dimensions):
    """The real time axis — with two time dims (reference + base year for
    indices), it's the one with the most periods. Mirrors assign_roles()."""
    time_dims = [d for d in dimensions if d.get('dim_type') == 'time']
    return max(time_dims, key=lambda d: d.get('option_count') or 0, default=None)


def _effective(dim, actual_values) -> list[tuple[dict, str | None]]:
    """(option, data_value) pairs for the options actually present in the
    parquet. data_value is the exact stored string — filters built from it
    always match. When data reality is unknown (no parquet / legacy schema)
    every metadata option is returned with data_value=None and filters fall
    back to label+trimmed variants.

    Legacy parquets store label strings with whitespace padding the metadata
    lacks (" Anul 2023" vs "Anul 2023") — a trimmed-spelling fallback covers
    those, but only when the trimmed form is unambiguous on BOTH sides
    (hierarchical dims encode depth in indentation, so " Masculi" and
    "  Masculi" can be different options).
    """
    opts = dim.get('options', [])
    vals = (actual_values or {}).get(_col(dim))
    if not vals:
        return [(o, None) for o in opts]

    trimmed_vals: dict = {}
    for v in vals:
        trimmed_vals.setdefault(str(v).strip(), set()).add(v)
    label_counts: dict = {}
    for o in opts:
        t = (o.get('label') or '').strip()
        label_counts[t] = label_counts.get(t, 0) + 1

    eff = []
    for o in opts:
        matched = None
        for cand in (o.get('sdmx_value'), o.get('label'),
                     (o.get('label') or '').strip()):
            if cand and cand in vals:
                matched = cand
                break
        if matched is None:
            t = (o.get('label') or '').strip()
            tv = trimmed_vals.get(t)
            if tv and len(tv) == 1 and label_counts.get(t, 0) == 1:
                matched = next(iter(tv))
        if matched is not None:
            eff.append((o, matched))
    # Metadata/parquet naming drift — better to trust metadata than to
    # silently treat the dim as absent.
    return eff or [(o, None) for o in opts]


def _total_entry(dim, effective) -> tuple[dict, str | None] | None:
    """The total/aggregate option of a dimension, restricted to options
    that exist in the data."""
    if dim.get('dim_type') == 'geo':
        for o, v in effective:
            if (o.get('parsed') or {}).get('geo_level') == 'national':
                return o, v
    for o, v in effective:
        if _TOTAL_RE.match((o.get('label') or '').strip()):
            return o, v
    return None


def _pin_values(dim, opt, data_value) -> list[str]:
    """Filter values that pin a dimension to one option.

    With a known data value the filter is exact. Otherwise fall back to the
    metadata label plus its trimmed variant (labels may carry indentation
    whitespace the parquet lacks), unless trimming collides with a
    different option.
    """
    if data_value is not None:
        return [data_value]
    lbl = opt.get('label') or ''
    values = [lbl]
    trimmed = lbl.strip()
    all_labels = {(o.get('label') or '') for o in dim.get('options', [])}
    if trimmed != lbl and trimmed not in all_labels:
        values.append(trimmed)
    return values


def _latest_time_entry(time_dim, effective) -> tuple[dict, str | None] | None:
    """(option, data_value) of the most recent period present in the data."""
    best, best_key = None, None
    for o, v in effective:
        p = o.get('parsed') or {}
        year = p.get('year')
        if year is None:
            continue
        sub = p.get('month') or ((p.get('quarter') or 0) * 3) or 12
        key = (year, sub)
        if best_key is None or key > best_key:
            best, best_key = (o, v), key
    if best is None and effective:
        best = effective[-1]
    return best


def _time_pin_values(entry) -> list[str]:
    """Filter values for a time pin. With a known data value the pin is
    exact; otherwise (legacy parquet, no actual_values) send every known
    spelling — SDMX value ("2023") AND label variants (" Anul 2023") — so
    the filter matches whichever format the file stores."""
    opt, v = entry
    if v is not None:
        return [v]
    vals = [x for x in (opt.get('sdmx_value'), opt.get('label'),
                        (opt.get('label') or '').strip()) if x]
    return list(dict.fromkeys(vals))


def _latest_time_value(time_dim, effective) -> str | None:
    """Single best filter value of the most recent period (for defaults).

    SDMX-canonical parquets store TIME_PERIOD as normalized values
    ("2023", "2023-Q1"), not the RO labels ("Anul 2023") — prefer the
    option's data/sdmx value for filter matching.
    """
    entry = _latest_time_entry(time_dim, effective)
    if entry is None:
        return None
    opt, v = entry
    return v or opt.get('sdmx_value') or opt['label']


def _non_total_options(dim, actual_values) -> list:
    eff = _effective(dim, actual_values)
    return [(o, v) for o, v in eff
            if not _TOTAL_RE.match((o.get('label') or '').strip())]


def _hierarchy_root_pin(dim, effective) -> tuple[dict, str | None] | None:
    """Top-level option to pin for dims that hide a hierarchy in their labels.

    INS dims like AGR201E's "Grupe de varsta si destinatie economica" carry
    no parent_id data — the tree lives in label indentation ("  Masculi")
    and "- total" suffixes ("Taurine - total"). Summing ALL options of such
    a dim double-counts every level (10.3M "bovines" vs the real 1.9M).
    Returns the first top-level aggregate to pin, or None for flat dims
    (where summing options genuinely equals the total).
    """
    labels = [(o.get('label') or '') for o, _ in effective]
    has_indent = any(l != l.lstrip() for l in labels)
    has_total_suffix = any(_TOTAL_SUFFIX_RE.search(l.strip()) for l in labels)
    if not (has_indent or has_total_suffix):
        return None
    top = [(o, v) for o, v in effective
           if (o.get('label') or '') == (o.get('label') or '').lstrip()]
    if not top:
        return None
    for o, v in top:
        if _TOTAL_SUFFIX_RE.search((o.get('label') or '').strip()):
            return o, v
    if has_indent:
        return top[0]
    return None


def _widest_pin(dim, effective, actual_values) -> tuple[dict, str | None]:
    """The option covering the most parquet rows.

    A forced pin (non-additive dim without a Total) should at least
    represent the dataset's densest slice, not whatever option happens to
    be listed first. actual_values may carry per-value row counts; without
    them, fall back to the first option (ties keep first-listed order).
    """
    counts = (actual_values or {}).get(_col(dim))
    if isinstance(counts, dict):
        return max(effective, key=lambda ov: counts.get(ov[1], 0))
    return effective[0]


def _arbitrary_pin_count(series_col: str, dimensions: list, time_col: str | None,
                         actual_values: dict | None, non_additive: bool) -> int:
    """How many dims a [time × series] slice would pin to an arbitrary
    non-total option (no Total in the data, values not summable)."""
    n = 0
    for d in dimensions:
        c = _col(d)
        if c in (series_col, time_col) or d.get('dim_type') in ('time', 'unit'):
            continue
        eff = _effective(d, actual_values)
        if len(eff) <= 1:
            continue
        if _total_entry(d, eff) is None and non_additive:
            n += 1
    return n


# Charts whose series is a free choice the composer can improve on.
SERIES_RETUNABLE = {'line', 'area_stacked', 'stacked_bar', 'bar_vertical'}


def _best_temporal_series(dimensions: list, time_col: str | None,
                          actual_values: dict | None, non_additive: bool):
    """Most informative series split for the evolution chart.

    assign_roles defaults to gender-first, but a substantive categorical dim
    (ownership, category, …) usually tells a richer story than the M/F split.
    Honesty beats richness though: a candidate that forces *other* dims onto
    arbitrary non-total pins loses to one whose slice stays complete.
    Returns a dimension or None (keep the selector's choice).
    """
    ranked = []
    for d in dimensions:
        if d.get('dim_type') in ('time', 'unit', 'geo'):
            continue
        n = len(_non_total_options(d, actual_values))
        if not (2 <= n <= 8):
            continue
        pins = _arbitrary_pin_count(_col(d), dimensions, time_col,
                                    actual_values, non_additive)
        substantive = d.get('dim_type') not in ('gender', 'residence', 'age')
        ranked.append(((-pins, substantive, n), d))
    if not ranked:
        return None
    ranked.sort(key=lambda t: t[0], reverse=True)
    return ranked[0][1]


def retune_ranked_series(ranked: list[dict], dimensions: list, sig: dict,
                         actual_values: dict | None) -> None:
    """Align ranked_charts' evolution-series defaults with the composer.

    assign_roles defaults to gender-first; the composer overrides that with
    the most informative substantive split for its own tiles
    (_best_temporal_series). Frontends that read ranked_charts directly
    (v1 lens) must get the same default, or the two surfaces tell
    different stories about the same dataset. Mutates entries in place.
    """
    non_additive = sig.get('primary_unit_type') in NON_ADDITIVE_UNIT_TYPES
    time_dim = primary_time_dim(dimensions)
    if time_dim is None:
        return
    time_col = _col(time_dim)
    geo_dim = next((d for d in dimensions if d.get('dim_type') == 'geo'), None)
    geo_col = _col(geo_dim) if geo_dim else None
    best = _best_temporal_series(dimensions, time_col, actual_values, non_additive)
    if best is None:
        return
    for entry in ranked:
        roles = entry.get('roles') or {}
        axis = _chart_axis(entry['chart_type'], roles, time_col, geo_col)
        if (entry['chart_type'] in SERIES_RETUNABLE and axis == 'temporal'
                and roles.get('x_axis') == time_col
                and roles.get('series') != _col(best)):
            entry['roles'] = {**roles, 'series': _col(best)}


def _chart_axis(chart_type: str, roles: dict, time_col: str | None,
                geo_col: str | None = None) -> str:
    if chart_type == 'bar_vertical':
        return 'temporal' if time_col and roles.get('x_axis') == time_col else 'ranking'
    if chart_type == 'bubble':
        # Geo bubble is spatial; the no-geo variant is a multi-series time chart
        return 'spatial' if geo_col and roles.get('x_axis') == geo_col else 'temporal'
    return CHART_AXIS.get(chart_type, 'structural')


def _slice_id(group_by: list, filters: dict) -> str:
    key = json.dumps([group_by, filters], sort_keys=True, ensure_ascii=False)
    return hashlib.md5(key.encode('utf-8')).hexdigest()[:10]


# Chart modules with a built-in timeline browser; for any other chart a
# 'timeline' role is dropped from the slice so time gets pinned to the
# latest period instead (their renderers would otherwise sum across years).
TIMELINE_CAPABLE = {'choropleth', 'population_pyramid', 'grouped_bar'}


def _build_slice(roles: dict, dimensions: list, time_dim,
                 chart_type: str | None = None,
                 actual_values: dict | None = None,
                 non_additive: bool = False) -> dict:
    """Declarative data spec for one chart: GROUP BY its role dims, pin every
    other dim to its Total option (avoids double-count sums), pin time to the
    latest period when time is not an axis.

    Pins only use values present in the parquet. When a dim has no Total in
    the data, additive values are left unfiltered (sum = total) while
    non-additive ones (means/rates) get pinned to the first real option —
    the tile chip discloses the pin.
    """
    group_by = []
    slice_roles = ('x_axis', 'series', 'facet', 'timeline') \
        if (chart_type is None or chart_type in TIMELINE_CAPABLE) \
        else ('x_axis', 'series', 'facet')
    for role in slice_roles:
        c = roles.get(role)
        if c and c not in group_by:
            group_by.append(c)

    filters: dict = {}

    for dim in dimensions:
        c = _col(dim)
        if c in group_by:
            continue
        eff = _effective(dim, actual_values)
        if len(eff) <= 1:
            continue  # singleton in the data — nothing to pin
        if dim.get('dim_type') == 'unit':
            # Multi-unit dataset: mixing units in one SUM is meaningless —
            # pin the first unit option.
            opt, val = eff[0]
            filters[c] = _pin_values(dim, opt, val)
            continue
        if dim.get('dim_type') == 'time':
            # Pin time to the latest period only when no time dim is on an
            # axis. With a time axis present, a *secondary* time dim (base
            # year of an index series) is left unfiltered — its coverage
            # windows don't overlap, and pinning would truncate the series.
            has_time_axis = any(
                d2.get('dim_type') == 'time' and _col(d2) in group_by
                for d2 in dimensions)
            if not has_time_axis:
                latest = _latest_time_entry(dim, eff)
                if latest:
                    filters[c] = _time_pin_values(latest)
            continue
        total = _total_entry(dim, eff)
        if total:
            filters[c] = _pin_values(dim, *total)
        elif non_additive:
            opt, val = _widest_pin(dim, eff, actual_values)
            filters[c] = _pin_values(dim, opt, val)
        else:
            # Additive + no total: leaving the dim unfiltered (sum = total)
            # is only honest for flat partitions — label-encoded hierarchies
            # double-count, so pin their top-level aggregate instead.
            root = _hierarchy_root_pin(dim, eff)
            if root:
                filters[c] = _pin_values(dim, *root)

    return {
        'group_by': group_by,
        'filters': filters,
        'slice_id': _slice_id(group_by, filters),
    }


def _tile_controls(spec: dict, dimensions: list, actual_values: dict | None) -> list:
    """One select per pinned dim of a tile — the pin is a default the user
    can change, not a verdict. Options are data-grounded; values match the
    slice filter values exactly."""
    controls = []
    for dim in dimensions:
        c = _col(dim)
        if c not in spec['filters']:
            continue
        eff = _effective(dim, actual_values)
        if len(eff) <= 1:
            continue
        options = [{'label': (o.get('label') or '').strip(),
                    'value': v if v is not None else o.get('label')}
                   for o, v in eff]
        if dim.get('dim_type') == 'time':
            options = list(reversed(options))  # newest first
        controls.append({
            'column': c,
            'label': (dim.get('dim_label') or '').strip(),
            'dim_type': dim.get('dim_type'),
            'options': options,
            'default': spec['filters'][c][0],
        })
    return controls


def _annotations_for(axis: str, group_by: list, time_col: str | None, trend: dict) -> list:
    """Zero-cost annotations from precomputed dataset_trends signals."""
    anns = []
    if not trend:
        return anns

    def _json_list(key):
        raw = trend.get(key)
        if not raw:
            return []
        try:
            vals = json.loads(raw) if isinstance(raw, str) else raw
            return vals if isinstance(vals, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    if axis == 'temporal' and time_col in group_by:
        for y in _json_list('breakpoint_years')[:3]:
            anns.append({'type': 'breakpoint', 'year': y})
        peak, trough = trend.get('max_value_year'), trend.get('min_value_year')
        if peak and peak != trough:
            anns.append({'type': 'peak', 'year': peak})
        if trough and trough != peak:
            anns.append({'type': 'trough', 'year': trough})
    elif axis == 'spatial':
        outliers = _json_list('geo_outlier_counties')
        if outliers:
            anns.append({'type': 'outlier_regions', 'values': outliers})
    return anns


def compose_dashboard(sig: dict, ranked: list[dict], dimensions: list,
                      trend: dict | None = None,
                      actual_values: dict | None = None) -> dict | None:
    """Compose the dashboard recipe from ranked charts (roles pre-assigned).

    actual_values maps dim column → set of values present in the parquet;
    slices and filters are restricted to them so tiles never pin on
    metadata-only options.

    Returns the `composition` block for chart_config, or None when there is
    nothing rankable (frontend falls back to single-chart behaviour).
    """
    trend = trend or {}
    non_additive = sig.get('primary_unit_type') in NON_ADDITIVE_UNIT_TYPES
    time_dim = primary_time_dim(dimensions)
    geo_dim = next((d for d in dimensions if d.get('dim_type') == 'geo'), None)
    time_col = _col(time_dim) if time_dim else None
    geo_col = _col(geo_dim) if geo_dim else None

    candidates = [r for r in ranked
                  if r['chart_type'] != 'table' and r.get('score', 0) >= MIN_SCORE]
    if not candidates:
        candidates = [r for r in ranked if r['chart_type'] != 'table'][:1]
    if not candidates:
        return None

    # Hero + axis-diverse sides. Dense overview charts (heatmap) may rank
    # first but never lead — the hero must be readable at a glance.
    hero = next((r for r in candidates
                 if r['chart_type'] not in NON_HERO_CHARTS), candidates[0])
    picked = [hero]
    hero_axis = _chart_axis(hero['chart_type'],
                            hero.get('roles', {}), time_col, geo_col)
    axes_used = {hero_axis}
    for r in candidates:
        if r is hero:
            continue
        if len(picked) >= MAX_CHARTS:
            break
        axis = _chart_axis(r['chart_type'], r.get('roles', {}), time_col, geo_col)
        if axis not in axes_used:
            picked.append(r)
            axes_used.add(axis)

    charts = []
    for entry in picked:
        chart_type = entry['chart_type']
        roles = entry.get('roles', {})
        # A small_multiples pick without a facet dim degrades to a single
        # panel — render it as the line it actually is (AMG101E case).
        if chart_type == 'small_multiples' and not roles.get('facet'):
            chart_type = 'line'
        # A heatmap needs two axes. With no second categorical, use time as
        # the x axis (cat × time grid — the renderer keeps all periods only
        # when time is x); without time either, the tile can't render.
        if chart_type == 'heatmap' and not roles.get('series'):
            if time_col and (sig.get('time_points') or 0) >= 2:
                roles = {**roles, 'x_axis': time_col, 'series': roles.get('x_axis')}
            else:
                continue
        axis = _chart_axis(chart_type, roles, time_col, geo_col)
        # Evolution charts: swap the selector's gender-first series for the
        # most informative real split (copy — ranked_charts keep their roles).
        if chart_type in SERIES_RETUNABLE and axis == 'temporal' \
                and roles.get('x_axis') == time_col:
            best = _best_temporal_series(dimensions, time_col,
                                         actual_values, non_additive)
            if best is not None and _col(best) != roles.get('series'):
                roles = {**roles, 'series': _col(best)}
        spec = _build_slice(roles, dimensions, time_dim, chart_type,
                            actual_values, non_additive)
        charts.append({
            'id': entry['chart_type'],
            'chart_type': chart_type,
            'axis': axis,
            'title_hint': AXIS_TITLE_HINTS.get(axis, axis),
            'score': entry.get('score'),
            'roles': roles,
            'data': spec,
            'controls': _tile_controls(spec, dimensions, actual_values),
            'annotations': _annotations_for(axis, spec['group_by'], time_col, trend),
        })

    # Synthesize missing companions the hero axis wants
    for want in COMPANION_AXES.get(hero_axis, []):
        if want in axes_used or len(charts) >= MAX_CHARTS:
            continue
        if want == 'temporal' and time_col and (sig.get('time_points') or 0) >= 3:
            roles = {'x_axis': time_col}
            best = _best_temporal_series(dimensions, time_col,
                                         actual_values, non_additive)
            if best is not None:
                roles['series'] = _col(best)
            spec = _build_slice(roles, dimensions, time_dim,
                                actual_values=actual_values,
                                non_additive=non_additive)
            charts.append({
                'id': 'trend',
                'chart_type': 'line',
                'axis': 'temporal',
                'title_hint': AXIS_TITLE_HINTS['temporal'],
                'score': None,
                'synthesized': True,
                'roles': roles,
                'data': spec,
                'controls': _tile_controls(spec, dimensions, actual_values),
                'annotations': _annotations_for('temporal', spec['group_by'],
                                                time_col, trend),
            })
            axes_used.add('temporal')
        elif want == 'ranking':
            # Geo dim first; otherwise the widest real categorical dim —
            # a ranked bar is the readable view of a high-cardinality dim
            # (e.g. 68 CAEN activities) that heatmaps/lines can't show.
            rank_dim = None
            if geo_dim and (sig.get('geo_count') or 0) >= 5:
                rank_dim = geo_dim
            else:
                widest, widest_n = None, 0
                for d in dimensions:
                    if d.get('dim_type') in ('time', 'unit'):
                        continue
                    n = len(_effective(d, actual_values))
                    if n > widest_n:
                        widest, widest_n = d, n
                if widest_n >= MIN_RANKING_OPTIONS:
                    rank_dim = widest
            if rank_dim is None:
                continue
            roles = {'x_axis': _col(rank_dim)}
            spec = _build_slice(roles, dimensions, time_dim, 'horizontal_bar',
                                actual_values, non_additive)
            charts.append({
                'id': 'ranking',
                'chart_type': 'horizontal_bar',
                'axis': 'ranking',
                'title_hint': AXIS_TITLE_HINTS['ranking'],
                'score': None,
                'synthesized': True,
                'roles': roles,
                'data': spec,
                'controls': _tile_controls(spec, dimensions, actual_values),
                'annotations': [],
            })
            axes_used.add('ranking')

    n = min(len(charts), MAX_CHARTS)
    charts = charts[:n]
    wide = [c for c in charts if c['chart_type'] in WIDE_CHARTS]
    if wide and n >= 2:
        charts = [c for c in charts if c not in wide] + wide
        layout, slots = LAYOUTS_WIDE[n], SLOTS_WIDE[n]
    else:
        layout, slots = LAYOUTS[n], SLOTS[n]
    for chart, slot in zip(charts, slots):
        chart['slot'] = slot

    # Dims no chart consumes as an axis → compact filter row. Options are
    # restricted to values present in the data; dims that are singletons in
    # the parquet (whatever metadata claims) get no control at all.
    consumed = {c for ch in charts for c in ch['data']['group_by']}
    filter_dims = []
    for d in dimensions:
        c = _col(d)
        if c in consumed:
            continue
        eff = _effective(d, actual_values)
        if len(eff) <= 1:
            continue
        options = [{'label': (o.get('label') or '').strip(),
                    'value': v if v is not None else o.get('label')}
                   for o, v in eff]
        total = _total_entry(d, eff)
        is_time = d.get('dim_type') == 'time'
        root = None if (total or is_time) else _hierarchy_root_pin(d, eff)
        if total:
            default = total[1] if total[1] is not None else total[0].get('label')
        elif is_time:
            default = _latest_time_value(d, eff)
        elif root:
            # Label-encoded hierarchy: "Toate" would double-count levels —
            # default to the top-level aggregate instead.
            default = root[1] if root[1] is not None else root[0].get('label')
        else:
            default = None if not non_additive and d.get('dim_type') != 'unit' \
                else options[0]['value']
        # "Toate" (unfiltered sum) only makes sense for additive values
        # without an explicit total; units and time never sum meaningfully.
        allow_all = (default is None)
        widget = ('single_select' if len(eff) > 25
                  else 'multi_select' if len(eff) > 6 else 'pill_group')
        filter_dims.append({'column': c, 'label': d.get('dim_label'),
                            'dim_type': d.get('dim_type'), 'widget': widget,
                            'options': options, 'default': default,
                            'allow_all': allow_all})

    # Dims in the global filter row already control every tile — a per-tile
    # select for them would be a duplicate.
    filter_cols = {fd['column'] for fd in filter_dims}
    if filter_cols:
        for ch in charts:
            ch['controls'] = [c for c in ch.get('controls', [])
                              if c['column'] not in filter_cols]

    return {
        'layout': layout,
        'charts': charts,
        'default_filters': {'exclude_total': True, 'time': 'latest'},
        'filter_dims': filter_dims,
    }
