"""AQ-03A: evidence coordinates of a result's numbers (endpoints, change metric, full entity key,
normalized unit, reviewed population definition) and what a claim may be bound to because of them.

Hand-built `tempo-tools/2` envelopes: the checker is a pure function of the trace, so each case
states exactly the cells it offers. The end-to-end Ask loop stays covered by test_at05_quality.py."""
import pytest

from app.services import agent, answer_check as A


def env(tool, data, *, dataset='D1', unit='Numar persoane', unit_type=None, sources=None, status='ok'):
    src = {'dataset': dataset, 'unit': unit, 'unit_type': unit_type}
    return {'id': 'c1', 'tool': tool, 'output': {
        'contract': 'tempo-tools/2', 'tool': tool, 'status': status, 'data': data,
        'provenance': {'sources': sources if sources is not None else [src],
                       'selection': {'kind': 'dataset', 'dataset': dataset, 'filters': {}}}}}


def change(rows, *, unit='Numar persoane', dataset='D1', **kw):
    return [env('compare_periods', {'dataset': dataset, 'unit': unit, 'metric': 'absolute',
                                    'intervals': [{'from': '2020', 'to': '2025', 'rows': rows}]},
                dataset=dataset, unit=unit, **kw)]


ROW = {'entity': {'REF_AREA': 'Cluj'}, 'from_value': 100.0, 'to_value': 140.0,
       'absolute': 40.0, 'percent': 40.0, 'rank': 1}


def bind(text, trace, question=''):
    return A.bind_claims(text, question, trace)


# --------------------------------------------------------------------- leaf coordinates

def test_change_leaves_keep_their_own_endpoint_year_and_metric():
    by = {lf['path'].rsplit('/', 1)[1]: lf for lf in A.numeric_leaves(change([ROW])[0]['output'], 'c9')}
    assert {lf['call'] for lf in by.values()} == {'c9'} and by['absolute']['path'] == '/data/intervals/0/rows/0/absolute'
    assert by['from_value']['metric'] == 'from_value' and by['from_value']['period'] == '2020'
    assert (by['from_value']['period_from'], by['from_value']['period_to']) == ('2020', '2020')
    assert by['to_value']['metric'] == 'to_value' and by['to_value']['period'] == '2025'
    assert (by['to_value']['period_from'], by['to_value']['period_to']) == ('2025', '2025')
    for name, metric in (('absolute', 'change_absolute'), ('percent', 'change_percent')):
        lf = by[name]
        assert lf['metric'] == metric and lf['period'] == '2020→2025'
        assert (lf['period_from'], lf['period_to']) == ('2020', '2025')
    assert by['absolute']['unit_norm']['measure'] == 'persons' and by['absolute']['unit'] == 'Numar persoane'
    assert by['percent']['unit_norm']['measure'] == 'percent' and by['percent']['unit'] == '%'


@pytest.mark.parametrize('text,year,expected', [
    ('Cluj avea 100 de persoane în 2020.', 'from', 'matched'),
    ('Cluj avea 140 de persoane în 2025.', 'to', 'matched'),
    ('Cluj avea 100 de persoane în 2025.', None, 'period_mismatch'),     # the 2020 value is not the 2025 one
    ('Cluj avea 140 de persoane în 2020.', None, 'period_mismatch'),
    ('In 2025, Cluj had 100 people.', None, 'period_mismatch'),
])
def test_an_endpoint_value_is_verified_only_for_its_own_year(text, year, expected):
    c = bind(text, change([ROW]))[0]
    if expected == 'matched':
        assert c['check'] == 'matched' and c['path'].endswith(f'/{year}_value') and c['metric'] == f'{year}_value'
    else:
        assert c['check'] == 'unverified' and c['reason'] == expected and c['path'] is None


def test_an_absolute_change_is_not_a_percent_change_and_the_reverse():
    t = change([ROW])
    absolute = bind('Cluj a crescut cu 40 de persoane între 2020 și 2025.', t)[0]
    percent = bind('Cluj a crescut cu 40% între 2020 și 2025.', t)[0]
    assert absolute['path'].endswith('/absolute') and absolute['metric'] == 'change_absolute'
    assert percent['path'].endswith('/percent') and percent['metric'] == 'change_percent'
    # the amount is a count of persons, the % a relative change: neither stands in for the other
    only_pct = change([{**ROW, 'absolute': 7.0}])
    wrong = bind('Cluj a crescut cu 40 de persoane între 2020 și 2025.', only_pct)[0]
    assert wrong['check'] == 'unverified' and wrong['reason'] == 'unit_mismatch'
    only_abs = change([{**ROW, 'percent': 7.0}])
    wrong = bind('Cluj a crescut cu 40% între 2020 și 2025.', only_abs)[0]
    assert wrong['check'] == 'unverified' and wrong['reason'] == 'unit_mismatch'


