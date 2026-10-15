"""AT-01b: shared scope disclosure for incomplete domains.

A statistically valid partition is not an exhaustive one: the single-age
population children hold ages 0-84, "85 ani si peste" lives in the grouped-age
sibling, and summing AGE over the child is `valid_total` anyway. These tests pin
the `scope` that REST `/data`, the static engine and the insights KPI report
identically (app/services/scope.py is the specification).

AGEX  the child: AGE metadata is Total (0-999) + "0 ani".."2 ani" (padded
      labels, as the real child), data holds the three single years only.
      Per year 90 people (x2 in 2025), ages 3+ are not in this dataset.
AGEG  the grouped-age sibling: bands "0-2 ani" (90) and "3 ani si peste" (10).
"""
import copy
import json
import shutil
from pathlib import Path

import duckdb
import pytest

from fix02b_corpus import _write, build_corpus, make_client

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = json.loads((Path(__file__).with_name("at01_scope_golden.json")).read_text(encoding="utf-8"))

AGE_COLS = "AGE VARCHAR, SEX VARCHAR, TIME_PERIOD VARCHAR, OBS_VALUE DOUBLE"
YEARS = (("2024", 1.0), ("2025", 2.0))
SEXES = ("Masculin", "Feminin")
AGEX_ROWS = [(f"{a} ani", sex, y, 15.0 * k) for y, k in YEARS for sex in SEXES for a in range(3)]
AGEG_ROWS = [(band, sex, y, v * k) for y, k in YEARS for sex in SEXES
             for band, v in (("0-2 ani", 45.0), ("3 ani si peste", 5.0))]
AGEX_TOTALS = {"2024": 90.0, "2025": 180.0}
AGEG_TOTALS = {"2024": 100.0, "2025": 200.0}

# (data value, display label, parsed age range); the child's Total is in metadata only
AGEX_OPTIONS = [("Total", "Total", (0, 999))] + [
    (f"{a} ani", f"      {a} ani", (a, a)) for a in range(3)]
AGEG_OPTIONS = [("Total", "Total", (0, 999)), ("0-2 ani", "0-2 ani", (0, 2)),
                ("3 ani si peste", "3 ani si peste", (3, 999))]


def _add_age_dataset(corpus, code, rows, age_options):
    _write(corpus / "parquet" / f"{code}.parquet", AGE_COLS, rows)
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    did = db.execute("SELECT coalesce(max(dimension_id), 0) FROM dimensions").fetchone()[0]
    nid = db.execute("SELECT coalesce(max(nom_item_id), 0) FROM dimension_options").fetchone()[0]
    db.execute("INSERT INTO matrices (matrix_code, matrix_name, matrix_name_en, row_count, "
               "definitie) VALUES (?, ?, ?, ?, ?)", [code, "Populatia", "Population", len(rows), "Populatia"])
    db.execute("INSERT INTO matrix_profiles (matrix_code, primary_unit_type, archetype, time_year_min, "
               "time_year_max, unit_types) VALUES (?, 'count', 'x', 2024, 2025, '[]')", [code])
    dims = [
        ("AGE", "Grupe de varsta", "age",
         [(v, lbl, dict(age_min=lo, age_max=hi)) for v, lbl, (lo, hi) in age_options]),
        ("SEX", "Sexe", "gender", [(s, s, dict(gender=s[0])) for s in SEXES]),
        ("TIME_PERIOD", "Ani", "time", [(y, y, dict(year=int(y))) for y, _ in YEARS]),
    ]
    for i, (col, dlabel, dtype, opts) in enumerate(dims, 1):
        did += 1
        db.execute("INSERT INTO dimensions VALUES (?, ?, ?, ?, ?, ?)", [did, code, i, dlabel, col, len(opts)])
        for off, (value, label, parsed) in enumerate(opts):
            nid += 1
            db.execute("INSERT INTO dimension_options VALUES (?, ?, ?, ?, NULL)", [did, nid, label, off])
            p = {"year": None, "gender": None, "age_min": None, "age_max": None, **parsed}
            db.execute("INSERT INTO dimension_options_parsed VALUES "
                       "(?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?, NULL, NULL, 0.9)",
                       [nid, dtype, p["year"], p["gender"], p["age_min"], p["age_max"]])
            db.execute("INSERT INTO sdmx_codes VALUES (?, ?, ?)", [nid, value, value])
    db.close()


