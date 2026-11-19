"""AQ-10: a "Din care" ("of which") option is a part of the option before it, never a sibling.

Policy rule (label variants, refusal, explicit selections), the tool path (the Q17 double
count in rank_entities, the child's refusal that no longer offers an unchecked parent) and
one corpus probe on the served LOC104A.
"""
import duckdb
import pytest

from app.services import aggregation_policy as ap
from app.services.aggregation_policy import decide, VALID_TOTAL, UNAVAILABLE
from at01_fixtures import add_dataset, add_split, call, make_env
from test_at01_changes import area_dim, time_dim, unit_dim


def opt(label):
    return {'label': label, 'sdmx_value': label, 'parsed': {}}


def dim(col, dtype, labels):
    return {'dim_column_name': col, 'dim_type': dtype, 'options': [opt(l) for l in labels]}


TIME = dim('TIME_PERIOD', 'time', ['2024'])
PUBLIC, PRIVATE = 'Din fonduri publice', 'Din fonduri private'
SUBSET = 'Din care: din fondurile populatiei'


def run(labels, **kw):
    dims = [TIME, dim('SRC', 'indicator', labels)]
    eff = {d['dim_column_name']: [(o, o['label']) for o in d['options']] for d in dims}
    return decide(dimensions=dims, effective=eff, group_by=['TIME_PERIOD'], unit_type='count', **kw)


# ---------------------------------------------------------------- label variants

@pytest.mark.parametrize('label,expected', [
    ('Din care: din fondurile populatiei', True),
    ('din care', True),
    ('DIN CARE: X', True),
    ('   Din care: X', True),
    ('        - din care:', True),
    ('- Din care, exclusiv informala', True),
    ('Din care : X', True),
    ('Of which: included in cities', True),
    ('of which, in urban area', True),
    ('OF WHICH :Individual holdings', True),
    ('Total, din care:', False),            # a Total with a colon, not a part
    ('Total of which:', False),
    ('De capital, din care:', False),
    ('Din fonduri private', False),
    ('Dincolo de care', False),
    ('', False),
    (None, False),
])
def test_subset_label_variants(label, expected):
    assert ap.is_subset_label(label) is expected


def test_diacritics_are_folded():
    assert ap.is_subset_label('Dín cáre: x') is True


# ---------------------------------------------------------------- the rule

@pytest.mark.parametrize('subset', [SUBSET, 'din care:  X', 'Of which: X', '  - DIN CARE: X'])
def test_a_sum_over_a_dim_with_a_subset_option_is_refused(subset):
    d = run([PUBLIC, PRIVATE, subset])
    assert d.outcome == UNAVAILABLE and d.reason == 'label_hierarchy'
    assert d.blocking_dimension == 'SRC'


def test_a_total_option_is_still_pinned():
    d = run(['Total', PUBLIC, PRIVATE, SUBSET])
    assert d.outcome == VALID_TOTAL and d.effective_filters == {'SRC': ['Total']}


def test_explicit_non_subset_options_sum():
    d = run([PUBLIC, PRIVATE, SUBSET], filters={'SRC': [PUBLIC, PRIVATE]})
    assert d.outcome != UNAVAILABLE and d.method == 'sum_partition'


def test_a_subset_with_the_option_it_is_part_of_is_refused():
    d = run([PUBLIC, PRIVATE, SUBSET], filters={'SRC': [PRIVATE, SUBSET]})
    assert d.outcome == UNAVAILABLE and d.reason == 'label_hierarchy'


def test_all_three_selected_explicitly_is_refused():
    d = run([PUBLIC, PRIVATE, SUBSET], filters={'SRC': [PUBLIC, PRIVATE, SUBSET]})
    assert d.outcome == UNAVAILABLE and d.reason == 'label_hierarchy'


def test_a_subset_with_an_unrelated_option_is_allowed():
    # the subset belongs to PRIVATE (the option before it), so PUBLIC + subset does not overlap
    d = run([PUBLIC, PRIVATE, SUBSET], filters={'SRC': [PUBLIC, SUBSET]})
    assert d.outcome != UNAVAILABLE