def test_percentage_points_stay_distinct_from_percent():
    rate = {'entity': {'REF_AREA': 'Cluj'}, 'from_value': 50.0, 'to_value': 84.0, 'absolute': 34.0,
            'percent': 68.0, 'rank': 1}
    t = change([rate], unit='Procente')
    lf = {x['path'].rsplit('/', 1)[1]: x for x in A.numeric_leaves(t[0]['output'])}
    assert lf['absolute']['unit_norm']['measure'] == 'percentage_points'     # difference of two rates
    assert lf['percent']['unit_norm']['measure'] == 'percent'                # relative change
    assert lf['to_value']['unit_norm']['measure'] == 'percent'
    ok = bind('Rata a crescut cu 34 puncte procentuale în Cluj.', t)[0]
    assert ok['check'] == 'matched' and ok['path'].endswith('/absolute')
    loose = bind('Rata a crescut cu 34% în Cluj.', t)[0]                     # "34%" is not "34 points"
    assert loose['check'] == 'unverified' and loose['reason'] == 'unit_unverified'
    assert loose['reason'] not in A.CONTRADICTIONS                           # unverifiable, not an accusation
    rel = bind('Rata a crescut cu 68% în Cluj.', t)[0]
    assert rel['check'] == 'matched' and rel['path'].endswith('/percent')
    # a relative change presented as points is explicit
    wrong = bind('Rata a crescut cu 68 de puncte procentuale în Cluj.', t)[0]
    assert wrong['check'] == 'unverified' and wrong['reason'] == 'unit_mismatch'


def test_two_currencies_and_scales_are_not_interchangeable():
    lei = [env('query_data', {'columns': ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'],
                              'rows': [['Cluj', '2025', 33.0]]}, unit='Milioane lei')]
    eur = [env('query_data', {'columns': ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'],
                              'rows': [['Cluj', '2025', 33.0]]}, unit='Milioane EURO')]
    assert bind('Cluj a avut 33 milioane lei în 2025.', lei)[0]['check'] == 'matched'
    assert bind('Cluj a avut 33 milioane euro în 2025.', eur)[0]['check'] == 'matched'
    for text, trace in (('Cluj a avut 33 milioane euro în 2025.', lei), ('Cluj a avut 33 milioane lei în 2025.', eur)):
        c = bind(text, trace)[0]
        assert c['check'] == 'unverified' and c['reason'] == 'unit_mismatch'
    # the stored 33.0 is millions: 33 000 000 lei is the same cell, a bare "33 lei" is a dropped scale
    assert bind('Cluj a avut 33000000 lei în 2025.', lei)[0]['check'] == 'matched'
    dropped = bind('Cluj a avut 33 lei în 2025.', lei)[0]
    assert dropped['check'] == 'unverified' and dropped['reason'] == 'scale_mismatch'
    assert dropped['reason'] not in A.CONTRADICTIONS


def test_a_thousands_source_is_matched_in_base_units_or_in_its_own():
    t = [env('query_data', {'columns': ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'],
                            'rows': [['Cluj', '2025', 560.3]]}, unit='Mii persoane')]
    lf = A.numeric_leaves(t[0]['output'])[0]
    assert lf['value'] == 560.3 and lf['scaled'] == 560300.0 and lf['unit_norm']['scale'] == 1000.0
    for text in ('Cluj avea 560,3 mii de persoane în 2025.', 'Cluj avea 560 300 de persoane în 2025.',
                 'Cluj had 560.3 thousand people in 2025.'):
        c = bind(text, t)[0]
        assert c['check'] == 'matched', text
    c = bind('Cluj avea 560,3 persoane în 2025.', t)[0]
    assert c['check'] == 'unverified' and c['reason'] == 'scale_mismatch'
    assert A.uncited_numbers('560 300 de persoane', [t[0]['output']]) == []     # the same value, base units


def test_unknown_and_unstated_units_are_never_an_accusation():
    odd = [env('query_data', {'columns': ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'],
                              'rows': [['Cluj', '2025', 12.5]]}, unit='Mii tone echivalent petrol')]
    assert A.numeric_leaves(odd[0]['output'])[0]['unit_norm']['known'] is False
    c = bind('Cluj a avut 12,5% în 2025.', odd)[0]
    assert c['check'] == 'unverified' and c['reason'] == 'unit_unverified'
    assert bind('Cluj a avut 12,5 în 2025.', odd)[0]['check'] == 'matched'          # no unit stated


