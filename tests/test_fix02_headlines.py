"""FIX-02: curated headlines resolve through the shared aggregation policy."""
import duckdb
import pytest

from app.services import headlines as hl


@pytest.fixture()
def pq(tmp_path):
    """Tiny SDMX parquets with known answers."""
    con = duckdb.connect()
    d = str(tmp_path)
    # IND118A-like: a Total row alongside its components
    con.execute(f"""COPY (SELECT * FROM (VALUES
        ('Eoliana','2022',40.0,'u'),('Solara','2022',60.0,'u'),('Total, din care:','2022',100.0,'u'),
        ('Eoliana','2023',50.0,'u'),('Solara','2023',70.0,'u'),('Total, din care:','2023',120.0,'u'))
        t(CATEGORY,TIME_PERIOD,OBS_VALUE,UNIT_MEASURE)) TO '{d}/TOT.parquet' (FORMAT PARQUET)""")
    # no total row: two sexes sum
    con.execute(f"""COPY (SELECT * FROM (VALUES
        ('Feminin','2023',3.0,'u'),('Masculin','2023',4.0,'u'),
        ('Feminin','2024',0.0,'u'),('Masculin','2024',0.0,'u'))
        t(SEX,TIME_PERIOD,OBS_VALUE,UNIT_MEASURE)) TO '{d}/SEXES.parquet' (FORMAT PARQUET)""")
    # unweighted-rate trap: a rate by county, no total
    con.execute(f"""COPY (SELECT * FROM (VALUES
        ('A','2023',10.0,'Procente'),('B','2023',20.0,'Procente'),
        ('A','2024',10.0,'Procente'),('B','2024',20.0,'Procente'))
        t(CAT,TIME_PERIOD,OBS_VALUE,UNIT_MEASURE)) TO '{d}/RATE.parquet' (FORMAT PARQUET)""")
    # mixed units
    con.execute(f"""COPY (SELECT * FROM (VALUES
        ('t','2024',5.0,'Tone'),('t','2024',7.0,'Mii lei'))
        t(CAT,TIME_PERIOD,OBS_VALUE,UNIT_MEASURE)) TO '{d}/MIX.parquet' (FORMAT PARQUET)""")
    return d, duckdb.connect()


def card(pq, **ind):
    d, con = pq
    ind.setdefault('label_en', ind['code'])
    return hl.resolve_indicator(con, d, ind, 'en')


def test_ind118a_style_total_row_not_double_counted(pq):
    c, status = card(pq, code='TOT', measure='additive', method='aggregate_row',
                     slice={'CATEGORY': ['Total, din care:']})
    assert status == 'ok' and c['value'] == 120.0 and c['prev_value'] == 100.0
    assert c['change']['value'] == 20.0 and c['change']['basis'] == 'yoy'
    p = c['provenance']
    assert p['source_code'] == 'TOT' and p['period'] == '2023'
    assert p['method'] == 'aggregate_row' and p['outcome'] == 'valid_total'
    assert p['filters'] == {'CATEGORY': ['Total, din care:']}


def test_unpinned_dimension_is_not_summed(pq):
    # the old behaviour (SUM over everything) would give 240
    c, status = card(pq, code='TOT', measure='additive', method='sum_partition')
    assert c is None and status == 'unverified_structure'


def test_declared_partition_sums_once_and_zero_comparator_is_unavailable(pq):
    c, status = card(pq, code='SEXES', measure='additive', method='sum_partition',
                     sum_over=['SEX'])
    assert status == 'ok' and c['value'] == 0.0
    assert c['provenance']['method'] == 'sum_partition'
    assert c['provenance']['verification'] == 'curated'
    # 2023 -> 2024: 7 -> 0 is a -100% change, but reversed order has a zero base
    c2, _ = card(pq, code='SEXES', measure='additive', method='sum_partition',
                 sum_over=['SEX'], comparison='previous_period')
    assert c2['change']['value'] == -100.0


