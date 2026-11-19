"""A cited published answer reproduces: the selection carries `value_source`, the live link and the
evidence bundle serve the same INS cell the tool returned. Ordinary selections keep their shape."""
import csv
import io
import json
import zipfile
from urllib.parse import urlparse

import pytest
from at01_fixtures import GENERATION, call
from test_aq13_published_tools import build

PUB = {"REF_AREA": ["Beta"], "TIME_PERIOD": ["2022"]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from at01_fixtures import make_env
    return make_env(tmp_path, monkeypatch, build=build)


def path_of(url: str) -> str:
    u = urlparse(url)
    return u.path + "?" + u.query


def links_of(selection, generation=GENERATION):
    e = call("get_evidence_links", selection=selection, generation_id=generation, lang="en")
    return e, {link["kind"]: link["url"] for link in e["data"]["links"]} if e["status"] == "ok" else {}


def bundle(env, url):
    r = env.client.get(path_of(url))
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return z, {n: z.read(n).decode() for n in z.namelist()}


def published_answer(dataset="RATEPUB", filters=PUB):
    e = call("query_data", dataset=dataset, filters=filters, group_by=["TIME_PERIOD"], lang="en")
    assert e["status"] == "ok" and e["data"]["value_source"] == "ins_published"
    return e


# ------------------------------------------------------------------ a. the published case

def test_the_published_answer_reproduces_through_its_links(env):
    e = published_answer()
    sel = e["provenance"]["selection"]
    assert sel["value_source"] == "ins_published"
    gid = e["provenance"]["generation"]["id"]
    links, by = links_of(sel, gid)
    assert links["status"] == "ok" and links["data"]["selection"]["value_source"] == "ins_published"
    assert "value_source=ins_published" in by["live_selection"] and "value_source=ins_published" in by["evidence"]
    assert "value_source" not in by["csv"] and "value_source" not in by["dataset"]

    live = env.client.get(path_of(by["live_selection"])).json()
    assert live["unavailable"] is False and live["value_source"] == "ins_published"
    assert live["columns"] == e["data"]["columns"] and live["rows"] == e["data"]["rows"]
    assert live["published_total"] == e["data"]["published_total"]
    assert live["aggregation"] == e["provenance"]["aggregation"]
    assert live["contract"] == "tempo-query/1" and live["generation"]["id"] == gid
    assert live["truncated"] is False and live["total_rows"] == 1 and live["column_labels"] == {}

    z, files = bundle(env, by["evidence"])
    manifest = json.loads(files["manifest.json"])
    assert manifest["generation"]["id"] == gid
    assert set(files) == {"manifest.json", "README.txt", "attribution.json", "method.json", "result.csv",
                          "selection.json"}
    rows = list(csv.reader(io.StringIO(files["result.csv"])))
    assert rows[0] == e["data"]["columns"]
    cell = e["data"]["rows"][0]                 # [area, period, unit, value]
    assert rows[1][:3] == cell[:3] and float(rows[1][3]) == cell[3] == 103
    method = json.loads(files["method.json"])
    assert method["kind"] == "ins_published" and method["value_source"] == "ins_published"
    assert method["published_total"] == e["data"]["published_total"]
    fetch = method["published_total"]["fetches"][0]
    assert (fetch["query_id"], fetch["sha256"], fetch["ins_updated"]) == ("RATEPUB-total", "abc", "05-01-2026")
    assert method["unit"] == "Procente" or method["unit"] is None
    attr = json.loads(files["attribution.json"])
    assert "RATEPUB" in {s["dataset"] for s in attr["sources"]}
    assert any(s["source_updated"] == "05-01-2026" for s in attr["sources"])
    sel_json = json.loads(files["selection.json"])
    assert sel_json["requested"]["value_source"] == "ins_published" and sel_json["periods_in_result"] == ["2022"]
    assert "result.csv" in files["README.txt"]


def test_a_published_series_and_a_breakdown_reproduce(env):
    e = call("query_data", dataset="SEXPUB", filters={"SEX": ["Feminin"], "TIME_PERIOD": ["2022"]},
             group_by=["TIME_PERIOD"])
    _, by = links_of(e["provenance"]["selection"])
    live = env.client.get(path_of(by["live_selection"])).json()
    assert live["rows"] == e["data"]["rows"] == [["TOTAL", "2022", "Feminin", "Procente", 52]]
    series = call("query_data", dataset="RATEPUB", filters={"REF_AREA": ["Alfa"]}, group_by=["TIME_PERIOD"])
    _, by = links_of(series["provenance"]["selection"])
    live = env.client.get(path_of(by["live_selection"])).json()
    assert live["rows"] == series["data"]["rows"] and len(live["rows"]) == 2


def test_the_old_links_still_refuse_a_published_cut(env):
    """The marker is what makes the route serve cells; without it `/data` refuses as before."""
    r = env.client.get("/api/datasets/RATEPUB/data", params={
        "filters": json.dumps(PUB), "group_by": '["TIME_PERIOD"]'}).json()
    assert r["unavailable"] is True and r["rows"] == []


# ------------------------------------------------------------------ b. ordinary citations

def test_an_ordinary_selection_has_no_value_source_and_reproduces(env):
    f = {"REF_AREA": ["Alfa"], "TIME_PERIOD": ["2021"], "RESIDENCE": ["Urban"]}
    raw = call("query_data", dataset="RATEPUB", filters=f)
    assert raw["data"].get("value_source") is None and "value_source" not in raw["provenance"]["selection"]
    links, by = links_of(raw["provenance"]["selection"])
    assert "value_source" not in links["data"]["selection"] and "value_source" not in json.dumps(by)
    live = env.client.get(path_of(by["live_selection"])).json()
    assert live["rows"] == raw["data"]["rows"]
    _, files = bundle(env, by["evidence"])
    assert json.loads(files["method.json"])["kind"] == "raw_observations"

    summed = call("query_data", dataset="CNT", filters={"REF_AREA": ["Alfa"]},
                  group_by=["TIME_PERIOD", "RESIDENCE"])
    assert summed["status"] == "ok" and "value_source" not in summed["provenance"]["selection"]
    _, by = links_of(summed["provenance"]["selection"])
    live = env.client.get(path_of(by["live_selection"])).json()
    assert live["rows"] == summed["data"]["rows"] and "value_source" not in json.dumps(by)


def test_an_ordinary_selection_keeps_its_exact_dump(env):
    from app.services.tools import schemas as S
    d = S.DatasetSelection(kind="dataset", dataset="CNT").model_dump(mode="json", by_alias=True, exclude_none=False)
    assert "value_source" not in d
    p = S.DatasetSelection(kind="dataset", dataset="CNT", value_source="ins_published").model_dump()
    assert p["value_source"] == "ins_published"


# ------------------------------------------------------------------ c. generation

def test_a_changed_generation_refuses_links_and_evidence(env):
    published = published_answer()["provenance"]["selection"]
    ordinary = call("query_data", dataset="CNT", filters={"REF_AREA": ["Alfa"]},
                    group_by=["TIME_PERIOD"])["provenance"]["selection"]
    for sel in (published, ordinary):
        e = call("get_evidence_links", selection=sel, generation_id="another-generation")
        assert e["status"] == "unavailable" and e["reason"] == "generation_changed"
        _, by = links_of(sel)
        stale = path_of(by["evidence"]).replace(f"expected_generation={GENERATION}", "expected_generation=other")
        assert env.client.get(stale).status_code == 409


# ------------------------------------------------------------------ d. no published cells

def test_value_source_without_cells_is_refused(env):
    sel = {"kind": "dataset", "dataset": "RATENONE", "filters": PUB, "group_by": ["TIME_PERIOD"],
           "approximate": False, "value_source": "ins_published"}
    e = call("get_evidence_links", selection=sel, generation_id=GENERATION)
    assert e["status"] == "error" and e["reason"] == "invalid_input"
    for route in ("data", "evidence"):
        r = env.client.get(f"/api/datasets/RATENONE/{route}", params={
            "filters": json.dumps(PUB), "group_by": '["TIME_PERIOD"]', "value_source": "ins_published"})
        assert r.status_code == 404
    r = env.client.get("/api/datasets/RATEPUB/data", params={"filters": "{}", "value_source": "other"})
    assert r.status_code == 422


def test_a_cut_without_a_cell_is_a_404_not_an_empty_answer(env):
    r = env.client.get("/api/datasets/RATEPUB/data", params={
        "filters": json.dumps({"RESIDENCE": ["Urban"], "TIME_PERIOD": ["2021"]}),
        "group_by": '["TIME_PERIOD"]', "value_source": "ins_published"})
    assert r.status_code == 404 and "not available" in r.json()["detail"]
