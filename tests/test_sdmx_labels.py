"""Tests for sdmx_labels.py — label normalisation and time-period parsing."""
import sys
sys.path.insert(0, '.')

from sdmx_labels import norm_label, clean_label, parse_time_period


def test_norm_label_comma_mangled_matches_original():
    # INS CSVs replace ',' inside values with a space; metadata keeps the comma.
    csv_form = "De calatori  de cale normala"
    meta_form = "De calatori, de cale normala"
    assert norm_label(csv_form) == norm_label(meta_form)


def test_norm_label_strips_indentation():
    assert norm_label("   Bucuresti") == norm_label("Bucuresti")


def test_norm_label_collapses_repeated_spaces():
    assert norm_label("Statiuni din zona   litorala") == "statiuni din zona litorala"


def test_norm_label_lowercases():
    assert norm_label("Romani") == "romani"


def test_norm_label_none_and_empty():
    assert norm_label(None) == ""
    assert norm_label("") == ""


def test_clean_label_preserves_case_collapses_comma_and_space():
    assert clean_label("Statiuni din zona litorala,  exclusiv orasul Constanta") == \
        "Statiuni din zona litorala exclusiv orasul Constanta"


def test_parse_time_period_annual():
    assert parse_time_period("Anul 2020") == "2020"


def test_parse_time_period_bare_year():
    assert parse_time_period("2020") == "2020"


def test_parse_time_period_quarterly():
    assert parse_time_period("Trimestrul IV 2024") == "2024-Q4"


def test_parse_time_period_monthly_name():
    assert parse_time_period("Luna februarie 2026") == "2026-02"


def test_parse_time_period_monthly_numeric():
    assert parse_time_period("Luna 3 2020") == "2020-03"


def test_parse_time_period_year_range():
    assert parse_time_period("Anii 2010-2012") == "2010-P3Y"


def test_parse_time_period_semester():
    assert parse_time_period("Semestrul II 2019") == "2019-S2"


def test_parse_time_period_unparseable_returns_none():
    assert parse_time_period("Statiuni balneare") is None
