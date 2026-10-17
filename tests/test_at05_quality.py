"""Task-level regressions: preserve the requested statistic and refuse wrong claims."""
import pytest
from app.services import answer_check as A
from app.services.tools import registry as R
from app.services.tools.intent import interpret
from test_at01_discovery import env  # synthetic concept/recipe corpus


@pytest.mark.parametrize('question', [
    'Câte înnoptări revin la un locuitor în Cluj, în 2023?',
    'Câte înnoptări turistice revin pe locuitor în Cluj, în 2023?',
    'How many overnight stays were there per resident in Cluj in 2023?',
])
def test_ratio_paraphrases_only_offer_the_ratio(env, question):
    import json
    from app.services import concept_search as cs
    raw = json.loads(cs.CONCEPTS_PATH.read_text())
    c = next(c for c in raw['concepts'] if c['id'] == 'intensity')
    c['id'] = 'tourism_intensity'
    c['aliases']['ro'].append('innoptari pe locuitor')
    cs.CONCEPTS_PATH.write_text(json.dumps(raw))
    r = R.call_tool('discover_indicators', {'query': question})
    assert r['status'] == 'ok'
    cards = r['data']['concepts']
    assert len(cards) == 1 and cards[0]['id'] == 'tourism_intensity'
    n = cards[0]['next_call']
    assert n['tool'] == 'run_recipe'
    assert n['arguments']['year'] == '2023'
    assert n['arguments']['areas'] == ['Cluj']


@pytest.mark.parametrize('question', ['înnoptări la mia de locuitori Cluj',
    'turisti pe locuitor Cluj', 'population and population density of the top 30 cities'])
def test_unsupported_measures_do_not_turn_into_counts(env, question):
    r = R.call_tool('discover_indicators', {'query': question})
    assert r['status'] == 'unavailable' and r['reason'] == 'unsupported_operation'


def trace(unit='Numar', value=2751439, tool='query_data'):
    return [{'id': 'a', 'tool': tool, 'output': {
        'contract': 'tempo-tools/2', 'tool': tool, 'status': 'ok',
        'data': {'columns': ['REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'],
                 'rows': [['Brasov', '2025', value]]},
        'provenance': {'sources': [{'unit': unit}]}}}]


@pytest.mark.parametrize('text,reason', [
    ('Brașov a avut 2751439 înnoptări pe locuitor în 2025.', 'unit_mismatch'),
    ('Brasov had 2751439 overnight stays per resident in 2025.', 'unit_mismatch'),
    ('Brasov had 2751439 overnight stays in 2024.', 'period_mismatch'),
    ('Brașov a avut 2751439% în 2025.', 'unit_mismatch'),
])
def test_wrong_unit_or_period_cannot_be_matched(text, reason):
    c = A.bind_claims(text, '', trace())[0]
    assert c['check'] == 'unverified' and c['reason'] == reason


def test_correct_ratio_uses_recipe_unit_not_numerator_unit():
    t = trace(tool='run_recipe')
    t[0]['output']['data'] = {'year': '2025', 'recipe': {'unit': 'înnoptări pe locuitor'},
                            'rows': [{'label': 'Brasov', 'value': 4.9108548}]}
    c = A.bind_claims('Brașov: 4,91 înnoptări pe locuitor în 2025.', '', t)[0]
    assert c['check'] == 'matched' and c['unit'] == 'înnoptări pe locuitor'


def test_locality_name_must_match_not_just_county_or_unit():
    t = trace(unit='Numar persoane', value=60000)
    t[0]['output']['data'] = {'columns': ['REF_AREA', 'REF_AREA_2', 'TIME_PERIOD', 'OBS_VALUE'],
                            'rows': [['Cluj', '55400 MUNICIPIUL TURDA', '2025', 60000]]}
    assert A.bind_claims('Cluj-Napoca avea 60000 persoane în 2025.', '', t)[0]['check'] == 'unverified'
    assert A.bind_claims('Turda avea 60000 persoane în 2025.', '', t)[0]['check'] == 'matched'


