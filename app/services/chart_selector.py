"""
Generic chart selection engine for statistical datasets.

Replaces the hardcoded archetype → chart mapping with a rules-based scoring system.
The 4 existing archetypes (geo_time, demographic, time_residence, time_series) emerge
naturally from the scores — they are no longer hardcoded inputs.

Unit-type awareness: percentage data prefers area_stacked, index/rate data prefers line,
currency/count data is neutral. Confidence scoring tells the frontend how certain we are.
"""
import json


# ---------------------------------------------------------------------------
# Tie-breaking priority: when scores are equal, prefer more specific charts
# Lower number = higher priority
# ---------------------------------------------------------------------------
TIEBREAK_PRIORITY = {
    'choropleth': 0, 'population_pyramid': 1, 'line': 2,
    'area_stacked': 3, 'grouped_bar': 4, 'small_multiples': 5,
    'heatmap': 6, 'stacked_bar': 7, 'horizontal_bar': 8,
    'bar_vertical': 9, 'bubble': 10, 'table': 11,
}

# Chart pairings that are complementary rather than competitive
COMPLEMENTARY_PAIRS = {
    frozenset({'choropleth', 'line'}): 'map shows spatial patterns, line shows time trends',
    frozenset({'choropleth', 'horizontal_bar'}): 'map shows geography, bar ranks values',
    frozenset({'population_pyramid', 'line'}): 'pyramid shows age structure, line shows change over time',
    frozenset({'grouped_bar', 'heatmap'}): 'bar compares groups, heatmap shows all cross-sections',
    frozenset({'line', 'small_multiples'}): 'line shows aggregate trend, small multiples show per-category trends',
}

# ---------------------------------------------------------------------------
# 1. Signature builder — collapses all metadata into one dict
# ---------------------------------------------------------------------------

def build_signature(profile: dict, dimensions: list,
                    coverage: dict | None = None,
                    value_profile: dict | None = None,
                    trend: dict | None = None) -> dict:
    """Build a dataset signature from all available metadata.

    Args:
        profile:       Row from matrix_profiles
        dimensions:    List of dim dicts with dim_type, dim_column_name, option_count
        coverage:      Row from dataset_coverage (optional)
        value_profile: Row from dataset_value_profiles (optional)
        trend:         Row from dataset_trends (optional)
    """
    cov = coverage or {}
    vp = value_profile or {}
    tr = trend or {}

    indicator_dims = [
        {'name': d['dim_column_name'], 'count': d.get('option_count') or 0,
         'has_total': False, 'is_ordered': False}
        for d in dimensions if d.get('dim_type') == 'indicator'
    ]

    geo_levels_raw = profile.get('geo_levels', '[]') or '[]'
    try:
        geo_levels = json.loads(geo_levels_raw) if isinstance(geo_levels_raw, str) else geo_levels_raw
    except (json.JSONDecodeError, TypeError):
        geo_levels = []

    geo_count = cov.get('geo_county_count') or 0
    if geo_count == 0 and profile.get('has_geo'):
        # geo_county_count only tracks counties; for region/macroregion datasets it's 0.
        # Fall back to dimension metadata or known geo level counts.
        if 'county' in geo_levels:
            geo_count = _dim_count(dimensions, 'geo') or 42
        elif 'region' in geo_levels:
            geo_count = _dim_count(dimensions, 'geo') or 8
        elif 'macroregion' in geo_levels:
            geo_count = _dim_count(dimensions, 'geo') or 4
        else:
            geo_count = _dim_count(dimensions, 'geo') or 0

    time_points = cov.get('time_year_count') or profile.get('time_year_max', 0) or 0
    if time_points == 0 and profile.get('time_year_min') and profile.get('time_year_max'):
        time_points = profile['time_year_max'] - profile['time_year_min'] + 1

    coeff_var = vp.get('coeff_variation')
    # cap extreme values from near-zero means
    if coeff_var is not None and abs(coeff_var) > 100:
        coeff_var = 100.0

    # Unit type enrichment
    unit_types_raw = profile.get('unit_types', '[]') or '[]'
    try:
        unit_types = json.loads(unit_types_raw) if isinstance(unit_types_raw, str) else (unit_types_raw or [])
    except (json.JSONDecodeError, TypeError):
        unit_types = []
    primary_unit = profile.get('primary_unit_type', 'count') or 'count'

    return {
        # Dimension presence
        'has_time': bool(profile.get('has_time')),
        'time_points': int(time_points),
        'time_granularity': cov.get('time_granularity') or profile.get('time_granularity'),
        'has_geo': bool(profile.get('has_geo')),
        'geo_count': int(geo_count),
        'geo_levels': geo_levels,
        'has_gender': bool(profile.get('has_gender')),
        'gender_count': _dim_count(dimensions, 'gender'),
        'has_age': bool(profile.get('has_age')),
        'age_count': _dim_count(dimensions, 'age'),
        'has_residence': bool(profile.get('has_residence')),
        'categorical_dims': indicator_dims,
        'total_dims': int(profile.get('dim_count') or len(dimensions)),
        # Value characteristics
        'has_negatives': (vp.get('negative_pct') or 0) > 0,
        'is_sparse': (cov.get('fill_rate') or 1.0) < 0.3,
        'distribution': vp.get('distribution_shape', 'unknown'),
        'coeff_variation': coeff_var,
        # Unit type — drives chart affinity
        'primary_unit_type': primary_unit,
        'unit_types': unit_types,
        # Trend characteristics
        'trend_direction': tr.get('trend_direction', 'unknown'),
        'has_seasonality': bool(tr.get('has_seasonality')),
        # Original archetype for comparison
        '_archetype': profile.get('archetype', 'time_series'),
    }