# --------------------------------------------------------------------- full entity keys

def ranking(rows):
    return [env('rank_entities', {'dataset': 'POP107D_grupe_localitate', 'year': '2025', 'unit': 'Numar persoane',
                                  'entity_columns': ['REF_AREA', 'REF_AREA_2'], 'rows': rows,
                                  'eligible_count': len(rows), 'outside_class_count': 7},
                dataset='POP107D_grupe_localitate', unit='Numar persoane')]


def test_ranking_values_keep_the_full_key_whatever_the_dictionary_order():
    one = {'entity': {'REF_AREA': 'Cluj', 'REF_AREA_2': '54975 MUNICIPIUL ALFA'}, 'value': 100.0, 'rank': 1}
    two = {'entity': {'REF_AREA_2': '59999 ORASUL BETA', 'REF_AREA': 'Alba'}, 'value': 100.0, 'rank': 2}
    lv = A.numeric_leaves(ranking([one, two])[0]['output'])
    assert [lf['path'] for lf in lv] == ['/data/rows/0/value', '/data/rows/1/value']      # not rank / counts
    assert lv[0]['key'] == {'REF_AREA': 'Cluj', 'REF_AREA_2': '54975 MUNICIPIUL ALFA'}
    assert lv[1]['key'] == {'REF_AREA': 'Alba', 'REF_AREA_2': '59999 ORASUL BETA'}
    assert list(lv[1]['key']) == ['REF_AREA', 'REF_AREA_2']                               # order-independent
    assert lv[0]['entity'] == ['54975 MUNICIPIUL ALFA'] and lv[1]['entity'] == ['59999 ORASUL BETA']
    t = ranking([one, two])
    a = bind('Alfa are 100 de persoane în 2025.', t)[0]
    b = bind('Beta are 100 de persoane în 2025.', t)[0]
    assert (a['check'], a['path']) == ('matched', '/data/rows/0/value')                    # equal values, own keys
    assert (b['check'], b['path']) == ('matched', '/data/rows/1/value')
    county = bind('Județul Cluj are 100 de persoane în 2025.', t)[0]                     # a county is not its city
    assert county['check'] == 'unverified'


def test_change_rows_of_a_locality_are_named_by_the_locality_not_its_county():
    row = {'entity': {'REF_AREA': 'Cluj', 'REF_AREA_2': '54975 MUNICIPIUL ALFA'}, 'from_value': 100.0,
           'to_value': 140.0, 'absolute': 40.0, 'percent': 40.0, 'rank': 1}
    lv = A.numeric_leaves(change([row])[0]['output'])
    assert {tuple(lf['entity']) for lf in lv} == {('54975 MUNICIPIUL ALFA',)}
    assert all(lf['key'] == {'REF_AREA': 'Cluj', 'REF_AREA_2': '54975 MUNICIPIUL ALFA'} for lf in lv)
    assert bind('Cluj a crescut cu 40 de persoane.', change([row]))[0]['check'] == 'unverified'
    assert bind('Alfa a crescut cu 40 de persoane.', change([row]))[0]['check'] == 'matched'


def test_metadata_fields_ranks_and_siruta_codes_are_not_measurement_claims():
    q = env('query_data', {'columns': ['REF_AREA', 'REF_AREA_2', 'SIRUTA', 'TIME_PERIOD', 'OBS_VALUE', 'RANK'],
                           'rows': [['Cluj', '54975 MUNICIPIUL ALFA', 54975, '2025', 100.0, 3]]})
    assert [lf['value'] for lf in A.numeric_leaves(q['output'])] == [100.0]
    for number in (54975, 3):
        assert A.result_values([q['output']]).count(float(number)) == 0
    r = ranking([{'entity': {'REF_AREA': 'Cluj', 'REF_AREA_2': '54975 MUNICIPIUL ALFA'}, 'value': 100.0, 'rank': 1}])
    assert A.result_values([r[0]['output']]) == [100.0]         # not rank, eligible_count or outside_class_count


def test_a_unit_measure_column_gives_the_row_its_unit_and_is_not_an_entity_name():
    q = [env('query_data', {'columns': ['UNIT_MEASURE', 'TIME_PERIOD', 'OBS_VALUE'],
                            'rows': [['Mii persoane', '2025', 5.0], ['Procente', '2025', 5.0]]}, unit=None)]
    lv = A.numeric_leaves(q[0]['output'])
    assert [lf['unit_norm']['measure'] for lf in lv] == ['persons', 'percent']
    assert lv[0]['entity'] == [] and lv[0]['key'] == {'UNIT_MEASURE': 'Mii persoane'}
    assert lv[0]['scaled'] == 5000.0 and lv[1]['scaled'] is None


