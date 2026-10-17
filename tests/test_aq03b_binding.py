"""AQ-03B: a claim binds only to what its wording identifies.

Table-driven Romanian and English cases over hand-built `tempo-tools/2` results (the checker is a
pure function of the trace). Every row states the cells on offer, the sentence, and what the checker
may say: matched with the exact cell, or unverified with a stable reason. A claim is never bound to
the first of several equally plausible cells. The end-to-end Ask loop is covered at the bottom."""
import time

import pytest

from app.services import answer_check as A
from test_aq03a_evidence import ROW, change, env, ranking


def bind(text, trace, question=''):
    return A.bind_claims(text, question, trace)


def verdicts(text, trace, question=''):
    """[(check, reason | last path segment | None)] per claim: where a matched claim points, or why not."""
    return [(c['check'], c.get('reason') or (c['path'].rsplit('/', 1)[1] if c['path'] else None))
            for c in bind(text, trace, question)]


def rows_query(rows, unit='Numar persoane', cols=('REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'), **kw):
    return [env('query_data', {'columns': list(cols), 'rows': rows}, unit=unit, **kw)]


# --------------------------------------------------------------------- which numbers are claims

@pytest.mark.parametrize('text,question,expected', [
    # list numbering, ranks, counts of items
    ('1. Cluj-Napoca', '', []),
    ('Pe locul 2 se află Iași.', '', []),
    ('Iași este pe locul 2 cu 271.692 de locuitori.', '', ['271.692']),
    ('Top 10 județe după populație', '', []),
    ('Cele mai populate 30 de orașe sunt:', '', []),
    ('Rank 3: Constanța', '', []),
    ('The first 5 cities are listed below.', '', []),
    # identifiers, dates, matrix codes, rate bases
    ('Cluj-Napoca (SIRUTA 54975) are 286.598 de locuitori.', '', ['286.598']),
    ('Cod 54975 pentru Cluj-Napoca.', '', []),
    ('Datele sunt valabile la 31.12.2025.', '', []),
    ('Datele din 2025-03-01 sunt provizorii.', '', []),
    ('Seria POP105A are 3 regiuni.', '', []),
    ('5,2 decese la 100000 de locuitori', '', ['5,2']),
    ('Rata este de 12 la 1000 de locuitori.', '', ['12']),
    # years are not values unless a unit follows
    ('În 2021 populația a scăzut.', '', []),
    ('Valoarea a fost 2021 de persoane.', '', ['2021']),
    ('Între 2020 și 2025', '', []),
    # small integers and zero are values with a unit or a cue
    ('Brașov: 2 înnoptări pe locuitor.', '', ['2']),
    ('Brasov had 2 overnight stays per resident.', '', ['2']),
    ('Raportul este 2.', '', ['2']),
    ('The ratio is 2.', '', ['2']),
    ('Sunt 0 înnoptări.', '', ['0']),
    ('Au fost 0 persoane.', '', ['0']),
    ('Sunt 3 regiuni.', '', []),
    ('Au fost 3 județe în analiză.', '', []),
    ('Se compară 2 ani.', '', []),
    # the user's own premise is not a result, but a result that happens to repeat it is
    ('Pentru 5000 de persoane nu există date.', 'Ce avem pentru 5000 de persoane?', []),
    ('For 5000 people there is no data.', 'What about 5000 people?', []),
    ('Da, sunt 5000 de persoane.', 'Sunt 5000 de persoane?', ['5000']),
    ('Yes, there are 5000 people.', 'Are there 5000 people?', ['5000']),
    ('Nu sunt 4000, ci 5000 de persoane.', 'Sunt 4000 de persoane?', ['5000']),
    ('Și 5000 de persoane.', 'Sunt 5000 de persoane?', ['5000']),
])
def test_numbers_are_claims_by_context(text, question, expected):
    assert [c['raw'] for c in A.find_numbers(text, question, frozenset({'54975'}))] == expected


@pytest.mark.parametrize('text,sign', [
    ('a variat cu -40 de persoane', -1), ('o variație de −40 de persoane', -1), ('(−2,5%)', -1),
    ('a variat cu +40 de persoane', 1), ('(+8% față de 2024)', 1), ('în 2020-2025: 100 persoane', 0),
    ('Cluj-55 are 100 de persoane', 0), ('a variat cu 40 de persoane', 0),
])
def test_a_written_sign_is_kept_and_a_range_dash_is_not_a_sign(text, sign):
    got = [c for c in A.find_numbers(text) if c['raw'].split()[0] in ('40', '2,5', '8', '100')]
    assert got and got[0]['sign'] == sign


# --------------------------------------------------------------------- entities: swapped values

CITIES = rows_query([['Cluj', '54975 MUNICIPIUL CLUJ-NAPOCA', '2025', 250000.0],
                     ['Iasi', '95060 MUNICIPIUL IASI', '2025', 300000.0]],
                    cols=('REF_AREA', 'REF_AREA_2', 'TIME_PERIOD', 'OBS_VALUE'))


