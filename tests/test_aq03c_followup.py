"""AQ-03 follow-up: correct scripted answers from the AQ-02 task set that 03B left unverified.

Each case is a genuine false positive of the first 03B binding, pinned with the sentence that
exposed it (AQ-02 tasks T07, T08, T10, T11, T01) and the neighbouring wording that must still be
caught. Hand-built results again: the checker is a pure function of the trace."""
import copy

import pytest

from app.services import answer_check as A
from test_aq03a_evidence import ROW, change, env
from test_aq03b_binding import TOURISM, bind, rows_query, verdicts


# --------------------------------------------------------------------- an age range is not two values

@pytest.mark.parametrize('text,expected', [
    # T10 / T11: "(ages 0–4)" and "vârstele 0–2" with a unit later in the sentence
    ('On the single-year level (ages 0–4) the 2025 population is 110 persons;', ['110']),
    ('I cannot add all ages: single years and the 0–4 band overlap, 110 persons.', ['110']),
    ('AGEP covers only ages 0–2 (33 persons in 2023), not the whole population.', ['33']),
    ('AGEP acoperă doar vârstele 0–2 ani (33 de persoane în 2023), nu întreaga populație.', ['33']),
    ('Between ages 0 and 4 there were 110 persons.', ['110']),
    # the unit that belongs to a small number still counts, also across "la 1000"
    ('Brașov: 2 înnoptări pe locuitor în 2025.', ['2']),
    ('Rata este de 12 la 1000 de locuitori.', ['12']),
    ('Au fost 3 persoane.', ['3']),
])
def test_a_unit_after_the_next_number_does_not_make_a_range_endpoint_a_claim(text, expected):
    assert [c['raw'] for c in A.find_numbers(text)] == expected


# --------------------------------------------------------------------- T08: an enumeration of changes

COUNT = change([
    {'entity': {'REF_AREA': 'B'}, 'from_value': 200.0, 'to_value': 150.0, 'absolute': -50.0, 'percent': -25.0, 'rank': 1},
    {'entity': {'REF_AREA': 'A'}, 'from_value': 100.0, 'to_value': 80.0, 'absolute': -20.0, 'percent': -20.0, 'rank': 2}],
    unit='Numar persoane', dataset='COUNTX')


@pytest.mark.parametrize('text', [
    '2020–2025: B -50 (from 200 to 150), then A -20; C is not listed.',
    '2020–2025: B -50 (de la 200 la 150), apoi A -20.',
    '2020–2025: B -50 (from 200 to 150) and A -20.',
])
def test_a_list_of_changes_continues_through_from_to_and_a_bare_value(text):
    got = bind(text, COUNT)
    assert [c['check'] for c in got] == ['matched'] * len(got)
    assert got[-1]['path'].endswith('/rows/1/absolute') and got[-1]['entity'] == 'A'
    # "A -20" has no unit of its own: the metric of the list ("-50 persons") decides between -20 persons and -20 %
    a = next(c for c in got if c['entity'] == 'A')
    assert a['metric'] == 'change_absolute' and a['anchors']['unit'] == 'inherited' and a['anchors']['complete'] is False


def test_a_unit_of_its_own_beats_the_metric_of_the_list_and_a_swap_is_still_caught():
    (b, a) = bind('B -50 persoane, apoi A -20%.', COUNT)
    assert (b['metric'], a['metric']) == ('change_absolute', 'change_percent') and a['anchors']['unit'] == 'stated'
    swapped = bind('2020–2025: A -50 (from 200 to 150), then B -20.', COUNT)
    assert [(c['check'], c['reason']) for c in swapped] == [('unverified', 'entity_mismatch')] * len(swapped)
    # without a list to inherit from the two readings of "-20" stay ambiguous
    (c,) = bind('A -20.', COUNT)
    assert (c['check'], c['reason'], c['candidates']) == ('unverified', 'ambiguous_binding', 2)


def test_a_new_verb_ends_the_list_so_nothing_is_inherited():
    two = change([ROW, {'entity': {'REF_AREA': 'Iasi'}, 'from_value': 100.0, 'to_value': 80.0, 'absolute': -20.0,
                        'percent': -20.0, 'rank': 2}])
    got = bind('Cluj a crescut cu 40%, iar Iasi are -20.', two)
    assert got[1]['check'] == 'unverified' and got[1]['reason'] == 'ambiguous_binding'


# --------------------------------------------------------------------- T07: the reconstruction beside the published value

PUBLISHED = [{'id': 'r1', 'tool': 'run_recipe', 'output': {
    'contract': 'tempo-tools/2', 'tool': 'run_recipe', 'status': 'ok',
    'data': {'year': '2024', 'recipe': {'id': 'fx_published', 'unit': 'lei', 'value_source': 'ins_published'},
             'rows': [{'label': 'Alfa', 'geo_id': 'alfa', 'value': 10.0, 'reconstructed': 9.9}]},
    'provenance': {'sources': [{'dataset': 'PSTAY', 'role': 'stays'}, {'dataset': 'PPOP', 'role': 'population'}]}}}]


def test_the_cross_check_of_a_published_value_is_a_cell_cited_as_a_cross_check():
    lv = A.numeric_leaves(PUBLISHED[0]['output'])
    assert [(lf['metric'], lf['value'], lf['path']) for lf in lv] == [
        ('observation', 10.0, '/data/rows/0/value'), ('reconstruction', 9.9, '/data/rows/0/reconstructed')]
    assert lv[1]['unit_norm'] == lv[0]['unit_norm'] and lv[1]['key'] == lv[0]['key']
    ro = ('INS publică pentru Alfa, în 2024, valoarea 10 (celula publicată; reconstrucția din surse dă 9,9 '
          'și servește doar ca verificare, rețeta fx_published).')
    en = ('INS publishes the value 10 for Alfa in 2024 (the published cell; the reconstruction from sources gives '
          '9.9 and is only a cross-check, recipe fx_published).')
    for text in (ro, en):
        got = bind(text, PUBLISHED)
        assert [(c['check'], c['path'].rsplit('/', 1)[1]) for c in got] == [('matched', 'value'), ('matched', 'reconstructed')]
        assert got[1]['entity'] == 'Alfa' and got[1]['period'] == '2024'
        assert A.uncited_numbers(text, [PUBLISHED[0]['output']]) == []