def test_full_question_keeps_ranking_and_latest():
    i = interpret('populația curentă a celor mai populate 30 de orașe')
    assert i['cities'] and i['latest'] and i['operation'] == 'rank' and i['top_k'] == 30


def test_loop_withholds_wrong_unit_explanation(tmp_path, monkeypatch):
    from at02_env import full_env, run, call_resp
    from test_at02_loop import text_resp
    full_env(tmp_path, monkeypatch)
    r, _ = run(monkeypatch, [call_resp('query_data', {'dataset': 'POPC',
        'filters': {'TIME_PERIOD': ['2021']}, 'group_by': ['REF_AREA', 'TIME_PERIOD']}),
        text_resp('Cluj avea 1010 persoane pe locuitor în 2021.')])
    assert r.verification['status'] == 'claim_mismatch'
    assert r.outcome == 'partial' and r.reason == 'claim_mismatch'
    assert '1010' not in r.answer


def test_count_and_ratio_in_one_sentence_keep_their_own_units():
    t = trace()
    ratio = trace(tool='run_recipe')[0]
    ratio['id'] = 'b'
    ratio['output']['data'] = {'year': '2025', 'recipe': {'unit': 'înnoptări pe locuitor'},
                              'rows': [{'label': 'Brasov', 'value': 4.9108548}]}
    t.append(ratio)
    claims = A.bind_claims('Brașov: 2751439 înnoptări, adică 4,91 înnoptări pe locuitor în 2025.', '', t)
    assert len(claims) == 2 and all(c['check'] == 'matched' for c in claims)
    from app.services.ask_present import display_table
    assert display_table(t)['unit'] == 'înnoptări pe locuitor'


def test_population_default_is_disclosed_only_for_reviewed_definition(env):
    import json
    from app.services import concept_search as cs
    raw = json.loads(cs.CONCEPTS_PATH.read_text())
    c = next(c for c in raw['concepts'] if c['id'] == 'res_pop')
    c['id'] = 'resident_population'
    cs.CONCEPTS_PATH.write_text(json.dumps(raw))
    r = R.call_tool('discover_indicators', {'query': 'populația curentă pe județe'})
    assert r['status'] == 'ok'
    assert r['data']['interpretation']['assumed_definition'] == 'resident_population'
    assert r['data']['interpretation']['latest']
    assert any(w['code'] == 'assumed_definition' for w in r['warnings'])
    assert any(c.get('assumed') for c in r['data']['concepts'])
    explicit = R.call_tool('discover_indicators', {'query': 'populația după domiciliu pe județe'})
    assert explicit['data']['interpretation']['assumed_definition'] is None
    assert explicit['data']['concepts'][0]['id'] == 'dom_pop'


def test_loop_does_not_present_a_query_as_a_ranking(tmp_path, monkeypatch):
    from at02_env import full_env, run, call_resp
    from test_at02_loop import text_resp
    full_env(tmp_path, monkeypatch)
    r, _ = run(monkeypatch, [call_resp('query_data', {'dataset': 'POPC',
        'filters': {'TIME_PERIOD': ['2021']}, 'group_by': ['REF_AREA', 'TIME_PERIOD']}),
        text_resp('Cluj conduce clasamentul cu 1010 persoane în 2021.')],
        question='Top 10 județe după populație în 2021')
    assert r.outcome == 'partial' and r.reason == 'ranking_unverified'
    assert r.data is None and r.chart_spec is None and '1010' not in r.answer


def test_ranking_entity_identity_is_independent_of_column_order():
    t = trace(unit='Numar persoane', tool='rank_entities')
    t[0]['output']['data'] = {'year': '2025', 'rows': [
        {'entity': {'REF_AREA_2': '55400 MUNICIPIUL TURDA', 'REF_AREA': 'Cluj'}, 'value': 60000}]}
    assert A.bind_claims('Cluj-Napoca: 60000 persoane în 2025.', '', t)[0]['check'] == 'unverified'
    assert A.bind_claims('Turda: 60000 persoane în 2025.', '', t)[0]['check'] == 'matched'