def _dim_count(dimensions: list, dim_type: str) -> int:
    for d in dimensions:
        if d.get('dim_type') == dim_type:
            return d.get('option_count') or 0
    return 0


# ---------------------------------------------------------------------------
# 2. Eligibility rules (hard requirements)
# ---------------------------------------------------------------------------

def _eligible(chart_type: str, sig: dict) -> bool:
    has_time = sig['has_time']
    tp = sig['time_points']
    has_geo = sig['has_geo']
    geo = sig['geo_count']
    has_gender = sig['has_gender']
    has_age = sig['has_age']
    gender_count = sig['gender_count']
    total_dims = sig['total_dims']
    cat_dims = sig['categorical_dims']
    has_neg = sig['has_negatives']
    is_sparse = sig['is_sparse']
    cv = sig['coeff_variation'] or 0
    has_residence = sig['has_residence']

    any_cat_gte5 = any(d['count'] >= 5 for d in cat_dims)
    any_cat_lte20 = any(d['count'] <= 20 for d in cat_dims)
    any_cat_facetable = any(6 < d['count'] <= 25 for d in cat_dims)
    # Non-unit, non-time dims for stacked bar threshold
    non_structural_dims = total_dims - (1 if has_time else 0) - 1  # subtract unit dim estimate

    if chart_type == 'line':
        return has_time and tp >= 3
    if chart_type == 'area_stacked':
        return has_time and tp >= 3 and not has_neg and len(cat_dims) >= 1
    if chart_type == 'bar_vertical':
        return True
    if chart_type == 'grouped_bar':
        return total_dims >= 2 and (any_cat_lte20 or has_gender or has_age or has_residence)
    if chart_type == 'stacked_bar':
        # Useful when simple structure (few dims) AND a categorical series with ≤ 4 options
        has_small_series = (
            any(d['count'] <= 4 for d in cat_dims)
            or has_gender or has_residence
        )
        return not has_neg and total_dims >= 2 and has_small_series
    if chart_type == 'horizontal_bar':
        return any_cat_gte5 or (has_geo and geo >= 5)
    if chart_type == 'choropleth':
        return has_geo and geo >= 5
    if chart_type == 'population_pyramid':
        # INS "Sexe si medii" dims mix gender+residence (Total+M+F+Urban+Rural = 5)
        return has_age and has_gender and 2 <= gender_count <= 6
    if chart_type == 'heatmap':
        return total_dims >= 2 and not is_sparse
    if chart_type == 'small_multiples':
        return has_time and (any_cat_facetable or (has_geo and 6 < geo <= 25))
    if chart_type == 'bubble':
        # Bubble map (geo units as circles) or scatter-bubble over time/categories
        return (has_geo and geo >= 5) or (has_time and len(cat_dims) >= 1 and tp >= 3)
    if chart_type == 'table':
        return True
    return False


