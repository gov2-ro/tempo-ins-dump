"""PKG-COMPOSER: composed tiles draw honest series and render rows.

Synthetic dimensions and parquets with known values:
  C01/E3  a Total is never a series next to its parts;
  C04/C14 a temporal tile holds one periodicity, and the latest pin agrees;
  E7      a slice the unique-grain gate refuses is suppressed with its reason;
  E8      pins that never co-occur are re-picked so the slice has rows;
  E10     a few areas without a national row are series, not a pin.
"""
import duckdb
import pytest

from app.services import dashboard_composer as dc
from app.services.dashboard_composer import compose_dashboard, time_granularity


def _dim(col, dtype, labels, parsed=None):
    return {'dim_column_name': col, 'dim_label': col, 'dim_type': dtype,
            'option_count': len(labels),
            'options': [{'label': l, 'sdmx_value': l.strip(),
                         **({'parsed': parsed(l)} if parsed else {})} for l in labels]}


def _actual(*dims):
    return {d['dim_column_name']: {o['sdmx_value']: 1 for o in d['options']} for d in dims}


def _tile(comp, chart_id):
    return next(c for c in comp['charts'] if c['id'] == chart_id)


ADDITIVE = {'primary_unit_type': 'count', '_measure': 'additive', 'time_points': 3}


# --------------------------------------------------------------- C01 / E3

YEARS = _dim('TIME_PERIOD', 'time', ['2022', '2023', '2024'])
OWNER = _dim('OWNER', 'gender', ['Total', 'Privata', 'Publica'])     # a partition
VALUES = {('2022', 'Privata'): 4.0, ('2022', 'Publica'): 1.0, ('2022', 'Total'): 5.0,
          ('2023', 'Privata'): 6.0, ('2023', 'Publica'): 2.0, ('2023', 'Total'): 8.0,
          ('2024', 'Privata'): 7.0, ('2024', 'Publica'): 3.0, ('2024', 'Total'): 10.0}


@pytest.mark.parametrize('chart_type', ['area_stacked', 'stacked_bar', 'line', 'bar_vertical'])
def test_total_is_never_a_series_beside_its_parts(chart_type):
    dims = [YEARS, OWNER]
    ranked = [{'chart_type': chart_type, 'score': 0.9,
               'roles': {'x_axis': 'TIME_PERIOD', 'series': 'OWNER'}}]
    tile = compose_dashboard(ADDITIVE, ranked, dims, actual_values=_actual(*dims))['charts'][0]
    assert tile['roles']['series'] == 'OWNER'
    assert tile['data']['filters']['OWNER'] == ['Privata', 'Publica']
    # The stack top is the sum of the drawn series; it equals the Total row.
    con = duckdb.connect()
    con.execute('CREATE TABLE t (TIME_PERIOD VARCHAR, OWNER VARCHAR, OBS_VALUE DOUBLE)')
    con.executemany('INSERT INTO t VALUES (?, ?, ?)', [(*k, v) for k, v in VALUES.items()])
    keep = tile['data']['filters']['OWNER']
    tops = dict(con.execute(
        f"SELECT TIME_PERIOD, sum(OBS_VALUE) FROM t WHERE OWNER IN ({', '.join('?' * len(keep))}) "
        "GROUP BY 1", keep).fetchall())
    assert tops == {'2022': 5.0, '2023': 8.0, '2024': 10.0}


def test_categorical_tile_drops_the_series_total():
    brk = _dim('BRK', 'indicator', [f'Grupa {i}' for i in range(8)])
    dims = [brk, OWNER, _dim('TIME_PERIOD', 'time', ['2024'])]
    ranked = [{'chart_type': 'heatmap', 'score': 0.8,
               'roles': {'x_axis': 'BRK', 'series': 'OWNER'}}]
    sig = {**ADDITIVE, 'time_points': 1}
    tile = _tile(compose_dashboard(sig, ranked, dims, actual_values=_actual(*dims)), 'heatmap')
    assert tile['data']['filters']['OWNER'] == ['Privata', 'Publica']


def test_series_total_kept_when_it_is_the_only_value():
    only = _dim('OWNER', 'gender', ['Total'])
    assert dc._series_without_total(only, dc._effective(only, None), None, None) is None


def test_total_stays_the_off_axis_pin():
    brk = _dim('BRK', 'indicator', [f'Grupa {i}' for i in range(8)])
    dims = [YEARS, OWNER, brk]
    ranked = [{'chart_type': 'horizontal_bar', 'score': 0.9, 'roles': {'x_axis': 'BRK'}}]
    tile = compose_dashboard(ADDITIVE, ranked, dims, actual_values=_actual(*dims))['charts'][0]
    assert tile['data']['filters']['OWNER'] == ['Total']


# --------------------------------------------------------------- C04 / C14

def _periods(labels):
    return _dim('TIME_PERIOD', 'time', labels)