def test_one_pinned_subset_is_a_slice():
    d = run([PUBLIC, PRIVATE, SUBSET], filters={'SRC': [SUBSET]})
    assert d.outcome != UNAVAILABLE and d.method == 'single_row'


def test_the_parent_is_the_option_before_in_the_dimensions_order():
    labels = [PUBLIC, SUBSET, PRIVATE]            # subset after PUBLIC
    assert run(labels, filters={'SRC': [PUBLIC, SUBSET]}).reason == 'label_hierarchy'
    assert run(labels, filters={'SRC': [PRIVATE, SUBSET]}).outcome != UNAVAILABLE


def test_the_subset_is_found_on_the_data_value_when_the_label_differs():
    o = {'label': 'Surse private', 'sdmx_value': 'Din care: x', 'parsed': {}}
    dims = [TIME, {'dim_column_name': 'SRC', 'dim_type': 'indicator',
                   'options': [opt(PUBLIC), o]}]
    eff = {'TIME_PERIOD': [(dims[0]['options'][0], '2024')],
           'SRC': [(dims[1]['options'][0], PUBLIC), (o, 'CODE_B')]}
    d = decide(dimensions=dims, effective=eff, group_by=['TIME_PERIOD'], unit_type='count')
    assert d.outcome == UNAVAILABLE and d.reason == 'label_hierarchy'


def test_gender_dim_with_a_subset_is_not_taken_as_metadata_partition():
    dims = [TIME, dim('SEX', 'gender', ['Masculin', 'Feminin', 'Din care: copii'])]
    eff = {d['dim_column_name']: [(o, o['label']) for o in d['options']] for d in dims}
    d = decide(dimensions=dims, effective=eff, group_by=['TIME_PERIOD'], unit_type='count')
    assert d.outcome == UNAVAILABLE and d.reason == 'label_hierarchy'


# ---------------------------------------------------------------- the tool path (Q17)

CITIES = [f'{1000 + i} ORAS CITY{i:03}' for i in range(3)]
YEARS = ('2024',)
SOURCES = [(PUBLIC, {}), (PRIVATE, {}), (SUBSET, {})]


def src_dim():
    return ('SRC', 'Surse', 'indicator', SOURCES)


def build(corpus):
    dims = [area_dim(['County']), area_dim(CITIES, 'locality', 'REF_AREA_2'), src_dim(),
            time_dim(YEARS), unit_dim('Numar')]
    rows = []
    for i, c in enumerate(CITIES):
        rows += [('County', c, PUBLIC, '2024', 'Numar', 10.0 + i),
                 ('County', c, PRIVATE, '2024', 'Numar', 30.0 + i),
                 ('County', c, SUBSET, '2024', 'Numar', 8.0 + i)]
    rows = [(a, b, s, t, u, v) for a, b, s, t, u, v in rows]
    add_dataset(corpus, 'DCPAR', dims, rows)
    add_dataset(corpus, 'DCKID', dims, rows, parent='DCPAR')
    add_split(corpus, 'DCPAR', 'DCKID', 'DCKID', {})
    add_dataset(corpus, 'GOS102A', [area_dim(CITIES, 'locality', 'REF_AREA_2'), time_dim(YEARS),
                                   unit_dim('Hectare')], [(c, '2024', 'Hectare', 1.) for c in CITIES])
    sex = ('SEX', 'Sexe', 'gender', [('Masculin', {'gender': 'M'}), ('Feminin', {'gender': 'F'})])
    sdims = [sex, area_dim(['Nord', 'Sud'], 'region'), time_dim(YEARS)]
    srows = [(g, a, '2024', v) for a in ('Nord', 'Sud') for g, v in (('Masculin', 60.0), ('Feminin', 40.0))]
    add_dataset(corpus, 'SXPAR', sdims, srows)
    add_dataset(corpus, 'SXKID', sdims, srows, parent='SXPAR')
    add_split(corpus, 'SXPAR', 'SXKID', 'SXKID', {})
    db = duckdb.connect(str(corpus / 'metadata.duckdb'))
    db.execute("CREATE TABLE kpi_total_checks (matrix_code VARCHAR, status VARCHAR, period VARCHAR, "
               "ours DOUBLE, ins DOUBLE, rel DOUBLE, reason VARCHAR)")
    db.execute("INSERT INTO kpi_total_checks VALUES ('DCKID', 'mismatch', '2024', 101.0, 59.0, 0.7, NULL), "
               "('SXKID', 'mismatch', '2024', 200.0, 150.0, 0.3, NULL)")
    db.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=build)