# ---------------------------------------------------------------------------
# 3. Relevance scoring (soft preferences)
# ---------------------------------------------------------------------------

def _score(chart_type: str, sig: dict) -> float:
    has_time = sig['has_time']
    tp = sig['time_points']
    has_geo = sig['has_geo']
    geo = sig['geo_count']
    has_gender = sig['has_gender']
    has_age = sig['has_age']
    gender_count = sig['gender_count']
    has_neg = sig['has_negatives']
    is_sparse = sig['is_sparse']
    cv = sig['coeff_variation'] or 0
    trend = sig['trend_direction']
    cat_dims = sig['categorical_dims']
    has_residence = sig['has_residence']
    geo_levels = sig['geo_levels']
    unit = sig.get('primary_unit_type', 'count')

    if chart_type == 'line':
        s = 0.5
        if tp >= 10: s += 0.2
        elif tp >= 5: s += 0.1
        if trend in ('increasing', 'decreasing', 'flat'): s += 0.1
        small_series = [d for d in cat_dims if d['count'] <= 6]
        if small_series: s += 0.1
        elif len(cat_dims) == 0 and has_residence: s += 0.1
        # Penalty: too many overlapping series — line becomes unreadable, prefer small_multiples
        if any(d['count'] > 8 for d in cat_dims): s -= 0.15
        # Seasonality: line is THE chart for seasonal data
        if sig['has_seasonality']: s += 0.15
        if sig['time_granularity'] in ('monthly', 'quarterly'): s += 0.05
        # Unit affinity: rates/indices/percentages are best shown as lines.
        # Most "percentage" data is rates/shares/indices, not parts-of-whole.
        if unit in ('rate', 'ratio', 'index', 'percentage'): s += 0.1
        return min(max(s, 0.0), 1.0)

    if chart_type == 'area_stacked':
        # Default-low: area_stacked is good ONLY for true parts-of-whole.
        # Most "percentage" data (rates, indices, shares of independent
        # populations) is NOT parts-of-whole — line is better. Audit found
        # ~92% of percentage datasets in this corpus are not compositions.
        s = 0.35
        series = [d for d in cat_dims if d['count'] <= 8]
        if series: s += 0.1
        if 3 <= (series[0]['count'] if series else 0) <= 6: s += 0.1
        if tp >= 8: s += 0.1
        # Tiny boost only when shape strongly suggests parts-of-whole:
        # percentage unit AND a small categorical series (2-4 options).
        if unit == 'percentage' and series and 2 <= series[0]['count'] <= 4:
            s += 0.05
        # Sparse data makes stacked charts misleading (gaps look like zero)
        if is_sparse: s -= 0.15
        return min(max(s, 0.0), 1.0)

    if chart_type == 'bar_vertical':
        s = 0.45  # slightly lower base — was too greedy at 0.5
        if has_time and tp < 5: s += 0.15   # few time points → bar shines
        if not has_time: s += 0.1           # snapshot data
        cat_small = [d for d in cat_dims if d['count'] <= 15]
        if cat_small: s += 0.1
        if has_geo and geo >= 5: s += 0.05
        # Penalty: bars hide trends in long time series — line is always better
        if has_time and tp >= 10: s -= 0.15
        elif has_time and tp >= 6: s -= 0.05
        # Penalty: seasonal data needs continuous line, not discrete bars
        if sig['has_seasonality']: s -= 0.10
        # Unit penalty: index numbers as bar heights are misleading (base=100)
        if unit == 'index': s -= 0.10
        return min(max(s, 0.0), 1.0)

    if chart_type == 'grouped_bar':
        s = 0.3
        if has_age and has_gender: s += 0.45  # demographic sweet spot
        elif has_gender: s += 0.2
        elif has_age: s += 0.15
        elif has_residence: s += 0.1
        if has_time and tp <= 5: s += 0.1
        return min(s, 1.0)

    if chart_type == 'stacked_bar':
        s = 0.35
        small_series = [d for d in cat_dims if 2 <= d['count'] <= 4]
        if small_series: s += 0.25
        elif has_gender or has_residence: s += 0.2
        if has_time and tp < 5: s += 0.1
        if has_time and tp >= 5: s += 0.05
        # Unit affinity: percentage data stacks meaningfully
        if unit == 'percentage' and small_series: s += 0.1
        # Sparse data creates misleading gaps in stacks
        if is_sparse: s -= 0.10
        return min(max(s, 0.0), 1.0)

    if chart_type == 'horizontal_bar':
        s = 0.5
        long_cats = [d for d in cat_dims if 10 <= d['count'] <= 50]
        if long_cats: s += 0.2
        if not has_time: s += 0.1
        elif has_time and tp == 1: s += 0.05
        if has_geo and 10 <= geo <= 50: s += 0.1
        # Unit affinity: currency/count are natural for comparison bars
        if unit in ('currency', 'count'): s += 0.05
        # Cap below choropleth for high geo coverage (explicit, no recursion)
        if has_geo and geo >= 30: s = min(s, 0.80)
        return min(s, 1.0)

    if chart_type == 'choropleth':
        s = 0.6
        if geo >= 30: s += 0.25
        elif geo >= 20: s += 0.15
        elif geo >= 10: s += 0.05
        if 'county' in geo_levels: s += 0.05
        if has_time: s += 0.05
        # Geo + demographic combo: choropleth is the natural primary,
        # demographic dim becomes a filter rather than a series.
        if has_age or has_gender or has_residence: s += 0.15
        if is_sparse: s -= 0.10
        return min(max(s, 0.0), 1.0)

    if chart_type == 'population_pyramid':
        s = 0.0
        if has_age and has_gender:
            s = 0.7
            # 2 = M+F (ideal); 3 = M+F+Total (still pyramid-friendly, Total filtered at render)
            if gender_count == 2: s += 0.2
            elif gender_count == 3: s += 0.15
            if sig['age_count'] >= 5: s += 0.1
        return min(s, 1.0)

    if chart_type == 'heatmap':
        s = 0.3
        dims_10_30 = [d for d in cat_dims if 10 <= d['count'] <= 30]
        if len(dims_10_30) >= 2: s += 0.3
        elif len(dims_10_30) == 1: s += 0.15
        # Age × Time is a classic heatmap shape (age groups stack badly as lines).
        # Skip when geo is present — choropleth is the better primary in that case.
        if has_age and has_time and sig['age_count'] >= 6 and not has_gender and not has_geo:
            s += 0.30
        if not is_sparse: s += 0.1
        if has_time and tp >= 5: s += 0.1
        if cv > 0.5: s += 0.05
        return min(s, 1.0)

    if chart_type == 'small_multiples':
        s = 0.35
        facet_dims = [d for d in cat_dims if 6 < d['count'] <= 16]
        if facet_dims: s += 0.35
        elif facet_dims := [d for d in cat_dims if 6 < d['count'] <= 25]:
            s += 0.25
        if has_geo and 6 < geo <= 16: s += 0.2
        # Time series matter most for facets — strong bonus when present
        if has_time and tp >= 5: s += 0.15
        elif has_time and tp >= 3: s += 0.1
        # Sparse data: many facets will be mostly empty
        if is_sparse: s -= 0.10
        return min(max(s, 0.0), 1.0)

    if chart_type == 'bubble':
        s = 0.4
        if has_geo and geo >= 10: s += 0.15
        if has_geo and has_time: s += 0.1
        if len(cat_dims) >= 1 and has_time:
            best_cat = min(cat_dims, key=lambda d: d['count'], default=None)
            if best_cat and best_cat['count'] <= 20: s += 0.1
        # Unit affinity: count/currency with large values → bubble size is meaningful
        if unit in ('count', 'currency'): s += 0.05
        # Cap below choropleth for high geo coverage (explicit, no recursion)
        if has_geo and geo >= 20: s = min(s, 0.80)
        return min(max(s, 0.0), 1.0)

    if chart_type == 'table':
        return 0.2

    return 0.0