QUARTERLY_MOSTLY = ['2022', '2022-Q1', '2022-Q2', '2022-Q3', '2022-Q4', '2023', '2023-Q1']
ANNUAL_ENOUGH = ['2021', '2021-Q4', '2022', '2022-Q1', '2022-Q2', '2022-Q3', '2022-Q4',
                 '2023', '2023-Q1']


@pytest.mark.parametrize('labels,gran,members,latest', [
    (QUARTERLY_MOSTLY, 'quarterly',
     ['2022-Q1', '2022-Q2', '2022-Q3', '2022-Q4', '2023-Q1'], '2023-Q1'),
    (ANNUAL_ENOUGH, 'annual', ['2021', '2022', '2023'], '2023'),
])
def test_temporal_tile_holds_one_periodicity(labels, gran, members, latest):
    time = _periods(labels)
    cat = _dim('CAT', 'indicator', [f'C{i}' for i in range(7)])
    dims = [time, cat]
    ranked = [{'chart_type': 'line', 'score': 0.9, 'roles': {'x_axis': 'TIME_PERIOD'}},
              {'chart_type': 'horizontal_bar', 'score': 0.8, 'roles': {'x_axis': 'CAT'}}]
    comp = compose_dashboard({**ADDITIVE, 'time_points': len(labels)}, ranked, dims,
                             actual_values=_actual(*dims))
    line, bar = _tile(comp, 'line'), _tile(comp, 'horizontal_bar')
    assert line['data']['filters']['TIME_PERIOD'] == members
    assert line['granularity'] == gran
    assert line['granularity_omitted'] and gran not in line['granularity_omitted']
    # The latest pin is the latest period of the same periodicity
    assert bar['data']['filters']['TIME_PERIOD'] == [latest]
    assert 'granularity' not in bar
    fd = next((f for f in comp['filter_dims'] if f['column'] == 'TIME_PERIOD'), None)
    assert fd is None or fd['default'] == latest


def test_single_periodicity_is_left_alone():
    assert time_granularity(_periods(['2021', '2022', '2023']), None) is None
    assert time_granularity(_periods(['2023-01', '2023-02']), None) is None


def test_legacy_labels_use_the_parsed_period():
    def parsed(label):
        y = int(label[-4:])
        return {'year': y, 'quarter': 1} if label.startswith('Trim') else {'year': y}
    time = _dim('TIME_PERIOD', 'time', ['Anul 2021', 'Anul 2022', 'Anul 2023',
                                        'Trimestrul I 2023'], parsed)
    # legacy parquets store the label strings, padded
    actual = {'TIME_PERIOD': {f' {o["label"]}': 1 for o in time['options']}}
    for o in time['options']:
        o['sdmx_value'] = None
    got = time_granularity(time, actual)
    assert got['granularity'] == 'annual' and len(got['entries']) == 3
    assert [v for _, v in got['entries']] == [' Anul 2021', ' Anul 2022', ' Anul 2023']


# --------------------------------------------------------------- E7 / E8 fixtures

def _write(path, ddl, rows):
    con = duckdb.connect()
    con.execute(f'CREATE TABLE t ({ddl})')
    con.executemany(f"INSERT INTO t VALUES ({', '.join('?' * len(rows[0]))})", rows)
    con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    con.close()


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    from app.services import generation, grain_guard, query_builder
    pq = tmp_path / 'parquet'
    pq.mkdir()
    monkeypatch.setattr(dc, 'PARQUET_DIR', pq)
    monkeypatch.setattr(query_builder, 'PARQUET_DIR', pq)
    monkeypatch.setattr(grain_guard, 'PARQUET_DIR', pq)
    state = {'conflicting': frozenset()}
    monkeypatch.setattr(generation, 'current', lambda: {
        'id': 'g-test', 'status': 'present', 'built_at': None, 'grain_checked': True,
        'conflicting': state['conflicting'], 'duplicates': frozenset(),
        'duplicates_recorded': True})
    grain_guard._cache.clear()
    con = duckdb.connect()
    con.execute('CREATE TABLE matrices (matrix_code VARCHAR, parent_matrix_code VARCHAR)')
    con.execute('CREATE TABLE sdmx_column_map (matrix_code VARCHAR, '
                'sdmx_column_name VARCHAR, old_column_name VARCHAR)')
    yield pq, con, state
    grain_guard._cache.clear()


AREAS = [f'Judet {i}' for i in range(6)]


def _grain_case(pq, code, conflicting):
    rows = [(a, y, 10.0 + i) for i, a in enumerate(AREAS) for y in ('2022', '2023', '2024')]
    if conflicting:
        rows.append((AREAS[0], '2024', 99.0))         # same key, another value
    _write(pq / f'{code}.parquet', 'REF_AREA VARCHAR, TIME_PERIOD VARCHAR, OBS_VALUE DOUBLE',
           rows)
    dims = [_dim('REF_AREA', 'geo', AREAS), YEARS]
    ranked = [{'chart_type': 'horizontal_bar', 'score': 0.9, 'roles': {'x_axis': 'REF_AREA'}}]
    return dims, ranked