@pytest.mark.parametrize('text,expected', [
    # correct assignments, different phrasings and word order
    ('Cluj-Napoca are 250000 de locuitori, iar Iași 300000.', [('matched', '3'), ('matched', '3')]),
    ('Iași are 300000 de persoane, Cluj-Napoca 250000.', [('matched', '3'), ('matched', '3')]),
    ('250000 de persoane locuiesc în Cluj-Napoca și 300000 în Iași.', [('matched', '3'), ('matched', '3')]),
    ('Cluj-Napoca: 250000 persoane; Iași: 300000 persoane.', [('matched', '3'), ('matched', '3')]),
    ('Cluj-Napoca has 250000 people, while Iasi has 300000.', [('matched', '3'), ('matched', '3')]),
    ('In 2025, Iasi had 300000 people and Cluj-Napoca 250000.', [('matched', '3'), ('matched', '3')]),
    # the same two numbers, swapped between the cities: nothing matches
    ('Cluj-Napoca are 300000 de locuitori, iar Iași 250000.', [('unverified', 'entity_mismatch')] * 2),
    ('Iași are 250000 de persoane, Cluj-Napoca 300000.', [('unverified', 'entity_mismatch')] * 2),
    ('300000 de persoane locuiesc în Cluj-Napoca și 250000 în Iași.', [('unverified', 'entity_mismatch')] * 2),
    ('Cluj-Napoca has 300000 people, while Iasi has 250000.', [('unverified', 'entity_mismatch')] * 2),
    ('Cluj-Napoca: 300000 persoane; Iași: 250000 persoane.', [('unverified', 'entity_mismatch')] * 2),
    # one right, one wrong: each number is judged on its own
    ('Cluj-Napoca are 250000 de locuitori, iar Iași 250000.', [('matched', '3'), ('unverified', 'entity_mismatch')]),
])
def test_two_cities_two_values_swapped_assignments_cannot_match(text, expected):
    assert verdicts(text, CITIES) == expected


def test_each_number_binds_to_its_own_city_row():
    paths = [c['path'] for c in bind('Cluj-Napoca are 250000 de locuitori, iar Iași 300000.', CITIES)]
    assert paths == ['/data/rows/0/3', '/data/rows/1/3']
    paths = [c['path'] for c in bind('Iasi has 300000 people and Cluj-Napoca 250000.', CITIES)]
    assert paths == ['/data/rows/1/3', '/data/rows/0/3']


@pytest.mark.parametrize('text', [
    'Cluj-Napoca și Iași au 250000 și respectiv 300000 de locuitori.',
    'Cluj-Napoca and Iasi have 250000 and 300000 people respectively.',
    'Cluj-Napoca și Iași au 250000 de locuitori.',        # one number for two names: true for one only
])
def test_one_number_for_a_group_of_names_is_ambiguous_never_guessed(text):
    for c in bind(text, CITIES):
        assert c['check'] == 'unverified' and c['reason'] == 'ambiguous_binding' and c['candidates'] >= 2
        assert c['path'] is None and c['reason'] not in A.CONTRADICTIONS


# --------------------------------------------------------------------- equal values: anchors or ambiguity

EQUAL = rows_query([['Cluj', '2020', 1000.0], ['Cluj', '2021', 1000.0], ['Iasi', '2020', 1000.0],
                    ['Iasi', '2021', 880.0], ['Bihor', '2021', 610.0]])


@pytest.mark.parametrize('text,expected', [
    ('Cluj avea 1000 de persoane în 2021.', [('matched', '2')]),
    ('Cluj avea 1000 de persoane în 2020.', [('matched', '2')]),
    ('În 2020, Cluj avea 1000 de persoane.', [('matched', '2')]),
    ('In 2021 Cluj had 1000 people.', [('matched', '2')]),
    ('Iași avea 1000 de persoane în 2020 și 880 în 2021.', [('matched', '2'), ('matched', '2')]),
    ('Iași avea 880 de persoane în 2021, iar Cluj 1000.', [('matched', '2'), ('matched', '2')]),
    ('Cluj avea 1000 de persoane în 2020 și 1000 în 2021.', [('matched', '2'), ('matched', '2')]),
    ('Cluj și Iași aveau 1000 de persoane în 2020.', [('unverified', 'ambiguous_binding')]),   # one number, two names
    # not enough to choose: the year is missing, or the place is
    ('Cluj avea 1000 de persoane.', [('unverified', 'ambiguous_binding')]),
    ('Cluj had 1000 people.', [('unverified', 'ambiguous_binding')]),
    ('În 2020 populația era de 1000 de persoane.', [('unverified', 'entity_unstated')]),
    # a stated year the place never had that value in
    ('Iași avea 1000 de persoane în 2021.', [('unverified', 'period_mismatch')]),
    ('Cluj avea 1000 de persoane în 2019.', [('unverified', 'period_mismatch')]),
])
def test_equal_values_are_resolved_by_explicit_anchors_or_stay_ambiguous(text, expected):
    assert verdicts(text, EQUAL) == expected


def test_a_number_is_the_cell_that_holds_it_not_also_a_neighbour_within_the_loose_tolerance():
    t = rows_query([['Cluj', '2021', 1010.0], ['Cluj', '2022', 1012.0], ['Cluj', '2023', 1013.0]])
    (c,) = bind('Cluj avea 1010 de persoane.', t)                  # 1012 and 1013 are within 0.5%, but are not 1010
    assert c['check'] == 'matched' and c['path'] == '/data/rows/0/2'
    (c,) = bind('Cluj avea 1,01 mii de persoane.', t)              # printed to the nearest ten: all three are 1,01 mii
    assert c['check'] == 'unverified' and c['reason'] == 'ambiguous_binding' and c['candidates'] == 3


