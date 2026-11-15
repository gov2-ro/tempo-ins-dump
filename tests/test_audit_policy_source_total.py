"""Audit E1/E2/E11: a sum is not a valid total when the dataset's summed headline
disagrees with the INS Total and INS has not shown the summed dimension adds up.

The kpi_total_checks row reaches decide() under struct[SOURCE_TOTAL_KEY] (with
`dims_match` from kpi_dimension_checks), so every caller gets the same verdict.
"""
import pytest

from app.services.aggregation_policy import (
    decide, SOURCE_TOTAL_KEY, VALID_TOTAL, VALID_SLICE, UNAVAILABLE)


def opt(label, **parsed):
    return {'label': label, 'sdmx_value': label, 'parsed': parsed}


def dim(col, dtype, options):
    return {'dim_column_name': col, 'dim_type': dtype, 'options': options}


TIME = dim('TIME_PERIOD', 'time', [opt('2024', year=2024)])
# SCL104A-like: levels that nest, but the profiler found the dim flat.
LEVELS = dim('NIVEL', 'indicator', [opt('Preuniversitar'), opt('Primar'), opt('Universitar')])
GEO = dim('REF_AREA', 'geo', [opt('Cluj', geo_level='county'), opt('Bucuresti', geo_level='county')])
SEX = dim('SEX', 'gender', [opt('Masculin'), opt('Feminin')])
DIMS = [TIME, LEVELS, GEO, SEX]

# Known values: per county, Preuniversitar 100 = Primar 100, Universitar 20.
# INS publishes 240 for both counties; our naive sum is 440 (rel +0.833).
MISMATCH = {'status': 'mismatch', 'period': '2024', 'ours': 440.0, 'ins': 240.0,
            'rel': 0.8333, 'dims_match': ['REF_AREA', 'SEX']}


def struct(check=None, flat=('NIVEL', 'REF_AREA', 'SEX')):
    s = {c: {'levels': [], 'confidence': 'flat', 'n_levels': 0} for c in flat}
    if check is not None:
        s[SOURCE_TOTAL_KEY] = check
    return s


def run(group_by, filters=None, check=None, **kw):
    eff = {d['dim_column_name']: [(o, o['label']) for o in d['options']] for d in DIMS}
    return decide(dimensions=DIMS, effective=eff, group_by=group_by, filters=filters,
                  struct=struct(check), measure='additive', **kw)


@pytest.mark.parametrize('api_mode', [False, True])
def test_sum_over_unchecked_dim_is_refused(api_mode):
    d = run(['REF_AREA', 'TIME_PERIOD'], check=MISMATCH, api_mode=api_mode)
    assert d.outcome == UNAVAILABLE and d.reason == 'source_total_mismatch'
    assert d.blocking_dimension == 'NIVEL'
    sc = d.to_dict()['source_check']
    assert sc['value'] == 240.0 and sc['ours'] == 440.0
    assert sc['message'] == ('The sum over NIVEL does not agree with the INS total for 2024: '
                             '440 against 240 (relative error 83%).')


def test_sum_over_dims_that_ins_shows_adding_up_stays_valid():
    # NIVEL pinned: only REF_AREA and SEX are summed, both agree with INS
    d = run(['TIME_PERIOD'], filters={'NIVEL': ['Primar']}, check=MISMATCH)
    assert d.outcome == VALID_SLICE and d.method == 'sum_partition'
    assert 'source_check' not in d.to_dict()


def test_dims_match_absent_refuses_every_summed_dim():
    chk = {**MISMATCH, 'dims_match': []}
    d = run(['NIVEL', 'TIME_PERIOD'], check=chk)
    assert d.reason == 'source_total_mismatch' and d.blocking_dimension == 'REF_AREA'
    assert 'REF_AREA, SEX' in d.source_check['message']


@pytest.mark.parametrize('check', [None, {'status': 'match', 'period': '2024', 'ours': 240.0,
                                          'ins': 240.0, 'rel': 0.0, 'dims_match': []},
                                   {'status': 'unresolved', 'dims_match': []}])
def test_no_mismatch_leaves_the_verdict_unchanged(check):
    d = run(['REF_AREA', 'TIME_PERIOD'], check=check)
    assert d.outcome == VALID_TOTAL and d.method == 'sum_partition'
    assert 'source_check' not in d.to_dict()


def test_grouping_by_every_dim_is_not_a_sum():
    d = run(['NIVEL', 'REF_AREA', 'SEX', 'TIME_PERIOD'], check=MISMATCH)
    assert d.outcome == VALID_TOTAL and d.method == 'aggregate_row'


def test_explicit_set_stays_a_slice():
    d = run(['TIME_PERIOD'], filters={'NIVEL': ['Primar', 'Universitar']}, check=MISMATCH)
    assert d.outcome == VALID_SLICE


def test_message_without_values_still_names_the_dims():
    d = run(['REF_AREA', 'TIME_PERIOD'], check={'status': 'mismatch', 'dims_match': []})
    assert d.source_check['message'] == 'The sum over NIVEL, SEX does not agree with the INS total.'