def test_grain_refused_tile_is_suppressed_with_its_reason(corpus):
    pq, con, state = corpus
    dims, ranked = _grain_case(pq, 'DUPG', conflicting=True)
    state['conflicting'] = frozenset({'DUPG'})
    sig = {**ADDITIVE, 'geo_count': 6}
    comp = compose_dashboard(sig, ranked, dims, actual_values=_actual(*dims),
                             conn=con, code='DUPG')
    assert comp['charts'] == []
    s = comp['suppressed'][0]
    assert s['id'] == 'horizontal_bar' and s['reason'] == 'conflicting_grain'
    assert s['evidence'] == 'slice_check'
    # Without conn/code the composer cannot see the grain (legacy call shape)
    assert compose_dashboard(sig, ranked, dims, actual_values=_actual(*dims))['charts']


def test_clean_slice_of_a_listed_file_is_kept(corpus):
    pq, con, state = corpus
    dims, ranked = _grain_case(pq, 'OKG', conflicting=False)
    state['conflicting'] = frozenset({'OKG'})       # listed, but this slice is clean
    comp = compose_dashboard({**ADDITIVE, 'geo_count': 6}, ranked, dims,
                             actual_values=_actual(*dims), conn=con, code='OKG')
    assert [c['id'] for c in comp['charts']][0] == 'horizontal_bar'
    assert not comp['suppressed']


def test_pins_that_never_co_occur_are_repicked(corpus):
    pq, con, _ = corpus
    cats = [f'Forma {i}' for i in range(6)]
    rows = ([('Milioane lei', y, c, 1.0) for y in ('2001', '2002', '2003') for c in cats]
            + [('Mii lei', y, c, 2.0) for y in ('2021', '2022', '2023') for c in cats])
    _write(pq / 'UNITX.parquet',
           'UNIT VARCHAR, TIME_PERIOD VARCHAR, CAT VARCHAR, OBS_VALUE DOUBLE', rows)
    dims = [_dim('UNIT', 'unit', ['Milioane lei', 'Mii lei']),
            _periods(['2001', '2002', '2003', '2021', '2022', '2023']),
            _dim('CAT', 'indicator', cats)]
    ranked = [{'chart_type': 'horizontal_bar', 'score': 0.9, 'roles': {'x_axis': 'CAT'}}]
    plain = compose_dashboard(ADDITIVE, ranked, dims, actual_values=_actual(*dims))
    assert plain['charts'][0]['data']['filters'] == {'UNIT': ['Milioane lei'],
                                                     'TIME_PERIOD': ['2023']}  # 0 rows
    comp = compose_dashboard(ADDITIVE, ranked, dims, actual_values=_actual(*dims),
                             conn=con, code='UNITX')
    spec = comp['charts'][0]['data']
    assert spec['filters'] == {'UNIT': ['Mii lei'], 'TIME_PERIOD': ['2023']}
    assert spec['slice_id'] != plain['charts'][0]['data']['slice_id']
    n = con.execute("SELECT count(*) FROM read_parquet(?) WHERE UNIT = 'Mii lei' "
                    "AND TIME_PERIOD = '2023'", [str(pq / 'UNITX.parquet')]).fetchone()[0]
    assert n == 6


# --------------------------------------------------------------- E10

MACROS = ['MACROREGIUNEA UNU', 'MACROREGIUNEA DOI', 'MACROREGIUNEA TREI',
          'MACROREGIUNEA PATRU']
RATE = {'primary_unit_type': 'percentage', '_measure': 'non_additive', 'time_points': 3}


def test_few_areas_without_a_national_row_are_series():
    dims = [YEARS, _dim('REF_AREA', 'geo', MACROS)]
    ranked = [{'chart_type': 'line', 'score': 0.9, 'roles': {'x_axis': 'TIME_PERIOD'}}]
    dc.retune_ranked_series(ranked, dims, RATE, _actual(*dims))
    assert ranked[0]['roles']['series'] == 'REF_AREA'
    tile = compose_dashboard(RATE, ranked, dims, actual_values=_actual(*dims))['charts'][0]
    assert tile['data']['group_by'] == ['TIME_PERIOD', 'REF_AREA']
    assert 'REF_AREA' not in tile['data']['filters']


def test_areas_with_a_national_row_stay_a_pin():
    geo = _dim('REF_AREA', 'geo', ['TOTAL', *MACROS])
    dims = [YEARS, geo]
    ranked = [{'chart_type': 'line', 'score': 0.9, 'roles': {'x_axis': 'TIME_PERIOD'}}]
    dc.retune_ranked_series(ranked, dims, RATE, _actual(*dims))
    assert ranked[0]['roles'].get('series') is None
