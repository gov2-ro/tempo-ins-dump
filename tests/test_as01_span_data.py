"""AS-01 end to end: single years plus ONE band that spans them (the old POPX shape).

The band is INS's own total for the range, so an unfiltered request pins it
(`aggregate_row`) and returns the band's cell. It is never the sum of the singles.
"""
import json

from at01_fixtures import add_dataset, make_env

AGE = ("AGE", "Varsta", "age",
       [(f"{a} ani", dict(age_min=a, age_max=a)) for a in range(3)]
       + [("0-2 ani", dict(age_min=0, age_max=2))])
TIME = ("TIME_PERIOD", "Ani", "time", [("2025", dict(year=2025))])


def build(corpus):
    rows = [(f"{a} ani", "2025", 10.0) for a in range(3)] + [("0-2 ani", "2025", 31.0)]
    add_dataset(corpus, "SPANX", [AGE, TIME], rows, name="SPANX")


def test_span_band_is_pinned_and_its_value_returned(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, build=build)
    r = env.client.get("/api/datasets/SPANX/data",
                       params={"group_by": json.dumps(["TIME_PERIOD"]), "filters": "{}"})
    assert r.status_code == 200
    body = r.json()
    assert not body.get("unavailable")
    assert body["aggregation"]["method"] == "aggregate_row"
    assert body["aggregation"]["filters"]["AGE"] == ["0-2 ani"]
    assert [row[-1] for row in body["rows"]] == [31.0]        # the band's cell, not 30 (the singles' sum)


def test_insights_headline_uses_the_pinned_band_not_the_sum(tmp_path, monkeypatch):
    """The composer's slice leaves AGE unfiltered; only the decision pins the band.
    Insights must fetch with the decision's filters (31), not sum every band (61)."""
    env = make_env(tmp_path, monkeypatch, build=build)
    r = env.client.get("/api/datasets/SPANX/insights", params={"lang": "ro"})
    assert r.status_code == 200
    latest = [k for k in r.json().get("kpis", []) if k.get("key") == "latest"]
    assert latest and latest[0]["value"] == 31.0
