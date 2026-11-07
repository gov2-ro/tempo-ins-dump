"""Audit C02: a dim that mixes sex and residence options is not a partition."""
import pytest

from app.services import aggregation_policy as ap
from app.services.aggregation_policy import decide, partition_kind, VALID_TOTAL, UNAVAILABLE
from app.services.dashboard_composer import _stack_ok


def opt(label):
    return {'label': label, 'sdmx_value': label, 'parsed': {}}


def dim(col, dtype, labels):
    return {'dim_column_name': col, 'dim_type': dtype, 'options': [opt(l) for l in labels]}


TIME = dim('TIME_PERIOD', 'time', ['2024'])
MIXED = ['Masculin', 'Feminin', 'Urban', 'Rural']


def run(dims, **kw):
    eff = {d['dim_column_name']: [(o, o['label']) for o in d['options']] for d in dims}
    return decide(dimensions=dims, effective=eff, group_by=['TIME_PERIOD'],
                  unit_type='count', **kw)


@pytest.mark.parametrize('labels,kind', [
    (MIXED, 'mixed'),
    (['Total', 'Masculin ', 'Feminin ', 'Urban', 'Rural'], 'mixed'),
    (['Male', 'Female', 'Urban', 'Rural'], 'mixed'),
    (['Masculin', 'Feminin'], 'sex'),
    (['Total', 'Barbati', 'Femei'], 'sex'),
    (['Urban', 'Rural'], 'residence'),
    (['Agricultura', 'Industrie'], None),
    (['Masculin', 'Feminin', 'Necunoscut'], None),
])
def test_partition_kind(labels, kind):
    assert partition_kind(labels) == kind


@pytest.mark.parametrize('dtype', ['residence', 'gender', 'indicator'])
def test_mixed_dim_without_total_is_not_summed(dtype):
    d = run([TIME, dim('RESIDENCE', dtype, MIXED)])
    assert d.outcome == UNAVAILABLE and d.reason == 'overlapping_levels'
    assert d.blocking_dimension == 'RESIDENCE'


def test_mixed_dim_explicit_set_of_all_four_is_refused():
    d = run([TIME, dim('RESIDENCE', 'residence', MIXED)], filters={'RESIDENCE': MIXED})
    assert d.outcome == UNAVAILABLE and d.reason == 'overlapping_levels'


def test_mixed_dim_with_total_pins_the_total():
    d = run([TIME, dim('RESIDENCE', 'residence', ['Total'] + MIXED)])
    assert d.outcome == VALID_TOTAL and d.method == 'aggregate_row'
    assert d.effective_filters == {'RESIDENCE': ['Total']}


@pytest.mark.parametrize('dtype,labels', [('gender', ['Masculin', 'Feminin']),
                                          ('residence', ['Urban', 'Rural'])])
def test_single_partitions_still_sum(dtype, labels):
    d = run([TIME, dim('X', dtype, labels)])
    assert d.outcome == VALID_TOTAL and d.method == 'sum_partition'
    assert d.dimensions[-1]['verification'] == 'metadata'
    assert ap.combine(d, [40, 60]) == 100


def test_mixed_series_is_not_stackable():
    assert not _stack_ok(dim('RESIDENCE', 'residence', MIXED), None, {}, False)
    # a verified additive flag does not make a mixed dim a partition
    assert not _stack_ok(dim('RESIDENCE', 'residence', MIXED), None,
                         {'RESIDENCE': {'additive': True, 'n_levels': 1}}, False)


@pytest.mark.parametrize('dtype,labels', [('gender', ['Masculin', 'Feminin']),
                                          ('residence', ['Urban', 'Rural'])])
def test_single_partition_series_stays_stackable(dtype, labels):
    assert _stack_ok(dim('X', dtype, labels), None, {}, False)
    assert not _stack_ok(dim('X', dtype, labels), None, {}, True)