def rank(dataset, **kw):
    return call('rank_entities', dataset=dataset, entity_columns=['REF_AREA', 'REF_AREA_2'],
                entity_class='cities', lang='en', **kw)


def test_rank_entities_no_longer_ranks_the_double_count(env):
    r = rank('DCPAR')
    assert r['status'] == 'unavailable' and not r['data'].get('rows')
    assert r['reason'] in ('label_hierarchy', 'unverified_structure')
    assert '48' not in str(r['data'])                 # 10 + 30 + 8 is never a number


def test_rank_entities_with_the_non_subset_options_selected_sums(env):
    r = rank('DCPAR', filters={'SRC': [PUBLIC, PRIVATE]})
    assert r['status'] in ('ok', 'partial')
    assert [x['value'] for x in r['data']['rows']] == [44, 42, 40]


def test_rank_entities_refuses_the_subset_with_its_parent(env):
    r = rank('DCPAR', filters={'SRC': [PRIVATE, SUBSET]})
    assert r['status'] == 'unavailable'


def test_a_refused_child_does_not_offer_the_unchecked_parent(env):
    # SXKID: INS disagrees with the sum over SEX. SXPAR has no kpi_total_checks row.
    e = call('query_data', dataset='SXKID', group_by=['REF_AREA', 'TIME_PERIOD'], lang='en')
    assert e['status'] == 'unavailable' and e['reason'] == 'source_total_mismatch'
    offered = [r['arguments'].get('dataset') for r in e['recovery'] if r['tool'] == 'query_data']
    assert 'SXPAR' not in offered


def test_a_related_dataset_with_its_own_passing_check_is_still_offered(env):
    db = duckdb.connect(str(env.corpus / 'metadata.duckdb'))
    db.execute("INSERT INTO kpi_total_checks VALUES ('SXPAR', 'match', '2024', 200.0, 200.0, 0.0, NULL)")
    db.close()
    e = call('query_data', dataset='SXKID', group_by=['REF_AREA', 'TIME_PERIOD'], lang='en')
    assert e['reason'] == 'source_total_mismatch'
    assert [r['arguments']['dataset'] for r in e['recovery'] if r['tool'] == 'query_data'] == ['SXPAR']


def test_a_related_dataset_whose_own_check_failed_is_not_offered(env):
    db = duckdb.connect(str(env.corpus / 'metadata.duckdb'))
    db.execute("INSERT INTO kpi_total_checks VALUES ('SXPAR', 'mismatch', '2024', 200.0, 150.0, 0.3, NULL)")
    db.close()
    e = call('query_data', dataset='SXKID', group_by=['REF_AREA', 'TIME_PERIOD'], lang='en')
    assert not [r for r in e['recovery'] if r['tool'] == 'query_data']


# ---------------------------------------------------------------- corpus

@pytest.mark.corpus
def test_loc104a_bucuresti_2023_is_not_the_double_count():
    from app.services import generation
    if not str(generation.current().get('id') or '').startswith('062bd2b0'):
        pytest.skip('pinned to generation 062bd2b0')
    r = call('query_data', dataset='LOC104A', group_by=['REF_AREA', 'TIME_PERIOD'],
             filters={'TIME_PERIOD': ['2023']}, lang='en')
    assert r['status'] == 'unavailable' and r['reason'] == 'label_hierarchy'
    e = call('query_data', dataset='LOC104A', group_by=['REF_AREA', 'TIME_PERIOD'], lang='en',
             filters={'TIME_PERIOD': ['2023'], 'SURSE_DE_FINANTARE': ['Din fonduri publice', 'Din fonduri private']})
    assert e['status'] in ('ok', 'partial')
    assert '18654' not in str(r['data']).replace(',', '')