def add_age_datasets(corpus, *, verified_sex=False, verified_age_level=False):
    """AGEX and AGEG on top of the fix02b corpus. `verified_*` add dimension_structure
    rows (the corpus must have been built with structure=True)."""
    _add_age_dataset(corpus, "AGEX", AGEX_ROWS, AGEX_OPTIONS)
    _add_age_dataset(corpus, "AGEG", AGEG_ROWS, AGEG_OPTIONS)
    db = duckdb.connect(str(corpus / "metadata.duckdb"))

    def level(code, col, level_id, members):
        levels = json.dumps([{"level_id": level_id, "name": level_id, "verified": True,
                              "members": members}])
        db.execute("INSERT INTO dimension_structure VALUES (?, ?, ?, ?, 1, NULL, FALSE, NULL, NULL, "
                   "1.0, 1.0, 'verified', 'test')", [code, col, levels, level_id])
    if verified_sex:
        for code in ("AGEX", "AGEG"):
            level(code, "SEX", "sex", list(SEXES))
    if verified_age_level:
        level("AGEX", "AGE", "age_y1", [f"{a} ani" for a in range(3)])
    db.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch)
    add_age_datasets(tmp_path / "corpus")
    return c


@pytest.fixture
def client_verified(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch, structure=True)
    add_age_datasets(tmp_path / "corpus", verified_sex=True)
    return c