@pytest.mark.parametrize('text', [
    'INS publică pentru Alfa, în 2024, valoarea 9,9 (rețeta fx_published).',
    'INS publishes the value 9.9 for Alfa in 2024 (recipe fx_published).',
])
def test_the_reconstruction_presented_as_the_figure_stays_unverified(text):
    (c,) = bind(text, PUBLISHED)
    assert (c['check'], c['reason']) == ('unverified', 'metric_mismatch') and c['reason'] not in A.CONTRADICTIONS


def test_a_semicolon_continues_the_sentence_but_a_full_stop_does_not():
    twice = 'INS publishes the value 10 for Alfa in 2024; the reconstruction gives 9.9, only a cross-check.'
    assert [c['check'] for c in bind(twice, PUBLISHED)] == ['matched', 'matched']
    new_sentence = 'INS publishes the value 10 for Alfa in 2024. The reconstruction gives 9.9, only a cross-check.'
    assert [(c['check'], c.get('reason')) for c in bind(new_sentence, PUBLISHED)] == [
        ('matched', None), ('unverified', 'entity_unstated')]
    own_entity = 'INS publishes the value 10 for Alfa in 2024; Beta has 4000 persons.'
    assert [c['check'] for c in bind(own_entity, PUBLISHED)] == ['matched', 'unverified']
    # the carried entity never overrides a clause that names its own, and the year it carries is soft
    t = rows_query([['Cluj', '2020', 1000.0], ['Cluj', '2021', 1010.0], ['Iasi', '2020', 900.0]])
    got = bind('Cluj avea 1000 de persoane în 2020; 1010 în 2021.', t)
    assert [(c['check'], c['path']) for c in got] == [('matched', '/data/rows/0/2'), ('matched', '/data/rows/1/2')]
    got = bind('Cluj avea 1000 de persoane în 2020; 900.', t)
    assert [c['check'] for c in got] == ['matched', 'unverified']          # Iasi's 900 is not Cluj's


# --------------------------------------------------------------------- T01: a figure meant exactly

@pytest.mark.parametrize('text,cell,ok', [
    ('Cluj avea 1010 persoane în 2021.', 1010.0, True),
    ('Cluj avea 1011 persoane în 2021.', 1010.0, False),       # T01 off-by-one: written exactly, not the cell
    ('Cluj avea 1009 persoane în 2021.', 1010.0, False),
    ('Cluj avea 2.751.000 de persoane în 2021.', 2751439.0, True),     # a rounded-looking figure keeps the 0.5%
    ('Cluj avea 2.751.439 de persoane în 2021.', 2751439.0, True),
    ('Cluj avea 2.751.438 de persoane în 2021.', 2751439.0, False),
    ('Cluj avea 2,75 milioane de persoane în 2021.', 2751439.0, True),
    ('Cluj avea 4,91 persoane în 2021.', 4.9108548, True),      # rounded to the digits printed
    ('Cluj avea 4,90 persoane în 2021.', 4.9108548, True),
    ('Cluj avea 4,92 persoane în 2021.', 4.9108548, False),
    ('Cluj avea 58.085 de persoane în 2021.', 58119.0, False),
    ('Cluj avea 58.110 de persoane în 2021.', 58119.0, True),
])
def test_an_integer_written_exactly_is_the_cell_or_nothing_while_rounded_figures_keep_their_tolerance(text, cell, ok):
    t = rows_query([['Cluj', '2021', cell]])
    (c,) = bind(text, t)
    assert (c['check'] == 'matched') is ok, c
    figure = A.find_numbers(text)[0]['raw']
    assert (A.uncited_numbers(text, [t[0]['output']]) == []) is ok, figure


def test_the_cell_that_holds_the_printed_figure_outranks_a_cell_it_only_rounds_to():
    t = [env('run_recipe', {'year': '2024', 'recipe': {'id': 'r', 'unit': 'lei'},
                            'rows': [{'label': 'Alfa', 'geo_id': 'alfa', 'value': 10.0, 'reconstructed': 9.9}]},
             dataset=None, unit=None, sources=[])]
    got = bind('Alfa: 10 lei în 2024 (reconstrucția dă 9,9).', t)
    assert [c['path'].rsplit('/', 1)[1] for c in got] == ['value', 'reconstructed']
    # two cells that both hold the printed figure exactly are still ambiguous
    t2 = rows_query([['Cluj', '2020', 1000.0], ['Cluj', '2021', 1000.0]])
    (c,) = bind('Cluj avea 1000 de persoane.', t2)
    assert c['reason'] == 'ambiguous_binding'


def test_the_tourism_recipe_cells_do_not_gain_unrelated_leaves():
    # only the headline value and a reconstruction are cells; stays / population columns stay out
    out = copy.deepcopy(TOURISM[1]['output'])
    out['data']['rows'][0]['stays'], out['data']['rows'][0]['population'] = 2751439.0, 560277.0
    assert {lf['metric'] for lf in A.numeric_leaves(out)} == {'observation'}
    assert verdicts('Brașov are 2751439 de înnoptări.', TOURISM)[0][0] == 'matched'     # via the query_data count