# --------------------------------------------------------------------- population definition

@pytest.mark.parametrize('dataset,expected', [
    ('POP105A_judete_grupe', 'resident'),           # reviewed concept family POP105A
    ('POP106A_judete_grupe', 'resident'),
    ('POP107A_judete_grupe', 'domicile'),
    ('POP107D_grupe_localitate', 'domicile'),       # the locality series of the AT-05 city ranking
    ('TUR105D_judete', None),
    ('POP999Z', None),                               # nothing reviewed says what it counts
])
def test_population_definition_comes_only_from_a_reviewed_mapping(dataset, expected):
    q = env('query_data', {'columns': ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'], 'rows': [['Cluj', '2025', 5.0]]},
            dataset=dataset)
    assert A.numeric_leaves(q['output'])[0]['population'] == expected


def test_a_title_that_contains_the_word_classifies_nothing():
    src = {'dataset': 'POP999Z', 'unit': 'Numar persoane', 'metric': 'Populația după domiciliu (titlu)',
           'definition': 'Persoane cu domiciliul legal în zonă'}
    q = env('query_data', {'columns': ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'], 'rows': [['Cluj', '2025', 700000.0]]},
            dataset='POP999Z', sources=[src])
    assert A.numeric_leaves(q['output'])[0]['population'] is None


def population_trace(dataset):
    return [env('query_data', {'columns': ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'],
                               'rows': [['Cluj', '2025', 700000.0]]}, dataset=dataset)]


def test_a_stated_definition_must_be_the_cells_reviewed_definition():
    text = 'Populația după domiciliu a județului Cluj era de 700000 de persoane în 2025.'
    assert bind(text, population_trace('POP107A_judete_grupe'))[0]['check'] == 'matched'
    wrong = bind(text, population_trace('POP105A_judete_grupe'))[0]                # it is the resident count
    assert wrong['check'] == 'unverified' and wrong['reason'] == 'definition_mismatch'
    unknown = bind(text, population_trace('POP999Z'))[0]                           # unclassified proves nothing
    assert unknown['check'] == 'unverified' and unknown['reason'] == 'definition_unverified'
    assert {wrong['reason'], unknown['reason']}.isdisjoint(A.CONTRADICTIONS)
    said = 'Cluj had a resident population of 700000 in 2025.'          # plain "residents" is just inhabitants
    assert bind(said, population_trace('POP105A_judete_grupe'))[0]['check'] == 'matched'
    assert bind(said, population_trace('POP107A_judete_grupe'))[0]['reason'] == 'definition_mismatch'
    assert bind('Cluj had 700000 residents in 2025.', population_trace('POP999Z'))[0]['check'] == 'matched'


def test_an_explicitly_requested_definition_needs_a_classified_source():
    ask = 'Care este populația după domiciliu a județului Cluj în 2025?'
    text = 'Cluj avea 700000 de locuitori în 2025.'                                  # the answer itself is silent
    assert bind(text, population_trace('POP107A_judete_grupe'), ask)[0]['check'] == 'matched'
    assert bind(text, population_trace('POP105A_judete_grupe'), ask)[0]['reason'] == 'definition_mismatch'
    assert bind(text, population_trace('POP999Z'), ask)[0]['reason'] == 'definition_unverified'
    # nothing was requested: nothing to prove, so an unclassified source is not penalised
    assert bind(text, population_trace('POP999Z'), 'Câți locuitori are Cluj?')[0]['check'] == 'matched'
    # a question that names both definitions requests neither
    both = 'Compară populația rezidentă și cea după domiciliu din Cluj.'
    assert bind(text, population_trace('POP999Z'), both)[0]['check'] == 'matched'


def test_a_per_resident_phrase_is_a_denominator_not_a_definition_claim():
    t = [env('run_recipe', {'year': '2025', 'recipe': {'id': 'tourism_intensity', 'unit': 'înnoptări pe locuitor'},
                            'rows': [{'label': 'Brasov', 'geo_id': 'brasov', 'value': 4.91}]},
             dataset=None, unit=None,
             sources=[{'dataset': 'TUR105D_judete', 'role': 'stays', 'concept': 'tourist_overnight_stays'},
                      {'dataset': 'POP105A_judete_grupe', 'role': 'population', 'concept': 'resident_population'}])]
    lf = A.numeric_leaves(t[0]['output'])[0]
    assert lf['population'] == 'resident' and lf['unit_norm']['denominator'] == 'person'
    assert bind('Brașov: 4,91 înnoptări per resident în 2025.', t)[0]['check'] == 'matched'
    wrong = bind('Brașov: 4,91 înnoptări pe locuitor, la populația după domiciliu, în 2025.', t)[0]
    assert wrong['check'] == 'unverified' and wrong['reason'] == 'definition_mismatch'


# --------------------------------------------------------------------- unit normalization

@pytest.mark.parametrize('text,measure,currency,scale,den', [
    ('Numar persoane', 'persons', None, 1.0, None),
    ('Mii persoane', 'persons', None, 1000.0, None),
    ('Numar', 'count', None, 1.0, None),
    ('Procente', 'percent', None, 1.0, None),
    ('Lei', 'currency', 'RON', 1.0, None),
    ('Milioane lei RON', 'currency', 'RON', 1e6, None),
    ('Miliarde lei', 'currency', 'RON', 1e9, None),
    ('Milioane EURO', 'currency', 'EUR', 1e6, None),
    ('Mii dolari (USD)', 'currency', 'USD', 1e3, None),
    ('Lei / persoana', 'currency', 'RON', 1.0, 'person'),
    ('înnoptări pe locuitor', 'stays', None, 1.0, 'person'),
    ('overnight stays per resident', 'stays', None, 1.0, 'person'),
    ('Hectare', 'area_ha', None, 1.0, None),
    ('Puncte procentuale', 'percentage_points', None, 1.0, None),
    ('Decedati la 1000 locuitori', None, None, None, 'thousand_persons'),
])
def test_supported_source_units_are_normalized(text, measure, currency, scale, den):
    u = A.normalize_unit(text)
    assert (u['measure'], u['currency'], u['scale'], u['denominator']) == (measure, currency, scale, den)
    assert u['known'] is True


@pytest.mark.parametrize('text', ['Kilometri', 'Mii', 'Tone', 'Numar locuri-zile', 'Persoane la 100000 locuitori',
                                  'Mii lei preturile anului 2020/tona', '', None])
def test_other_units_stay_unknown(text):
    u = A.normalize_unit(text)
    assert u['known'] is False and u['measure'] is None and u['scale'] is None


def test_hectares_are_not_square_kilometres_and_the_profile_type_is_only_a_hint():
    ha = A.normalize_unit('Hectare')
    km = A.normalize_unit('Kilometri patrati')
    assert (ha['measure'], km['measure']) == ('area_ha', 'area_km2')
    assert A.normalize_unit(None, 'percentage')['measure'] == 'percent'
    assert A.normalize_unit(None, 'area')['known'] is False and A.normalize_unit('Hectare', 'count')['measure'] == 'area_ha'
    t = [env('query_data', {'columns': ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'], 'rows': [['Cluj', '2025', 120.0]]},
             unit='Hectare')]
    assert bind('Cluj are 120 ha în 2025.', t)[0]['check'] == 'matched'
    km2 = bind('Cluj are 120 km² în 2025.', t)[0]
    assert km2['check'] == 'unverified' and km2['reason'] == 'unit_mismatch'


# --------------------------------------------------------------------- the agent's withholding set

def test_only_explicit_contradictions_withhold_prose():
    assert A.CONTRADICTIONS == {'unit_mismatch', 'period_mismatch'}
    rate = {'entity': {'REF_AREA': 'Cluj'}, 'from_value': 50.0, 'to_value': 84.0, 'absolute': 34.0,
            'percent': 68.0, 'rank': 1}
    cases = [(change([ROW]), 'Cluj avea 100 de persoane în 2025.', 'claim_mismatch'),          # explicit year
             (change([ROW]), 'Cluj a crescut cu 40 de lei între 2020 și 2025.', 'claim_mismatch'),   # explicit unit
             (change([rate], unit='Procente'), 'Cluj: rata a crescut cu 34% (puncte?).', 'unverified_numbers'),
             (change([ROW]), 'Cluj avea 100 de persoane în 2020.', 'verified')]
    for trace, text, status in cases:
        run = agent._Run.__new__(agent._Run)
        run.lang, run.question, run.trace, run.warnings, run.on_event = 'ro', '', trace, [], None
        answer, ver = run._check_answer(text)
        assert ver['status'] == status, (text, ver['claims'])
        assert (answer == text) == (status != 'claim_mismatch')