# ---------------------------------------------------------------------------
# 4. Main selection function
# ---------------------------------------------------------------------------

CHART_TYPES = [
    'line', 'area_stacked', 'bar_vertical', 'grouped_bar', 'stacked_bar',
    'horizontal_bar', 'choropleth', 'population_pyramid', 'heatmap',
    'small_multiples', 'bubble', 'table',
]


def select_charts(sig: dict, top_n: int = 8) -> list[dict]:
    """Return ranked list of applicable chart types with scores and confidence.

    Returns:
        List of dicts sorted by score DESC. First item = recommended primary.
        Each entry: {chart_type, score, confidence, complementary_to?}
    """
    results = []
    for ct in CHART_TYPES:
        if _eligible(ct, sig):
            score = _score(ct, sig)
            results.append({'chart_type': ct, 'score': round(score, 3)})

    # Deterministic tie-breaking: prefer more specific/informative charts
    results.sort(key=lambda x: (-x['score'], TIEBREAK_PRIORITY.get(x['chart_type'], 99)))
    results = results[:top_n]

    # Confidence: how sure are we about the primary recommendation?
    if len(results) >= 2:
        gap = results[0]['score'] - results[1]['score']
        confidence = 'high' if gap > 0.15 else 'medium' if gap > 0.05 else 'low'
    elif len(results) == 1:
        confidence = 'high'
    else:
        confidence = 'low'

    for entry in results:
        entry['confidence'] = confidence

    # Mark complementary pairs among top results
    top_types = {r['chart_type'] for r in results[:4]}
    for entry in results:
        for pair, reason in COMPLEMENTARY_PAIRS.items():
            if entry['chart_type'] in pair:
                partner = (pair - {entry['chart_type']})
                if partner & top_types:
                    entry['complementary_to'] = list(partner & top_types)[0]
                    entry['complementary_reason'] = reason
                    break

    return results