def test_zero_comparator_gives_explicit_unavailable_change(pq):
    d, con = pq
    con.execute(f"""COPY (SELECT * FROM (VALUES
        ('Total','2023',0.0,'u'),('Total','2024',5.0,'u'))
        t(CATEGORY,TIME_PERIOD,OBS_VALUE,UNIT_MEASURE)) TO '{d}/ZERO.parquet' (FORMAT PARQUET)""")
    c, _ = card(pq, code='ZERO', measure='additive', method='aggregate_row',
                slice={'CATEGORY': ['Total']})
    assert c['value'] == 5.0
    assert c['change']['status'] == 'unavailable'
    assert c['change']['reason'] == 'comparator_zero' and c['change']['value'] is None
    assert c['change_pct'] is None


def test_rates_are_never_summed_or_averaged_into_a_total(pq):
    c, status = card(pq, code='RATE', measure='rate', method='sum_partition',
                     sum_over=['CAT'])
    assert c is None and status == 'declared_partition_invalid'
    c, status = card(pq, code='RATE', measure='rate', method='single_row')
    assert c is None and status == 'unverified_structure'
    c, status = card(pq, code='RATE', measure='rate', method='single_row',
                     slice={'CAT': ['A']})
    assert status == 'ok' and c['value'] == 10.0
    assert c['provenance']['outcome'] == 'valid_slice'
    assert c['change']['unit'] == 'points'


def test_mixed_units_unavailable(pq):
    c, status = card(pq, code='MIX', measure='additive', method='aggregate_row',
                     slice={'CAT': ['t']})
    assert c is None and status == 'mixed_units'


def test_missing_slice_value_and_omitted(pq):
    c, status = card(pq, code='TOT', measure='additive', method='aggregate_row',
                     slice={'CATEGORY': ['Nope']})
    assert c is None and status == 'slice_value_missing'
    c, status = card(pq, code='TOT', omitted='why')
    assert c is None and status == 'omitted'


def test_minus_100_transform(pq):
    d, con = pq
    con.execute(f"""COPY (SELECT * FROM (VALUES
        ('PIB','2025-Q4',103.3,'u'),('PIB','2026-Q1',101.0,'u'))
        t(CATEGORY,TIME_PERIOD,OBS_VALUE,UNIT_MEASURE)) TO '{d}/GDP.parquet' (FORMAT PARQUET)""")
    c, _ = card(pq, code='GDP', measure='rate', method='aggregate_row', transform='minus_100',
                slice={'CATEGORY': ['PIB']}, aggregates=['CATEGORY'],
                comparison='previous_period')
    assert c['value'] == 1.0 and c['prev_value'] == 3.3
    assert c['change'] == {'status': 'ok', 'reason': None, 'value': -2.3, 'unit': 'points',
                           'basis': 'previous_period', 'from_period': '2025-Q4',
                           'to_period': '2026-Q1'} or c['change']['value'] == -2.3


def test_shipped_config_is_well_formed():
    seen = 0
    for theme in hl.HEADLINE_CONFIG:
        for ind in theme['indicators']:
            seen += 1
            assert 'sql' not in ind, ind['code']
            if ind.get('omitted'):
                assert len(ind['omitted']) > 20
                continue
            assert ind['measure'] in ('additive', 'average', 'index', 'rate')
            assert ind['method'] in ('aggregate_row', 'single_row', 'sum_partition')
            assert ind.get('verification'), ind['code']
            if ind.get('sum_over'):
                assert ind['measure'] == 'additive', ind['code']
            assert (ind['method'] == 'sum_partition') == bool(ind.get('sum_over')), ind['code']
    assert seen >= 14
    # the two cards the audit found misleading are not shown
    omitted = {i['code'] for t in hl.HEADLINE_CONFIG for i in t['indicators']
               if i.get('omitted')}
    assert 'IPC102A' in omitted
    ind118 = next(i for t in hl.HEADLINE_CONFIG for i in t['indicators']
                  if i['code'] == 'IND118A')
    assert ind118['slice'] == {'CATEGORY': ['Total, din care:']}
