"""FIX-02: shared aggregation decision — synthetic fixtures with known answers."""
import pytest

from app.services import aggregation_policy as ap
from app.services.aggregation_policy import (
    decide, classify_measure, weighted_mean, combine, compute_change,
    VALID_TOTAL, VALID_SLICE, APPROXIMATION, UNAVAILABLE, WeightSpec)


def opt(label, **parsed):
    return {'label': label, 'sdmx_value': label, 'parsed': parsed}


def dim(col, dtype, options):
    return {'dim_column_name': col, 'dim_type': dtype, 'options': options}


def eff_of(dims):
    return {d['dim_column_name']: [(o, o['label']) for o in d['options']] for d in dims}


def run(dims, **kw):
    return decide(dimensions=dims, effective=eff_of(dims), **kw)


TIME = dim('TIME_PERIOD', 'time', [opt('2024', year=2024)])


# 1. Total=100 with components 40+60 -> 100, never 200 -------------------------
def test_total_row_wins_over_components():
    cat = dim('CATEGORY', 'indicator', [opt('Total'), opt('A'), opt('B')])
    d = run([TIME, cat], group_by=['TIME_PERIOD'], unit_type='count')
    assert d.outcome == VALID_TOTAL and d.method == 'aggregate_row'
    assert d.effective_filters == {'CATEGORY': ['Total']}
    rows = {'Total': 100, 'A': 40, 'B': 60}
    picked = [v for k, v in rows.items() if k in d.effective_filters['CATEGORY']]
    assert combine(d, picked) == 100


# 2. age partitions + geo levels -----------------------------------------------
AGE_YEARS = [opt(f'{i} ani', age_min=i, age_max=i) for i in range(5)]
AGE_BANDS = [opt('0-4 ani', age_min=0, age_max=4), opt('5-9 ani', age_min=5, age_max=9)]
GEO_COUNTIES = [opt(f'Judet{i}', geo_level='county') for i in range(3)]
GEO_REGIONS = [opt('Regiunea X', geo_level='region')]


def test_overlapping_age_and_geo_levels_suppress_total():
    age = dim('AGE', 'age', AGE_YEARS + AGE_BANDS)
    geo = dim('REF_AREA', 'geo', GEO_COUNTIES + GEO_REGIONS)
    d = run([TIME, age, geo], group_by=['TIME_PERIOD'], unit_type='count')
    assert d.outcome == UNAVAILABLE and d.reason == 'overlapping_levels'


def test_explicit_slice_still_allowed_when_overlap_unresolved():
    age = dim('AGE', 'age', AGE_YEARS + AGE_BANDS)
    geo = dim('REF_AREA', 'geo', GEO_COUNTIES + GEO_REGIONS)
    d = run([TIME, age, geo], group_by=['TIME_PERIOD'], unit_type='count',
            filters={'AGE': ['0-4 ani', '5-9 ani'],
                     'REF_AREA': ['Judet0', 'Judet1', 'Judet2']})
    assert d.outcome == VALID_SLICE and d.available
    # a user set mixing grains is still refused
    d2 = run([TIME, age, geo], group_by=['TIME_PERIOD'], unit_type='count',
             filters={'AGE': ['0 ani', '0-4 ani'], 'REF_AREA': ['Judet0']})
    assert d2.outcome == UNAVAILABLE


def test_one_partition_per_dim_gives_valid_total():
    age = dim('AGE', 'age', AGE_BANDS)
    geo = dim('REF_AREA', 'geo', GEO_COUNTIES)
    sex = dim('SEX', 'gender', [opt('Masculin'), opt('Feminin')])
    d = run([TIME, age, geo, sex], group_by=['TIME_PERIOD'], unit_type='count')
    assert d.outcome == VALID_TOTAL and d.method == 'sum_partition'
    assert d.verification == 'metadata'


def test_verified_level_is_selected_and_reported():
    struct = {'AGE': {'confidence': 'verified', 'default_level': 'bands',
                      'levels': [
                          {'level_id': 'years', 'verified': True,
                           'members': [o['label'] for o in AGE_YEARS]},
                          {'level_id': 'bands', 'verified': True,
                           'members': [o['label'] for o in AGE_BANDS]}]}}
    age = dim('AGE', 'age', AGE_YEARS + AGE_BANDS)
    d = run([TIME, age], group_by=['TIME_PERIOD'], unit_type='count', struct=struct)
    assert d.outcome == VALID_TOTAL and d.verification == 'verified'
    assert d.levels == {'AGE': 'bands'}
    assert d.effective_filters['AGE'] == ['0-4 ani', '5-9 ani']


def test_unprofiled_indicator_is_conservative():
    cat = dim('CATEGORY', 'indicator', [opt('Cereale'), opt('Legume')])
    d = run([TIME, cat], group_by=['TIME_PERIOD'], unit_type='count')
    assert d.outcome == UNAVAILABLE and d.reason == 'unverified_structure'
    # a profiler-confirmed flat dim is fine
    d2 = run([TIME, cat], group_by=['TIME_PERIOD'], unit_type='count',
             struct={'CATEGORY': {'confidence': 'flat', 'levels': []}})
    assert d2.outcome == VALID_TOTAL and d2.verification == 'profile_flat'


def test_label_hierarchy_is_not_summed():
    cat = dim('CAT', 'indicator', [opt('Taurine - total'), opt(' Vaci'), opt(' Juninci')])
    # no Total-regex hit, but a "- total" tree
    d = run([TIME, cat], group_by=['TIME_PERIOD'], unit_type='count',
            struct={'CAT': {'confidence': 'flat', 'levels': []}})
    assert d.outcome == UNAVAILABLE and d.reason == 'label_hierarchy'