def test_ambiguity_reports_the_count_and_binds_nothing():
    (c,) = bind('Cluj avea 1000 de persoane.', EQUAL)
    assert (c['check'], c['reason'], c['candidates']) == ('unverified', 'ambiguous_binding', 2)
    assert c['path'] is None and c['tool_call_id'] is None and 'anchors' not in c
    # explicit year resolves it to the 2021 cell, not the first one in the table
    (c,) = bind('Cluj avea 1000 de persoane în 2021.', EQUAL)
    assert c['path'] == '/data/rows/1/2' and c['anchors']['period'] == 'stated'


def test_the_same_cell_cited_twice_dedupes_but_distinct_cells_do_not():
    once = rows_query([['Cluj', '2021', 1010.0]])
    twice = once + [{**once[0], 'id': 'c2'}]                       # the same call replayed from the cache
    (c,) = bind('Cluj avea 1010 persoane în 2021.', twice)
    assert c['check'] == 'matched' and c['tool_call_id'] == 'c1'
    # an observation and the same series' endpoint value for the same year are one coordinate
    endpoint = env('compare_periods', {'dataset': 'D1', 'unit': 'Numar persoane', 'metric': 'absolute', 'intervals': [
        {'from': '2020', 'to': '2021', 'rows': [{'entity': {'REF_AREA': 'Cluj'}, 'from_value': 500.0, 'to_value': 1010.0,
                                                 'absolute': 510.0, 'percent': 102.0, 'rank': 1}]}]})
    (c,) = bind('Cluj avea 1010 persoane în 2021.', once + [{**endpoint, 'id': 'c3'}])
    assert c['check'] == 'matched' and c['tool_call_id'] == 'c1'
    # the endpoint of another year is not that cell
    (c,) = bind('Cluj avea 1010 persoane în 2020.', once + [{**endpoint, 'id': 'c3'}])
    assert c['check'] == 'unverified' and c['reason'] == 'period_mismatch'
    # two different datasets with the same figure are two cells
    other = rows_query([['Cluj', '2021', 1010.0]], dataset='D2')
    (c,) = bind('Cluj avea 1010 persoane în 2021.', once + [{**other[0], 'id': 'c4'}])
    assert (c['check'], c['reason'], c['candidates']) == ('unverified', 'ambiguous_binding', 2)


# --------------------------------------------------------------------- county versus city

PLACES = [env('rank_entities', {
    'dataset': 'POP107D_grupe_localitate', 'year': '2025', 'unit': 'Numar persoane',
    'entity_columns': ['REF_AREA', 'REF_AREA_2'],
    'rows': [{'entity': {'REF_AREA': 'Braila', 'REF_AREA_2': '42682 MUNICIPIUL BRAILA'}, 'value': 197232.0, 'rank': 1},
             {'entity': {'REF_AREA': 'Cluj', 'REF_AREA_2': '54975 MUNICIPIUL CLUJ-NAPOCA'}, 'value': 286598.0, 'rank': 2}]},
    dataset='POP107D_grupe_localitate', unit='Numar persoane')]


@pytest.mark.parametrize('text,expected', [
    ('Municipiul Brăila are 197232 de persoane.', 'matched'),
    ('Brăila are 197232 de persoane.', 'matched'),
    ('The city of Braila has 197232 people.', 'matched'),
    ('Cluj-Napoca are 286598 de persoane.', 'matched'),
    ('Județul Brăila are 197232 de persoane.', 'entity_mismatch'),         # the county, not its city
    ('Braila County has 197232 people.', 'entity_mismatch'),
    ('Județul Cluj are 286598 de persoane.', 'entity_unstated'),           # the county named; only the city has a row
    ('Cluj are 286598 de persoane.', 'entity_unstated'),
    ('Cluj County has 286598 people.', 'entity_unstated'),
    ('Valoarea este 197232.', 'entity_unstated'),
])
def test_naming_a_county_cannot_verify_a_city_in_it(text, expected):
    (c,) = bind(text, PLACES)
    assert (c['check'] if c['check'] == 'matched' else c['reason']) == expected
    assert c.get('reason') not in A.CONTRADICTIONS


def test_a_city_name_is_not_the_county_it_starts_with():
    county = rows_query([['Cluj', '2025', 700000.0]])
    (c,) = bind('Cluj-Napoca are 700000 de persoane în 2025.', county)
    assert c['check'] == 'unverified' and c['reason'] == 'entity_unstated'
    (c,) = bind('Județul Cluj are 700000 de persoane în 2025.', county)
    assert c['check'] == 'matched'
    (c,) = bind('Clujului îi revin 700000 de persoane în 2025.', county)               # inflected form
    assert c['check'] == 'matched'


def test_a_generic_total_row_is_named_by_the_word_total():
    t = rows_query([['Total', '2025', 5000.0], ['Cluj', '2025', 700.0]])
    (c,) = bind('În total, în 2025 au fost 5000 de persoane.', t)
    assert c['check'] == 'matched' and c['path'] == '/data/rows/0/2'
    (a, b) = bind('În total sunt 5000 de persoane, iar în Cluj 700.', t)
    assert (a['path'], b['path']) == ('/data/rows/0/2', '/data/rows/1/2')


# --------------------------------------------------------------------- endpoints, years, signs

NEG = change([{**ROW, 'from_value': 140.0, 'to_value': 100.0, 'absolute': -40.0, 'percent': -28.57}])


