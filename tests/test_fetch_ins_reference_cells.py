"""fetch-ins-reference-cells: request building and answer checks (no network)."""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "fetch_ref", Path(__file__).resolve().parent.parent / "scripts" / "fetch-ins-reference-cells.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)


def _opt(i, label):
    return {"label": label, "nomItemId": i}


META = {
    "details": {"matMaxDim": 3, "matUMSpec": 0, "matRegJ": 0},
    "dimensionsMap": [
        {"label": "Sexe", "options": [_opt(1, "Total "), _opt(2, "Masculin "), _opt(3, "Feminin ")]},
        {"label": "Judete", "options": [_opt(10, "TOTAL"), _opt(11, "MACROREGIUNEA UNU"),
                                        _opt(12, "Regiunea NORD-VEST"), _opt(13, "Cluj"),
                                        _opt(14, "Municipiul Bucuresti")]},
        {"label": "Perioade", "options": [_opt(20, "Anul 2023"), _opt(21, "Anul 2024")]},
    ],
}


def test_builds_total_and_county_cells():
    payload, labels = fr.build_request(META, {"id": "q", "matrix": "SOM103A", "select": [
        {"pick": "total"}, {"pick": "counties", "total": True},
        {"pick": "years", "from": 2024, "to": 2024}]})
    assert payload["encQuery"] == "1:10,13,14:21"
    assert labels == [["Total"], ["TOTAL", "Cluj", "Municipiul Bucuresti"], ["Anul 2024"]]


def test_missing_year_or_label_is_an_error_not_a_smaller_query():
    with pytest.raises(ValueError):
        fr.build_request(META, {"id": "q", "matrix": "X", "select": [
            {"pick": "total"}, {"pick": "all"}, {"pick": "years", "from": 2022, "to": 2024}]})
    with pytest.raises(ValueError):
        fr.build_request(META, {"id": "q", "matrix": "X", "select": [
            {"pick": "labels", "labels": ["Ambele"]}, {"pick": "all"}, {"pick": "all"}]})


def test_pick_count_must_match_dimensions():
    with pytest.raises(ValueError):
        fr.build_request(META, {"id": "q", "matrix": "X", "select": [{"pick": "total"}]})


def test_summarize_flags_unrequested_labels_and_blanks():
    labels = [["Total"], ["TOTAL", "Cluj"], ["Anul 2024"]]
    good = "Sexe, Judete, Perioade, Valoare\nTotal, TOTAL, Anul 2024, 3.3\nTotal, Cluj, Anul 2024, :\n"
    s = fr.summarize(good, labels)
    assert s == {**s, "rows": 2, "blank_or_suppressed": 1, "labels_ok": True}
    renumbered = "Sexe, Judete, Perioade, Valoare\nTotal, Iasi, Anul 2024, 3.6\n"
    assert fr.summarize(renumbered, labels)["labels_ok"] is False