def q(client, code, group_by=None, filters=None, **kw):
    params = {"filters": json.dumps(filters or {}), **kw}
    if group_by is not None:
        params["group_by"] = json.dumps(group_by)
    r = client.get(f"/api/datasets/{code}/data", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def by_period(body):
    return {r[0]: r[-1] for r in body["rows"]}


AGEX_RESTRICTION = {"column": "AGE", "kind": "age_range", "covered": [[0, 2]], "domain": [0, None]}


# ------------------------------------------------ 1. the numerical fixture

def test_single_age_child_keeps_its_value_and_discloses_the_missing_ages(client):
    body = q(client, "AGEX", ["TIME_PERIOD"])
    # the value is the child's honest 0-2 sum: unchanged, never 100
    assert by_period(body) == AGEX_TOTALS
    assert body["aggregation"]["outcome"] == "valid_total"
    assert body["aggregation"]["method"] == "sum_partition"
    scope = body["scope"]
    assert scope["domain_complete"] is False
    assert scope["restrictions"] == [{**AGEX_RESTRICTION, "requested": False}]


def test_grouped_age_sibling_has_the_whole_domain(client):
    body = q(client, "AGEG", ["TIME_PERIOD"])
    assert by_period(body) == AGEG_TOTALS
    assert body["scope"]["restrictions"] == []
    assert body["scope"]["domain_complete"] is not False


def test_verified_structure_does_not_hide_a_partial_domain(tmp_path, monkeypatch):
    """A verified single-year level is a valid partition, not a complete one."""
    c = make_client(tmp_path, monkeypatch, structure=True)
    add_age_datasets(tmp_path / "corpus", verified_sex=True, verified_age_level=True)
    body = q(c, "AGEX", ["TIME_PERIOD"])
    assert body["aggregation"]["levels"] == {"AGE": "age_y1", "SEX": "sex"}
    assert {d["column"]: d["treatment"] for d in body["aggregation"]["dimensions"]}["AGE"] == "level"
    assert by_period(body) == AGEX_TOTALS
    assert body["scope"]["domain_complete"] is False
    assert body["scope"]["restrictions"] == [{**AGEX_RESTRICTION, "requested": False}]


def test_complete_and_verified_domain_is_true(client_verified):
    body = q(client_verified, "AGEG", ["TIME_PERIOD"])
    assert body["scope"] == {"domain_complete": True, "restrictions": []}
    # same verified SEX level, but the child still lacks ages: false, not true
    assert q(client_verified, "AGEX", ["TIME_PERIOD"])["scope"]["domain_complete"] is False


def test_grouped_age_axis_is_disclosed_too(client):
    body = q(client, "AGEX", ["AGE"], {"TIME_PERIOD": ["2024"]})
    assert sorted(r[0] for r in body["rows"]) == ["0 ani", "1 ani", "2 ani"]
    assert body["scope"]["domain_complete"] is False
    assert body["scope"]["restrictions"] == [{**AGEX_RESTRICTION, "requested": False}]


# ------------------------------------------- 2. an explicit request is the asked scope

def test_explicit_age_filter_is_a_requested_restriction(client):
    covered = ["0 ani", "1 ani", "2 ani"]
    body = q(client, "AGEX", ["TIME_PERIOD"], {"AGE": covered})
    assert by_period(body) == AGEX_TOTALS
    scope = body["scope"]
    assert scope["restrictions"] == [{**AGEX_RESTRICTION, "requested": True}]
    assert scope["domain_complete"] is not False


def test_explicit_narrower_filter_reports_what_was_asked(client):
    body = q(client, "AGEX", ["TIME_PERIOD"], {"AGE": ["1 ani"]})
    assert by_period(body) == {"2024": 30.0, "2025": 60.0}
    assert body["scope"]["restrictions"] == [
        {"column": "AGE", "kind": "age_range", "covered": [[1, 1]], "domain": [0, None],
         "requested": True}]
    assert body["scope"]["domain_complete"] is not False


def test_requested_sibling_slice_discloses_its_band(client):
    body = q(client, "AGEG", ["TIME_PERIOD"], {"AGE": ["3 ani si peste"]})
    assert by_period(body) == {"2024": 10.0, "2025": 20.0}
    assert body["scope"]["restrictions"] == [
        {"column": "AGE", "kind": "age_range", "covered": [[3, None]], "domain": [0, None],
         "requested": True}]


# ----------------------------------------------- 3. complete / unknown / false

def test_total_pinned_additive_dataset_is_complete(client):
    body = q(client, "ADDX", ["TIME_PERIOD"])
    assert body["scope"] == {"domain_complete": True, "restrictions": []}


def test_flat_partition_without_verification_is_unknown(client):
    # AGEG's AGE partition is proven complete, its SEX partition is only 'metadata'
    body = q(client, "AGEG", ["TIME_PERIOD"])
    verif = {d["column"]: d["verification"] for d in body["aggregation"]["dimensions"]}
    assert verif["SEX"] == "metadata"
    assert body["scope"] == {"domain_complete": None, "restrictions": []}


# --------------------------------------------- 4. only executed grouped results

def test_raw_and_unavailable_responses_have_no_scope(client):
    raw = q(client, "ADDX", None, {"TIME_PERIOD": ["2023"]})
    assert "scope" not in raw
    unavailable = q(client, "POPX", ["TIME_PERIOD"])
    assert unavailable["unavailable"] is True and "scope" not in unavailable
    assert "scope" not in q(client, "RATEX", ["TIME_PERIOD"])      # missing_weights


GOLDEN_CASES = [
    ("ADDX", {"group_by": ["TIME_PERIOD"]}),
    ("ADDX", {"group_by": ["CATEGORY"], "filters": {"TIME_PERIOD": ["2023"]}}),
    ("ADDX", {"group_by": ["TIME_PERIOD"], "filters": {"CATEGORY": ["A"]}}),
    ("ADDX", {"filters": {"TIME_PERIOD": ["2023"]}}),
    ("POPX", {"group_by": ["TIME_PERIOD"]}),
    ("POPX", {"group_by": ["AGE"], "filters": {"TIME_PERIOD": ["2025"]}}),
    ("POPX", {"group_by": ["TIME_PERIOD"], "filters": {"AGE": ["0-4 ani"]}}),
    ("POPX", {"group_by": ["TIME_PERIOD"], "filters": {"AGE": ["0 ani", "1 ani"]}}),
    ("POPX", {"filters": {"TIME_PERIOD": ["2025"]}}),
    ("RATEX", {"group_by": ["TIME_PERIOD"]}),
    ("RATEX", {"group_by": ["TIME_PERIOD"], "approximate": True}),
    ("RATEX", {"group_by": ["REF_AREA"], "filters": {"TIME_PERIOD": ["2024"]}}),
    ("INCX", {"group_by": ["TIME_PERIOD"]}),
    ("INCX", {"group_by": ["TIME_PERIOD"],
              "filters": {"VENITURI": ["media veniturilor disponibile pe adult-echivalent"]}}),
    ("INCX", {"group_by": ["SEX"], "filters": {
        "TIME_PERIOD": ["2024"], "VENITURI": ["mediana veniturilor disponibile pe adult-echivalent"]}}),
]


@pytest.mark.parametrize("structure", [False, True], ids=["unprofiled", "structure"])
def test_existing_response_fields_are_unchanged(tmp_path, monkeypatch, structure):
    """Every pre-existing key and value equals the answer recorded on the base
    commit (c5eca0d, before `scope` existed); only `scope` is new."""
    c = make_client(tmp_path, monkeypatch, structure=structure)
    prefix = "S" if structure else "N"
    for code, spec in GOLDEN_CASES:
        params = {"filters": json.dumps(spec.get("filters", {}))}
        if "group_by" in spec:
            params["group_by"] = json.dumps(spec["group_by"])
        if spec.get("approximate"):
            params["approximate"] = "1"
        r = c.get(f"/api/datasets/{code}/data", params=params)
        key = f"{prefix}|{code}|{json.dumps(spec, sort_keys=True)}"
        if key not in GOLDEN:                # the base answer was an HTTP error
            assert r.status_code != 200, key
            continue
        assert r.status_code == 200, key
        body = r.json()
        scope = body.pop("scope", None)
        assert body == GOLDEN[key], key
        assert (scope is not None) == bool(spec.get("group_by") and not body.get("unavailable")), key


# ---------------------------------------------------------- 5. immutable caches

def test_scope_never_mutates_the_cached_context_or_decision(client):
    from app.db import get_conn
    from app.services import dataset_meta as dm
    from app.services import scope
    conn = get_conn()
    ctx = dm.get_aggregation_context(conn, "AGEX")
    decision = dm.decide_grouped(ctx, ["TIME_PERIOD"], {}).to_dict()
    ctx_before, decision_before = copy.deepcopy(ctx), copy.deepcopy(decision)
    first = scope.result_scope(ctx, decision, {}, ["TIME_PERIOD"])
    scope.dimension_coverage(ctx, "AGE")
    scope.dimension_coverage(ctx, "AGE", ["0 ani"])
    scope.dataset_restrictions(ctx)
    assert scope.result_scope(ctx, decision, {}, ["TIME_PERIOD"]) == first
    q(client, "AGEX", ["TIME_PERIOD"], {"AGE": ["0 ani"]})
    q(client, "AGEX", ["AGE"])
    assert ctx == ctx_before and decision == decision_before
    # the cached object is the one the queries used
    assert dm.get_aggregation_context(conn, "AGEX") is ctx
    assert ctx == ctx_before


# --------------------------------------------------- pure functions on a context

def _ctx(options, actual=None, struct=None):
    opts = [{"label": v, "sdmx_value": v, "parsed": {"age_min": lo, "age_max": hi}}
            for v, (lo, hi) in options]
    return {"dimensions": [{"dim_column_name": "AGE", "dim_type": "age", "options": opts},
                           {"dim_column_name": "SEX", "dim_type": "gender", "options": []}],
            "actual_values": {"AGE": {v: 1 for v in actual}} if actual else {},
            "struct": struct or {}, "measure": "additive", "unit_type": "count"}


def test_coverage_merges_adjacent_integer_ranges_and_keeps_gaps():
    from app.services.scope import dimension_coverage
    bands = [("Total", (0, 999)), ("0-4", (0, 4)), ("5-9", (5, 9)), ("15-19", (15, 19)),
             ("20 si peste", (20, 999))]
    ctx = _ctx(bands)
    cov = dimension_coverage(ctx, "AGE")                  # every non-Total value
    assert cov == {"kind": "age_range", "covered": [[0, 9], [15, None]],
                   "domain": [0, None], "complete": False}
    full = dimension_coverage(_ctx(bands + [("10-14", (10, 14))]), "AGE")      # the gap filled
    assert full["covered"] == [[0, None]] and full["complete"] is True
    # explicit values: matched by value, label or sdmx_value, normalized
    assert dimension_coverage(ctx, "AGE", [" 0-4 ", "5-9"])["covered"] == [[0, 9]]


def test_coverage_without_a_total_uses_the_hull_of_the_options():
    from app.services.scope import dimension_coverage
    ctx = _ctx([("0-4", (0, 4)), ("5-9", (5, 9))], actual=["0-4"])
    assert dimension_coverage(ctx, "AGE") == {
        "kind": "age_range", "covered": [[0, 4]], "domain": [0, 9], "complete": False}
    # a metadata option the data lacks is not a data value: unknown, not covered
    assert dimension_coverage(ctx, "AGE", ["0-4", "5-9"]) is None
    both = _ctx([("0-4", (0, 4)), ("5-9", (5, 9))], actual=["0-4", "5-9"])
    assert dimension_coverage(both, "AGE", ["0-4", "5-9"])["complete"] is True


def test_coverage_is_unknown_not_complete_when_it_cannot_be_established():
    from app.services.scope import dimension_coverage, dataset_restrictions
    total = ("Total", (0, 999))
    assert dimension_coverage(_ctx([total, ("0-4", (0, 4))]), "SEX") is None       # not an age dim
    assert dimension_coverage(_ctx([total, ("0-4", (0, 4))]), "NOPE") is None
    # an included value with no parsed range
    ctx = _ctx([total, ("0-4", (0, 4)), ("necunoscut", (None, None))])
    assert dimension_coverage(ctx, "AGE") is None
    assert dimension_coverage(ctx, "AGE", ["0-4"])["covered"] == [[0, 4]]
    # a value matching no option
    assert dimension_coverage(ctx, "AGE", ["0-4", "99 ani"]) is None
    # a Total without a parsed range: the domain is unknown
    assert dimension_coverage(_ctx([("Total persoane", (None, None)), ("0-4", (0, 4))]), "AGE") is None
    assert dataset_restrictions(ctx) == []                                           # unknown is not a restriction


def test_open_ended_sentinel_and_one_sided_ranges():
    from app.services.scope import dimension_coverage
    ctx = _ctx([("Total", (0, 999)), ("sub 1 an", (None, 0)), ("1-84", (1, 84)),
                ("85 ani si peste", (85, 5000))])
    cov = dimension_coverage(ctx, "AGE")
    assert cov["covered"] == [[0, None]] and cov["domain"] == [0, None] and cov["complete"] is True


def test_dataset_restrictions_marks_the_single_age_child_only(client):
    from app.db import get_conn
    from app.services import dataset_meta as dm
    from app.services.scope import dataset_restrictions
    conn = get_conn()
    assert dataset_restrictions(dm.get_aggregation_context(conn, "AGEX")) == [
        {"column": "AGE", "kind": "age_range", "covered": [[0, 2]], "domain": [0, None]}]
    assert dataset_restrictions(dm.get_aggregation_context(conn, "AGEG")) == []
    assert dataset_restrictions(dm.get_aggregation_context(conn, "POPX")) == []
    assert dataset_restrictions(dm.get_aggregation_context(conn, "ADDX")) == []


def test_result_scope_needs_an_available_decision(client):
    from app.db import get_conn
    from app.services import dataset_meta as dm
    from app.services.scope import result_scope
    ctx = dm.get_aggregation_context(get_conn(), "AGEX")
    assert result_scope(ctx, None, {}, ["TIME_PERIOD"]) is None
    assert result_scope(ctx, {"outcome": "unavailable", "filters": {}, "dimensions": []},
                        {}, ["TIME_PERIOD"]) is None


# ----------------------------------------------------- 7. the insights KPI

def test_insights_headline_carries_the_same_scope(client):
    rest = q(client, "AGEX", ["TIME_PERIOD"])
    ins = client.get("/api/datasets/AGEX/insights").json()
    latest = next(k for k in ins["kpis"] if k["key"] == "latest")
    assert latest["value"] == AGEX_TOTALS["2025"]                # the value is not withheld or changed
    assert latest["provenance"]["scope"] == rest["scope"]
    assert latest["provenance"]["scope"]["domain_complete"] is False
    assert latest["provenance"]["outcome"] == "valid_total"
    sibling = client.get("/api/datasets/AGEG/insights").json()
    k = next(k for k in sibling["kpis"] if k["key"] == "latest")
    assert k["value"] == AGEG_TOTALS["2025"] and k["provenance"]["scope"]["restrictions"] == []
    # the English page reads the same scope
    en = client.get("/api/datasets/AGEX/insights", params={"lang": "en"}).json()
    assert next(k for k in en["kpis"] if k["key"] == "latest")["provenance"]["scope"] == rest["scope"]


# ------------------------------------------- 6. REST and the static engine agree

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_static_engine_reports_the_same_scope(tmp_path):
    from test_static_parity import _parity
    corpus = build_corpus(tmp_path / "data", structure=True)
    add_age_datasets(corpus, verified_sex=False)
    s = _parity(tmp_path / "data", tmp_path / "out", ["AGEX", "AGEG", "POPX", "ADDX"], per_dataset=80)
    assert s["ok"] == s["cases"]
    cases = [json.loads(line) for line in (tmp_path / "out" / "cases.jsonl").read_text().splitlines()]
    scopes = [c["response"]["scope"] for c in cases
              if c["code"] == "AGEX" and "scope" in c.get("response", {})]
    # the recorded REST answers exercise false, requested and unknown scopes
    assert any(s["domain_complete"] is False and s["restrictions"] for s in scopes)
    assert any(r["requested"] for s in scopes for r in s["restrictions"])
    assert any("scope" in c["response"] for c in cases if c["code"] == "AGEG")
    assert not any("scope" in c["response"] for c in cases
                   if "response" in c and c["response"].get("unavailable"))


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_static_site_answers_data_requests_with_the_same_scope(tmp_path):
    from test_static_parity import _api_parity, _catalog_corpus
    corpus = _catalog_corpus(tmp_path)
    add_age_datasets(corpus)
    s = _api_parity(tmp_path / "data", tmp_path / "out", ["AGEX", "AGEG", "ADDX"], n=40)
    assert s["ok"] == s["cases"] - s.get("browser_budget_refusals", 0)


# --------------------------------------------- read-only probe of the real copy

def _generation_id():
    from app.services import generation
    return generation.summary()["id"] or ""


@pytest.mark.corpus
def test_real_single_age_child_is_disclosed_as_zero_to_84():
    if not _generation_id().startswith("9b3e065d"):
        pytest.skip("pinned to generation 9b3e065d (copied 2026-10-12 corpus)")
    from app.db import get_conn
    from app.services.data_query import run_query
    conn = get_conn()
    body = run_query(conn, "POP107D_varste_judet", group_by=["TIME_PERIOD"])
    assert not body.get("unavailable")
    assert body["aggregation"]["outcome"] == "valid_total"
    assert body["scope"]["domain_complete"] is False
    assert body["scope"]["restrictions"] == [
        {"column": "AGE", "kind": "age_range", "covered": [[0, 84]], "domain": [0, None],
         "requested": False}]
    # the grouped-age sibling adds the open-ended band: no age restriction
    sib = run_query(conn, "POP107D_grupe_judet", group_by=["TIME_PERIOD"])
    assert not sib.get("unavailable") and sib["scope"]["restrictions"] == []