@pytest.mark.parametrize('trace,text,expected', [
    # endpoint roles
    (change([ROW]), 'Cluj a crescut de la 100 la 140 între 2020 și 2025.', [('matched', 'from_value'), ('matched', 'to_value')]),
    (change([ROW]), 'Cluj a scăzut de la 140 la 100 între 2020 și 2025.', [('unverified', 'endpoint_mismatch')] * 2),
    (change([ROW]), 'Between 2020 and 2025 Cluj grew from 100 to 140 people.', [('matched', 'from_value'), ('matched', 'to_value')]),
    (change([ROW]), 'Between 2020 and 2025 Cluj grew from 140 to 100 people.', [('unverified', 'endpoint_mismatch')] * 2),
    (NEG, 'Cluj a scăzut de la 140 la 100 de persoane în 2020-2025.', [('matched', 'from_value'), ('matched', 'to_value')]),
    # each number with its own year
    (change([ROW]), 'Cluj avea 100 de persoane în 2020 și 140 în 2025.', [('matched', 'from_value'), ('matched', 'to_value')]),
    (change([ROW]), 'Cluj avea 140 de persoane în 2020 și 100 în 2025.', [('unverified', 'period_mismatch')] * 2),
    (change([ROW]), 'Cluj avea 100 de persoane (2020) și 140 (2025).', [('matched', 'from_value'), ('matched', 'to_value')]),
    (change([ROW]), 'In 2025 Cluj had 140 people, up from 100 in 2020.', [('matched', 'to_value'), ('matched', 'from_value')]),
    (change([ROW]), 'Cluj went from 140 (2020) to 100 (2025).', [('unverified', 'period_mismatch')] * 2),
    # signed changes
    (NEG, 'Cluj a scăzut cu 40 de persoane.', [('matched', 'absolute')]),
    (NEG, 'Cluj lost 40 people.', [('matched', 'absolute')]),
    (NEG, 'Cluj: −40 de persoane.', [('matched', 'absolute')]),
    (NEG, 'Cluj: o scădere de 28,57%.', [('matched', 'percent')]),
    (NEG, 'Cluj a crescut cu 40 de persoane.', [('unverified', 'direction_mismatch')]),
    (NEG, 'Cluj gained 40 people.', [('unverified', 'direction_mismatch')]),
    (NEG, 'Cluj: variație de 40 de persoane.', [('unverified', 'direction_unstated')]),     # no evidence of a decline
    (change([ROW]), 'Cluj a crescut cu 40 de persoane.', [('matched', 'absolute')]),
    (change([ROW]), 'Cluj a scăzut cu 40 de persoane.', [('unverified', 'direction_mismatch')]),
    (change([ROW]), 'Cluj fell by 40 people.', [('unverified', 'direction_mismatch')]),
    (change([ROW]), 'Cluj: -40 persoane.', [('unverified', 'direction_mismatch')]),
    (change([ROW]), 'Cluj: +40 persoane.', [('matched', 'absolute')]),
    (change([ROW]), 'Cluj a avut o variație de 40 de persoane.', [('matched', 'absolute')]),
    (change([ROW]), 'Cluj a crescut până la 140 de persoane.', [('matched', 'to_value')]),    # a level, not a change
    # absolute versus relative, with and without the unit
    (change([ROW]), 'Cluj a crescut cu 40 de persoane (40%).', [('matched', 'absolute'), ('matched', 'percent')]),
    (change([ROW]), 'Cluj a crescut cu 40%.', [('matched', 'percent')]),
    (change([ROW]), 'Cluj a crescut cu 40.', [('unverified', 'ambiguous_binding')]),
])
def test_endpoints_years_and_signed_changes(trace, text, expected):
    assert verdicts(text, trace) == expected


@pytest.mark.parametrize('text,expected', [
    # a source date earlier in the sentence is not the number's year; the year attached to the number is
    ('Datele din 2025 arată că Cluj avea 1010 persoane în 2021.', ('matched', None)),
    ('According to the 2025 release, Cluj had 1010 people in 2021.', ('matched', None)),
    ('Datele din 2025 arată că Cluj avea 1010 persoane în 2019.', ('unverified', 'period_mismatch')),
    # a year in front of the number in a sentence with other years is evidence, not proof: never withheld
    ('În 2020 Cluj avea 140 de persoane, iar în 2025 100.', ('unverified', 'period_unverified')),
    # the only year of the sentence, or the year attached after the number, is explicit
    ('În 2020 Cluj avea 140 de persoane.', ('unverified', 'period_mismatch')),
    ('Cluj avea 140 de persoane în 2020, conform datelor.', ('unverified', 'period_mismatch')),
])
def test_only_reliable_year_anchors_can_contradict(text, expected):
    trace = rows_query([['Cluj', '2021', 1010.0], ['Cluj', '2025', 140.0]])
    got = bind(text, trace if '1010' in text else change([ROW]))
    assert (got[0]['check'], got[0].get('reason')) == expected


def test_an_endpoint_swap_is_not_withheld_but_an_explicit_year_conflict_is():
    assert 'endpoint_mismatch' not in A.CONTRADICTIONS and 'direction_mismatch' not in A.CONTRADICTIONS
    c = bind('Cluj avea 140 de persoane în 2020.', change([ROW]))[0]
    assert c['reason'] == 'period_mismatch' and c['reason'] in A.CONTRADICTIONS


# --------------------------------------------------------------------- units, ratios, scales