def assign_roles(chart_type: str, dimensions: list, sig: dict = None) -> dict:
    """Map dimension columns to visual roles for a given chart type.

    Args:
        chart_type: The selected chart type
        dimensions: List of dimension dicts
        sig: Optional signature dict — enables context-aware assignment

    Returns dict with keys: x_axis, series, facet, timeline, filter (list),
    filter_hints (dict), defaults (dict)
    """
    roles = {'x_axis': None, 'series': None, 'facet': None,
             'timeline': None, 'filter': [], 'filter_hints': {},
             'defaults': {}}

    by_type = {}
    for d in dimensions:
        dt = d.get('dim_type', 'indicator')
        by_type.setdefault(dt, []).append(d)

    def pop_type(dtype):
        dims = by_type.get(dtype, [])
        return dims[0] if dims else None

    def col(d):
        return d['dim_column_name'] if d else None

    time_d = pop_type('time')
    geo_d = pop_type('geo')
    gender_d = pop_type('gender')
    age_d = pop_type('age')
    residence_d = pop_type('residence')
    indicators = by_type.get('indicator', [])
    unit_d = pop_type('unit')

    assigned = set()

    def assign(role, dim):
        if dim:
            roles[role] = col(dim)
            assigned.add(col(dim))

    if chart_type == 'line':
        assign('x_axis', time_d)
        # Best series: gender/residence > small indicator (2-6 sweet spot) > age
        if gender_d: assign('series', gender_d)
        elif residence_d: assign('series', residence_d)
        elif indicators:
            # Prefer indicators in the 2-6 range (readable line count)
            sweet = [d for d in indicators if 2 <= (d.get('option_count') or 0) <= 6]
            small = [d for d in indicators if (d.get('option_count') or 0) <= 15]
            best = min(sweet or small or [], key=lambda d: d.get('option_count') or 99, default=None)
            if best:
                assign('series', best)
        if not roles['series'] and age_d and (age_d.get('option_count') or 0) <= 8:
            assign('series', age_d)
        # Facet: another indicator with 6-25 options
        for d in indicators:
            if col(d) not in assigned and 6 < (d.get('option_count') or 0) <= 25:
                assign('facet', d)
                break

    elif chart_type in ('area_stacked', 'stacked_bar'):
        assign('x_axis', time_d)
        # For stacking, prefer small categorical dims (parts-of-whole)
        stackable = [d for d in indicators if 2 <= (d.get('option_count') or 0) <= 6]
        if stackable:
            assign('series', stackable[0])
        elif has_gender_or_residence := (gender_d or residence_d):
            assign('series', has_gender_or_residence)
        elif indicators:
            assign('series', indicators[0])

    elif chart_type == 'bar_vertical':
        assign('x_axis', time_d or (indicators[0] if indicators else None))
        if time_d and indicators:
            assign('series', indicators[0])

    elif chart_type == 'grouped_bar':
        assign('x_axis', age_d or (indicators[0] if indicators else None))
        assign('series', gender_d or residence_d or (indicators[1] if len(indicators) > 1 else None))
        assign('timeline', time_d)

    elif chart_type == 'population_pyramid':
        assign('x_axis', age_d)
        assign('series', gender_d)
        assign('timeline', time_d)

    elif chart_type == 'choropleth':
        assign('x_axis', geo_d)
        assign('timeline', time_d)

    elif chart_type == 'heatmap':
        sorted_cats = sorted(indicators, key=lambda d: d.get('option_count') or 0, reverse=True)
        if sorted_cats:
            assign('x_axis', sorted_cats[0])
        if len(sorted_cats) > 1:
            assign('series', sorted_cats[1])
        if not roles['x_axis'] and age_d:
            assign('x_axis', age_d)
        if not roles['series'] and gender_d:
            assign('series', gender_d)

    elif chart_type == 'small_multiples':
        assign('x_axis', time_d)
        for d in indicators:
            if 6 < (d.get('option_count') or 0) <= 25:
                assign('facet', d)
                break
        if not roles['facet'] and geo_d:
            assign('facet', geo_d)

    elif chart_type == 'horizontal_bar':
        candidates = indicators + ([geo_d] if geo_d else [])
        if candidates:
            best = max(candidates, key=lambda d: d.get('option_count') or 0)
            assign('x_axis', best)
        assign('timeline', time_d)

    elif chart_type == 'bubble':
        if geo_d:
            assign('x_axis', geo_d)
            assign('timeline', time_d)
            if indicators:
                assign('series', indicators[0])
        else:
            assign('x_axis', time_d)
            if indicators:
                assign('series', indicators[0])
            if len(indicators) > 1:
                assign('facet', indicators[1])

    # Everything not assigned → filter, with type hints
    for d in dimensions:
        c = col(d)
        if c not in assigned and d.get('dim_type') != 'unit':
            roles['filter'].append(c)
            opt_count = d.get('option_count') or 0
            if opt_count > 25:
                roles['filter_hints'][c] = 'single_select'
            elif opt_count > 6:
                roles['filter_hints'][c] = 'multi_select'
            else:
                roles['filter_hints'][c] = 'pill_group'

    # Recommended default filter state
    if chart_type in ('choropleth', 'horizontal_bar', 'heatmap'):
        roles['defaults']['time'] = 'latest'
    if chart_type != 'population_pyramid':
        roles['defaults']['exclude_total'] = True

    return roles