# 3. rates + weights -------------------------------------------------------------
def test_weighted_mean_with_weights_and_no_fake_total_without():
    assert weighted_mean([(10, 90), (20, 10)]) == pytest.approx(11.0)
    county = dim('REF_AREA', 'geo', GEO_COUNTIES[:2])
    kw = dict(group_by=['TIME_PERIOD'], unit_type='percentage')
    d = run([TIME, county], **kw)
    assert d.outcome == UNAVAILABLE and d.reason == 'missing_weights'
    dw = run([TIME, county], weights=WeightSpec('DENOM1'), **kw)
    assert dw.outcome == VALID_TOTAL and dw.method == 'weighted_mean'
    assert combine(dw, [10, 20], [90, 10]) == pytest.approx(11.0)
    da = run([TIME, county], allow_approximation=True, **kw)
    assert da.outcome == APPROXIMATION and da.approximation
    assert da.method == 'unweighted_mean' and combine(da, [10, 20]) == 15
    assert da.outcome != VALID_TOTAL


def test_non_additive_pinned_slice_is_valid():
    sex = dim('SEX', 'gender', [opt('Total'), opt('Masculin')])
    d = run([TIME, sex], group_by=['TIME_PERIOD'], unit_type='rate',
            filters={'SEX': ['Masculin']})
    assert d.outcome == VALID_SLICE and d.method == 'single_row'


# 4. units -------------------------------------------------------------------------
def test_mixed_units_cannot_aggregate():
    unit = dim('UNIT_MEASURE', 'unit', [opt('Tone'), opt('Mii lei')])
    d = run([TIME, unit], group_by=['TIME_PERIOD'], unit_type='count')
    assert d.outcome == UNAVAILABLE and d.reason == 'mixed_units'
    d2 = run([TIME, unit], group_by=['TIME_PERIOD'], unit_type='count',
             filters={'UNIT_MEASURE': ['Tone']})
    assert d2.available


def test_currency_additivity_from_indicator_semantics():
    assert classify_measure('currency', 'Castigul salarial mediu net lunar') == 'non_additive'
    assert classify_measure('currency', 'Cifra de afaceri pe activitati') == 'additive'
    assert classify_measure('currency', '') == 'non_additive'          # conservative
    assert classify_measure('currency', 'Cifra de afaceri', struct_additive=False) == 'non_additive'
    assert classify_measure('count') == 'additive'
    for u in ('percentage', 'rate', 'ratio', 'index', 'time_unit', 'currency'):
        assert ap.is_non_additive_unit(u)


def test_declared_partition_rules():
    sex = dim('SEX', 'gender', [opt('Masculin'), opt('Feminin')])
    sex_unprof = dim('CAT', 'indicator', [opt('F'), opt('M')])
    d = run([TIME, sex_unprof], group_by=['TIME_PERIOD'], unit_type='count',
            declared_partitions=['CAT'])
    assert d.outcome == VALID_TOTAL and d.verification == 'curated'
    bad = dim('CAT', 'indicator', [opt('Total'), opt('F')])
    # a Total next to parts is pinned (aggregate), declared partition not needed
    assert run([TIME, bad], group_by=['TIME_PERIOD'], unit_type='count',
               declared_partitions=['CAT']).method == 'aggregate_row'
    hier = dim('CAT', 'indicator', [opt('X - total'), opt(' x1')])
    assert run([TIME, hier], group_by=['TIME_PERIOD'], unit_type='count',
               declared_partitions=['CAT']).reason == 'declared_partition_invalid'
    assert run([TIME, sex_unprof], group_by=['TIME_PERIOD'], unit_type='rate',
               declared_partitions=['CAT']).reason in ('missing_weights',
                                                       'declared_partition_invalid')


# 5. agreement: identical input -> identical decision ----------------------------
def test_same_slice_same_decision():
    age = dim('AGE', 'age', AGE_YEARS + AGE_BANDS)
    a = run([TIME, age], group_by=['TIME_PERIOD'], unit_type='count').to_dict()
    b = run([TIME, age], group_by=['TIME_PERIOD'], unit_type='count').to_dict()
    assert a == b


# 6. changes ----------------------------------------------------------------------
def test_change_unavailable_for_zero_or_missing_comparator():
    c = compute_change([('2023', 0), ('2024', 5)])
    assert c['status'] == 'unavailable' and c['reason'] == 'comparator_zero'
    assert c['value'] is None
    c = compute_change([('2024', 5)])
    assert c['status'] == 'unavailable' and c['reason'] == 'comparator_missing'
    # points do not divide, so a zero base is fine
    assert compute_change([('2023', 0), ('2024', 5)], unit='points')['value'] == 5
    c = compute_change([('2023', 100), ('2024', 110)])
    assert c['value'] == 10.0 and c['basis'] == 'yoy' and c['from_period'] == '2023'


def test_change_uses_same_period_last_year_for_subannual():
    s = [('2025-02', 100), ('2025-03', 150), ('2026-02', 110), ('2026-03', 120)]
    c = compute_change(s)
    assert c['basis'] == 'yoy' and c['from_period'] == '2025-03' and c['value'] == -20.0
    c = compute_change([('2026-01', 100), ('2026-02', 110)])
    assert c['basis'] == 'mom' and c['from_period'] == '2026-01'
    c = compute_change([('2025-Q4', 100), ('2026-Q1', 110)])
    assert c['basis'] == 'qoq'


def test_provenance_fields():
    d = run([TIME], group_by=['TIME_PERIOD'], unit_type='count')
    p = ap.provenance(d, source_code='X1', period='2024', unit='persoane')
    assert set(p) == {'source_code', 'period', 'unit', 'filters', 'levels', 'method',
                      'verification', 'approximation', 'outcome', 'reason',
                      'comparison', 'dimensions'}