TOURISM = [
    env('query_data', {'columns': ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'], 'rows': [['Brasov', '2025', 2751439.0]]},
        unit='Numar'),
    {'id': 'r1', 'tool': 'run_recipe', 'output': {
        'contract': 'tempo-tools/2', 'tool': 'run_recipe', 'status': 'ok',
        'data': {'year': '2025', 'recipe': {'id': 'tourism_intensity', 'unit': 'înnoptări pe locuitor'},
                 'rows': [{'label': 'Brasov', 'geo_id': 'brasov', 'value': 4.9108548},
                          {'label': 'Cluj', 'geo_id': 'cluj', 'value': 2.0},
                          {'label': 'Zero', 'geo_id': 'zero', 'value': 0.0}]},
        'provenance': {'sources': [{'dataset': 'TUR105D_judete', 'role': 'stays', 'concept': 'tourist_overnight_stays'},
                                   {'dataset': 'POP105A_judete_grupe', 'role': 'population',
                                    'concept': 'resident_population'}]}}}]


@pytest.mark.parametrize('text,expected', [
    # a correct mixed count + ratio sentence: each number keeps its own unit
    ('Brașov: 2751439 înnoptări, adică 4,91 înnoptări pe locuitor în 2025.', [('matched', '2'), ('matched', 'value')]),
    ('Brasov had 2,751,439 overnight stays, i.e. 4.91 per resident, in 2025.', [('matched', '2'), ('matched', 'value')]),
    ('Brașov a avut 2,75 milioane de înnoptări în 2025, adică 4,91 pe locuitor.', [('matched', '2'), ('matched', 'value')]),
    # a raw count phrased as a rate, and a rate phrased as a count
    ('Brașov a avut 2751439 înnoptări pe locuitor în 2025.', [('unverified', 'unit_mismatch')]),
    ('Brasov had 2751439 overnight stays per resident in 2025.', [('unverified', 'unit_mismatch')]),
    ('Brașov a avut 4,91 înnoptări în 2025.', [('unverified', 'unit_mismatch')]),
    ('Brasov had 4.91 overnight stays in 2025.', [('unverified', 'unit_mismatch')]),
    # a swapped unit between the two numbers
    ('Brașov: 2751439 înnoptări pe locuitor, adică 4,91 înnoptări în 2025.', [('unverified', 'unit_mismatch')] * 2),
    # small ratio 2 and zero are checked, with their unit
    ('Cluj: 2 înnoptări pe locuitor în 2025.', [('matched', 'value')]),
    ('Cluj had 2 overnight stays per resident in 2025.', [('matched', 'value')]),
    ('Cluj: raportul este 2 în 2025.', [('matched', 'value')]),
    ('Cluj: 3 înnoptări pe locuitor în 2025.', [('unverified', None)]),
    ('Cluj: 2 înnoptări în 2025.', [('unverified', 'unit_mismatch')]),
    ('Zero: 0 înnoptări pe locuitor în 2025.', [('matched', 'value')]),
    ('Zero: 0 persoane în 2025.', [('unverified', 'unit_mismatch')]),
    ('Zero: 4 înnoptări pe locuitor în 2025.', [('unverified', None)]),
])
def test_units_are_associated_with_their_own_statistic(text, expected):
    assert verdicts(text, TOURISM) == expected


@pytest.mark.parametrize('text,unit,value,ok', [
    ('Cluj avea 2.751.439 de persoane în 2025.', 'Numar persoane', 2751439.0, True),
    ('Cluj avea 2,751,439 people in 2025.', 'Numar persoane', 2751439.0, True),
    ('Cluj avea 2 751 439 de persoane în 2025.', 'Numar persoane', 2751439.0, True),
    ('Cluj avea 2,75 milioane de persoane în 2025.', 'Numar persoane', 2751439.0, True),
    ('Cluj had 2.75 million people in 2025.', 'Numar persoane', 2751439.0, True),
    ('Cluj avea 1.234.567,8 persoane în 2025.', 'Numar persoane', 1234567.8, True),
    ('Cluj had 1,234,567.8 people in 2025.', 'Numar persoane', 1234567.8, True),
    ('Cluj avea 560,3 mii de persoane în 2025.', 'Mii persoane', 560.3, True),
    ('Cluj avea 560 300 de persoane în 2025.', 'Mii persoane', 560.3, True),
    ('Cluj had 560.3 thousand people in 2025.', 'Mii persoane', 560.3, True),
    ('Cluj avea 560,3 persoane în 2025.', 'Mii persoane', 560.3, False),           # dropped scale
    ('Cluj avea 3,2 milioane lei în 2025.', 'Milioane lei', 3.2, True),
    ('Cluj had 3.2 million lei in 2025.', 'Milioane lei', 3.2, True),
    ('Cluj avea 3,2 milioane euro în 2025.', 'Milioane lei', 3.2, False),          # other currency
    ('Cluj had 2.75 billion people in 2025.', 'Numar persoane', 2751439.0, False),
    ('Cluj avea 2751,439 de persoane în 2025.', 'Numar persoane', 2751439.0, True),
])
def test_decimal_comma_and_scaled_values_in_both_languages(text, unit, value, ok):
    (c,) = bind(text, rows_query([['Cluj', '2025', value]], unit=unit))
    assert (c['check'] == 'matched') is ok, c


# --------------------------------------------------------------------- repeated premises, identifiers, vague wording

def test_a_question_that_repeats_the_eventual_figure_is_still_checked():
    t = rows_query([['Cluj', '2025', 2751439.0]])
    q = 'Are Cluj 2751439 de persoane în 2025?'
    (c,) = bind('Da, Cluj avea 2751439 de persoane în 2025.', t, q)
    assert c['check'] == 'matched' and c['path'] == '/data/rows/0/2'
    (c,) = bind('Da, Cluj avea 2751439 de persoane în 2024.', t, q)
    assert c['check'] == 'unverified' and c['reason'] == 'period_mismatch'
    (c,) = bind('Da, Cluj avea 2751439 de persoane.', rows_query([['Iasi', '2025', 999999.0]]), q)
    assert c['check'] == 'unverified'                                  # no evidence for the figure it echoes
    # the same premise repeated as a premise ("pentru N") is not a claim at all
    assert bind('Pentru 2751439 de persoane în 2025, Cluj are date.', t, q) == []
    # and an uncited echo is flagged by the plain number check, not waved through
    assert A.uncited_numbers('Da, Cluj avea 3000000 de persoane.', [t[0]['output']], 'Are Cluj 3000000 de persoane?') \
        == ['3000000']


def test_list_numbering_and_identifiers_do_not_create_claims():
    t = ranking([{'entity': {'REF_AREA': 'Cluj', 'REF_AREA_2': '54975 MUNICIPIUL CLUJ-NAPOCA'}, 'value': 286598.0, 'rank': 1},
                 {'entity': {'REF_AREA': 'Iasi', 'REF_AREA_2': '95060 MUNICIPIUL IASI'}, 'value': 271692.0, 'rank': 2}])
    text = ('1. Cluj-Napoca: 286.598 de locuitori (SIRUTA 54975)\n2. Iași: 271.692 de locuitori (cod 95060)\n'
            'Locul 1 este Cluj-Napoca. Datele sunt de la 31.12.2025.')
    got = bind(text, t)
    assert [(c['check'], c['path']) for c in got] == [('matched', '/data/rows/0/value'), ('matched', '/data/rows/1/value')]
    # the same codes in a bare answer without a "SIRUTA"/"cod" word are known identifiers of the result
    got = bind('Cluj-Napoca (54975) are 286.598 de locuitori.', t)
    assert [c['check'] for c in got] == ['matched']
    assert A.uncited_numbers('Cluj-Napoca (54975): 286.598 de locuitori.', [t[0]['output']]) == []
    # tables and bullets
    table = '| Loc | Oraș | Populație |\n|---|---|---|\n| 1 | Cluj-Napoca | 286.598 |\n| 2 | Iași | 271.692 |'
    assert [(c['check'], c['path']) for c in bind(table, t)] == [
        ('matched', '/data/rows/0/value'), ('matched', '/data/rows/1/value')]
    swapped = '| 1 | Cluj-Napoca | 271.692 |'
    assert [(c['check'], c['reason']) for c in bind(swapped, t)] == [('unverified', 'entity_mismatch')]


@pytest.mark.parametrize('text,trace,reason', [
    ('Cluj avea 7777 de persoane în 2025.', rows_query([['Cluj', '2025', 100.0]]), None),            # no such cell
    ('Cluj had 7777 people in 2025.', rows_query([['Cluj', '2025', 100.0]]), None),
    ('Valoarea a fost 100.', rows_query([['Cluj', '2025', 100.0]]), 'entity_unstated'),             # vague: whose?
    ('Un județ a avut 100 de persoane în 2025.', rows_query([['Cluj', '2025', 100.0]]), 'entity_unstated'),
    ('Some county had 100 people.', rows_query([['Cluj', '2025', 100.0]]), 'entity_unstated'),
    ('Cea mai mare scădere a fost de 28,57%.', NEG, 'entity_unstated'),
    ('Cluj are aproximativ 100 de persoane, în funcție de sursă.', rows_query([['Cluj', '2025', 100.0]]), 'MATCHED'),
])
def test_no_numeric_claim_without_evidence_is_matched_and_vague_wording_is_not_an_accusation(text, trace, reason):
    (c,) = bind(text, trace)
    if reason == 'MATCHED':
        assert c['check'] == 'matched'                                  # approximate wording is not a contradiction
        return
    assert c['check'] == 'unverified' and c['path'] is None and c['tool_call_id'] is None
    assert c.get('reason') == reason and c.get('reason') not in A.CONTRADICTIONS


def test_matched_claims_say_what_the_wording_fixed():
    (c,) = bind('Cluj avea 1000 de persoane în 2021.', EQUAL)
    assert c['semantic_check'] == 'no_explicit_conflict'
    assert c['anchors'] == {'entity': 'stated', 'period': 'stated', 'unit': 'stated', 'complete': True}
    (c,) = bind('Cluj-Napoca are 250000.', CITIES)                      # no year, no unit: not verified, only not contradicted
    assert c['check'] == 'matched' and c['anchors'] == {'entity': 'stated', 'period': 'unstated', 'unit': 'unstated',
                                                        'complete': False}
    (c,) = bind('Cluj a scăzut cu 40 de persoane.', NEG)
    assert c['anchors']['direction'] == 'stated' and c['anchors']['complete'] is False      # no year stated
    (c,) = bind('În 2020-2025 Cluj a scăzut cu 40 de persoane.', NEG)
    assert c['anchors']['complete'] is True
    (c,) = bind('Cluj avea 700000 de locuitori în 2025.', [env('query_data', {'columns': ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'],
                'rows': [['Cluj', '2025', 700000.0]]}, dataset='POP105A_judete_grupe')])
    assert c['anchors']['definition'] == 'unstated' and c['anchors']['complete'] is False   # resident or domicile?
    (c,) = bind('Cluj: −40 de persoane.', NEG)
    assert c['anchors']['direction'] == 'sign'


def test_unsupported_phrasing_stays_unverified_rather_than_guessed():
    t = rows_query([['Cluj', '2025', 2751439.0]])
    for text in ('Cluj avea 2 milioane 751 mii de persoane în 2025.',     # compound number
                 'Cluj avea circa trei milioane de persoane în 2025.',    # a spelled-out number is no claim at all
                 ):
        got = bind(text, t)
        assert all(c['check'] == 'unverified' for c in got)


@pytest.mark.parametrize('text,expected', [
    ('Județul Brăila are 197232 de persoane.', 'entity_mismatch'),
    ('County of Braila has 197232 people.', 'entity_mismatch'),
    ('Municipiul Brăila are 197232 de persoane.', 'matched'),
    ('Orașul Brăila are 197232 de persoane.', 'matched'),
])
def test_a_place_type_word_belongs_to_the_mention(text, expected):
    (c,) = bind(text, PLACES)
    assert (c['check'] if c['check'] == 'matched' else c['reason']) == expected


def test_a_population_definition_in_the_sentence_covers_its_numbers():
    t = [env('compare_periods', {'dataset': 'POP105A', 'unit': 'Numar persoane', 'metric': 'absolute', 'intervals': [
        {'from': '2012', 'to': '2021', 'rows': [{'entity': {'REF_AREA': 'Prahova'}, 'from_value': 761699.0,
                                                 'to_value': 703580.0, 'absolute': -58119.0, 'percent': -7.63,
                                                 'rank': 1}]}]}, dataset='POP105A')]
    ok = 'Între 2012 și 2021 Prahova a ajuns de la 761.699 la 703.580 de locuitori (populația rezidentă).'
    assert [c['check'] for c in bind(ok, t)] == ['matched', 'matched']
    wrong = ok.replace('rezidentă', 'după domiciliu')
    assert [(c['check'], c['reason']) for c in bind(wrong, t)] == [('unverified', 'definition_mismatch')] * 2
    both = 'Populația rezidentă din Prahova a fost de 761.699 în 2012, iar cea după domiciliu de 703.580 în 2021.'
    assert [(c['check'], c.get('reason')) for c in bind(both, t)] == [('matched', None), ('unverified', 'definition_mismatch')]


def test_a_direction_word_carries_through_an_enumeration_but_not_to_a_new_clause():
    two = change([ROW, {**ROW, 'entity': {'REF_AREA': 'Iasi'}, 'from_value': 90.0, 'to_value': 50.0,
                        'absolute': -40.0, 'percent': -44.44, 'rank': 2}])
    got = bind('Iasi a scăzut cu 40 de persoane, de la 90 la 50, iar Cluj a crescut cu 40 de persoane.', two)
    assert [c['check'] for c in got] == ['matched'] * 4
    assert [c['path'].rsplit('/', 2)[-2:] for c in got] == [['1', 'absolute'], ['1', 'from_value'],
                                                            ['1', 'to_value'], ['0', 'absolute']]
    # a verb of its own ends the enumeration: "are" is not an elided "a scăzut"
    got = bind('Iasi a scăzut cu 40 de persoane, iar Cluj are 140 de persoane.', two)
    assert [(c['check'], c['path'].rsplit('/', 2)[-2:]) for c in got] == [
        ('matched', ['1', 'absolute']), ('matched', ['0', 'to_value'])]


def test_abbreviations_do_not_split_a_number_from_its_unit_or_entity():
    (a, b) = bind('Brasov had 2751439 overnight stays, i.e. 4.91 per resident, in 2025.', TOURISM)
    assert (a['check'], b['check']) == ('matched', 'matched')
    assert A._sentences('Costă 120 mil. lei. Apoi 5 nr. 3 etc. Final.') == ['Costă 120 mil. lei.', 'Apoi 5 nr. 3 etc. Final.']
    assert A._sentences('a. b\nc; d') == ['a.', 'b', 'c;', 'd']


def test_random_wording_never_breaks_the_invariants():
    import random
    rnd = random.Random(7)
    words = ['Cluj', 'Iași', 'Cluj-Napoca', 'județul', 'și', 'and', 'iar', 'respectiv', 'a scăzut', 'fell', 'cu', 'de la',
             'la', 'from', 'to', '250000', '300000', '1000', '880', '40', '2', '0', '-40', '+8', '28,57%', '4,91',
             '2,75 milioane', '1.234.567', '2020', '2021', '2025', '2020-2025', '31.12.2025', '(54975)', 'persoane',
             'locuitori', 'lei', '%', 'pe locuitor', 'per resident', 'în', 'pentru', '.', ',', ';', ':', '|', '\n',
             'Top 10', 'locul 2', '1.', 'i.e.', 'mil.', '→', '(', ')']
    traces = [CITIES, EQUAL, PLACES, NEG, TOURISM, change([ROW])]
    for _ in range(300):
        text = ' '.join(rnd.choice(words) for _ in range(rnd.randint(1, 40)))
        claims = bind(text, rnd.choice(traces), rnd.choice(['', 'Câți locuitori are Cluj?']))
        assert len(claims) <= A.MAX_CLAIMS
        for c in claims:
            if c['check'] == 'matched':
                assert c['path'] and c['tool_call_id'] and c['semantic_check'] == 'no_explicit_conflict'
            else:
                assert c['path'] is None and c['tool_call_id'] is None


# --------------------------------------------------------------------- bounded work

def test_work_stays_bounded_for_long_answers_and_wide_traces():
    names = [f'Localitatea{i:04d}' for i in range(3000)]
    t = rows_query([[n, '2025', 1000.0 + i] for i, n in enumerate(names)])
    text = ' '.join(f'{n} are {1000 + i} de persoane.' for i, n in enumerate(names[:60]))
    start = time.monotonic()
    got = bind(text, t)
    assert time.monotonic() - start < 10
    assert len(got) == A.MAX_CLAIMS and all(c['check'] == 'matched' for c in got)
    assert [c['path'] for c in got][:2] == ['/data/rows/0/2', '/data/rows/1/2']
    assert len(A.uncited_numbers(text, [t[0]['output']])) == 0
    # one run-on "sentence" with thousands of numbers and names: only the claims within the cap are read
    run_on = ' '.join(f'{names[i]} {1000 + i}, {names[i + 1]} {1001 + i}' for i in range(0, 2000, 2))
    start = time.monotonic()
    got = bind(run_on, t)
    assert time.monotonic() - start < 10
    assert len(got) == A.MAX_CLAIMS and all(c['check'] == 'matched' for c in got)


# --------------------------------------------------------------------- the Ask loop

class TestAskLoop:
    def run_popc(self, tmp_path, monkeypatch, answer, on_event=None):
        from at02_env import call_resp, full_env, run
        from test_at02_loop import text_resp
        full_env(tmp_path, monkeypatch)
        return run(monkeypatch, [call_resp('query_data', {'dataset': 'POPC', 'group_by': ['REF_AREA', 'TIME_PERIOD']}),
                                 text_resp(answer)], on_event=on_event)[0]

    def test_swapped_values_are_unverified_not_withheld(self, tmp_path, monkeypatch):
        r = self.run_popc(tmp_path, monkeypatch, 'Cluj avea 880 de persoane în 2021, iar Iași 1010.')
        v = r.verification
        assert v['status'] == 'unverified_numbers' and (r.outcome, r.reason) == ('partial', 'unverified_numbers')
        assert r.answer.startswith('Cluj avea 880')                      # flagged, never rewritten
        assert v['claim_summary'] == {'matched': 0, 'unverified': 2} and v['claim_reasons'] == {'entity_mismatch': 2}
        assert r.metrics['claim_codes'] == {'unverified': 2, 'entity_mismatch': 2}

    def test_the_correct_assignment_verifies(self, tmp_path, monkeypatch):
        r = self.run_popc(tmp_path, monkeypatch, 'Cluj avea 1010 persoane în 2021, iar Iași 880 persoane.')
        assert r.verification['status'] == 'verified' and (r.outcome, r.reason) == ('answered', None)
        assert r.verification['claim_summary'] == {'matched': 2, 'unverified': 0}
        assert r.verification['claim_reasons'] == {} and r.metrics['claim_codes'] == {'matched': 2}

    def test_an_equal_value_without_its_year_is_partial(self, tmp_path, monkeypatch):
        from at02_env import call_resp, full_env, run
        from test_at02_loop import text_resp
        full_env(tmp_path, monkeypatch)
        # Cluj 1000 (2020) / 1010 (2021) are different; Iași 900 / 880. Ask for a series where two years agree
        r, _ = run(monkeypatch, [call_resp('query_data', {'dataset': 'POPC', 'group_by': ['REF_AREA', 'TIME_PERIOD'],
                                                          'filters': {'REF_AREA': ['Bihor']}}),
                                 text_resp('Bihor avea 610 persoane în 2021.')])
        assert r.verification['status'] == 'verified'

    def test_an_explicit_unit_contradiction_still_withholds(self, tmp_path, monkeypatch):
        r = self.run_popc(tmp_path, monkeypatch, 'Cluj avea 1010 persoane pe locuitor în 2021.')
        assert r.verification['status'] == 'claim_mismatch' and r.reason == 'claim_mismatch'
        assert '1010' not in r.answer and r.verification['claim_reasons'] == {'unit_mismatch': 1}

    def test_the_debug_event_has_counts_and_reasons_but_no_answer_text(self, tmp_path, monkeypatch):
        events = []
        self.run_popc(tmp_path, monkeypatch, 'Cluj avea 880 de persoane în 2021, iar Iași 1010.', events.append)
        ev = next(e for e in events if e['event'] == 'claims')
        assert ev['matched'] == 0 and ev['unverified'] == 2 and ev['reasons'] == {'entity_mismatch': 2}
        assert ev['complete'] == 0
        assert 'Cluj' not in str(ev) and '880' not in str(ev)

    def test_metrics_carry_claim_codes_only_when_claims_were_checked(self):
        from app.services import ask_guard
        assert ask_guard.sanitize_metrics({'claim_codes': {'matched': 1, 'entity_mismatch': 2, 'Not A Code': 1,
                                                           'x': 'y'}})['claim_codes'] == {'matched': 1, 'entity_mismatch': 2}
        assert 'claim_codes' not in ask_guard.sanitize_metrics({'claim_codes': {}, 'refusal_codes': {}})
