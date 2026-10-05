"""insights._source_total_gate: a summed KPI is published only when INS's own total
for the same slice agrees (kpi_total_checks, written by scripts/check-kpi-totals.py)."""
from types import SimpleNamespace

import duckdb
import pytest

from app.services.insights import _source_total_gate

DDL = ("CREATE TABLE kpi_total_checks (matrix_code VARCHAR PRIMARY KEY, period VARCHAR, ours DOUBLE, "
       "ins DOUBLE, rel DOUBLE, status VARCHAR, reason VARCHAR)")


def decision(*verifs, treatment='partition'):
    return SimpleNamespace(dimensions=[{'column': f'D{i}', 'treatment': treatment, 'verification': v}
                                       for i, v in enumerate(verifs)]
                           + [{'column': 'TIME_PERIOD', 'treatment': 'time', 'verification': None}])


@pytest.fixture
def conn():
    c = duckdb.connect()
    c.execute(DDL)
    c.executemany("INSERT INTO kpi_total_checks VALUES (?, ?, ?, ?, ?, ?, ?)", [
        ('OK1', '2023', 4862, 4862, 0.0, 'match', None),
        ('BAD1', '2023', 4960, 4862, 0.02, 'mismatch', None),
        ('NOTOT1', '2023', 7.0, None, None, 'unresolved', 'no_total_option:CATEGORY'),
        ('BLANK1', '2023', 7.0, None, None, 'ins_blank', None),
    ])
    return c


def test_match_publishes_with_the_source_value(conn):
    assert _source_total_gate(conn, 'OK1', decision('profile_flat')) == (
        None, {'source': 'INS', 'period': '2023', 'value': 4862.0, 'relative_diff': 0.0})


def test_mismatch_withholds_even_verified_structure(conn):
    assert _source_total_gate(conn, 'BAD1', decision('verified'))[0] == 'source_total_mismatch'


@pytest.mark.parametrize('code,reason', [('NOTOT1', 'no_source_total'), ('BLANK1', 'source_total_unchecked'),
                                         ('NEVER1', 'source_total_unchecked')])
def test_weak_verification_needs_a_match(conn, code, reason):
    assert _source_total_gate(conn, code, decision('verified', 'profile_flat'))[0] == reason
    assert _source_total_gate(conn, code, decision('metadata'))[0] == reason


def test_verified_sum_without_a_check_stands(conn):
    assert _source_total_gate(conn, 'NEVER1', decision('verified', 'curated')) == (None, None)


def test_unsummed_kpi_and_older_generation_are_untouched(conn):
    assert _source_total_gate(conn, 'BAD1', decision('profile_flat', treatment='pinned_value')) == (None, None)
    assert _source_total_gate(duckdb.connect(), 'BAD1', decision('profile_flat')) == (None, None)
