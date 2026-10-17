"""Rank the complete universe before top K; no capped input or model arithmetic."""
import json
import pytest
from at01_fixtures import add_dataset, make_env, call
from test_at01_changes import area_dim, time_dim, unit_dim
from app.services.tools.registry import validate_result


def build(corpus):
    cities = [f'{1000+i} ORAS CITY{i:03}' for i in range(230)]
    names = cities + ['9999 COMMUNE']
    dims = [area_dim(['County']), area_dim(names, 'locality', 'REF_AREA_2'),
            time_dim(('2024', '2025')), unit_dim('Numar persoane')]
    rows = [('County', c, year, 'Numar persoane', float(i + 100 if i < 230 else 999999))
            for year in ('2024', '2025') for i, c in enumerate(names)]
    add_dataset(corpus, 'CITYX', dims, rows)
    add_dataset(corpus, 'GOS102A', [area_dim(cities, 'locality', 'REF_AREA_2'),
                                   time_dim(('2024',)), unit_dim('Hectare')],
                [(c, '2024', 'Hectare', 10.) for c in cities])


@pytest.fixture
def env(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=build)


def rank(**kw):
    kw.setdefault('entity_class', 'cities')
    return call('rank_entities', dataset='CITYX', entity_columns=['REF_AREA', 'REF_AREA_2'], **kw)


def test_winner_after_two_hundred_rows_and_commune_excluded(env):
    r = rank(top_k=3)
    validate_result('rank_entities', r)
    assert r['status'] in ('ok', 'partial')
    d = r['data']
    assert d['year'] == '2025' and d['eligible_count'] == 230 and d['outside_class_count'] == 1
    assert [x['value'] for x in d['rows']] == [329, 328, 327]
    assert [x['rank'] for x in d['rows']] == [1, 2, 3]
    assert d['rows'][0]['entity']['REF_AREA_2'] == '1229 ORAS CITY229'
    assert r['limits']['source_complete'] and not r['limits']['preview_truncated']
    assert r['provenance']['classification']['dataset'] == 'GOS102A'


def test_exact_year_no_substitution(env):
    assert rank(year='2023')['reason'] == 'period_unavailable'
    assert rank(year='2024')['data']['year'] == '2024'


def test_capped_input_is_not_ranked(env, monkeypatch):
    from app import config
    monkeypatch.setattr(config, 'MAX_DATA_ROWS', 200)
    r = rank()
    assert r['status'] == 'unavailable' and r['reason'] == 'source_incomplete'
    assert not r['data'].get('rows')


def test_duplicates_are_refused_before_ranking(env, monkeypatch):
    from app.services import data_query
    original = data_query.run_query
    def duplicate(*a, **kw):
        out = original(*a, **kw)
        out['rows'].append(out['rows'][0])
        return out
    monkeypatch.setattr(data_query, 'run_query', duplicate)
    assert rank()['reason'] == 'duplicate_keys'


def test_ascending_and_stable_ties(env, monkeypatch):
    from app.services import data_query
    original = data_query.run_query
    def tie(*a, **kw):
        out = original(*a, **kw)
        out['rows'] = [list(r[:-1]) + [123.] for r in reversed(out['rows'])]
        return out
    monkeypatch.setattr(data_query, 'run_query', tie)
    r = rank(order='asc', top_k=2)
    assert [x['entity']['REF_AREA_2'] for x in r['data']['rows']] == ['1000 ORAS CITY000', '1001 ORAS CITY001']


def test_links_and_followup_replay_same_selection(env):
    from app.services import ask_context, ask_present
    r = rank(top_k=4)
    s = r['provenance']['selection']
    gid = r['provenance']['generation']['id']
    e = call('get_evidence_links', selection=s, generation_id=gid)
    assert e['status'] == 'ok'
    evidence = next(l for l in e['data']['links'] if l['kind'] == 'evidence')
    response = env.client.get(evidence['url'])
    assert response.status_code == 200 and response.json()['data']['rows'] == r['data']['rows']
    assert env.client.get(evidence['url'].replace(gid, 'stale')).status_code == 409
    entry = ask_context.entry_from_envelope('rank_entities', r)
    assert ask_context.validate([entry])[0]['selection'] == s
    table = ask_present.display_table([{'tool': 'rank_entities', 'output': r}])
    assert table['ranked'] and table['eligible_count'] == 230


@pytest.mark.parametrize('kw', [{'top_k': 0}, {'top_k': True}, {'year': '2025-01'},
    {'filters': {'TIME_PERIOD': ['2025']}}, {'entity_class': 'villages'}])
def test_bad_input_rejected(env, kw):
    assert rank(**kw)['status'] == 'error'


def test_public_mcp_returns_same_city_ranking_and_enforces_scan_limit(env, tmp_path, monkeypatch):
    import asyncio
    import at03_env as E
    from app.services.tools import registry
    args = {'dataset': 'CITYX', 'entity_columns': ['REF_AREA', 'REF_AREA_2'],
            'entity_class': 'cities', 'top_k': 3}
    app, mcp = E.make_app(tmp_path, monkeypatch, env=env)
    async def invoke(app):
        async with E.started(app), E.session(app) as client:
            return E.payload(await client.call_tool('rank_entities', args))
    structured, text = asyncio.run(invoke(app))
    assert structured == text
    assert structured['data']['rows'] == registry.call_tool('rank_entities', args)['data']['rows']
    limited, _ = E.make_app(tmp_path, monkeypatch, env=env,
                            environ={'TEMPO_MCP_MAX_SCAN_ROWS': '100'})
    structured, _ = asyncio.run(invoke(limited))
    assert structured['status'] == 'unavailable' and structured['reason'] == 'query_budget'
