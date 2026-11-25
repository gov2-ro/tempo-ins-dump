"""CP: profile pages for the large cities. Synthetic fixtures only (no corpus, no writes to data/)."""
import json
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, '.')
from app.routers import places as places_router
from app.services import grain_guard
from app.services import place_service as ps

CONFIG_PATH = Path(__file__).resolve().parent.parent / "app" / "static" / "data" / "place_kpi_config.json"

ITEMS = [
    {"type": "locality", "slug": "municipiul-bigcity", "siruta": 111, "name": "Bigcity",
     "county": "Alpha", "county_slug": "alpha"},
    {"type": "county", "slug": "municipiul-bucuresti", "siruta": 999, "name": "Municipiul Bucuresti"},
]
FEATURED = {"threshold": 200000, "population_year": 2021, "items": ITEMS}


def _write(path: Path, cols, rows):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (" + ", ".join(
        f'"{c}" {"DOUBLE" if c == "OBS_VALUE" else "VARCHAR"}' for c in cols) + ")")
    con.executemany("INSERT INTO t VALUES (" + ",".join("?" * len(cols)) + ")", rows)
    con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    con.close()


@pytest.fixture
def meta_conn():
    """Tiny stand-in for metadata.duckdb: two counties, three localities."""
    con = duckdb.connect()
    con.execute("CREATE TABLE dimension_options_parsed (dim_type VARCHAR, geo_level VARCHAR, "
                "geo_name_clean VARCHAR, siruta_code INTEGER)")
    con.executemany("INSERT INTO dimension_options_parsed VALUES (?,?,?,?)", [
        ("geo", "county", "Alpha", None), ("geo", "county", "Municipiul Bucuresti", None),
        ("geo", "locality", "MUNICIPIUL BIGCITY", 111), ("geo", "locality", "ORAS SMALLTOWN", 222),
        ("geo", "locality", "COMUNA VILLAGE", 333),
    ])
    yield con
    con.close()


@pytest.fixture
def env(tmp_path, monkeypatch, meta_conn):
    grain_guard._cache.clear()           # keyed by file stem: one test's verdict must not reach the next
    # no generation manifest: the slice is checked at query time, not certified by the live corpus's audit
    monkeypatch.setattr(grain_guard.generation, "current", lambda: grain_guard.generation._empty("missing"))
    monkeypatch.setattr(ps, "PARQUET_DIR", tmp_path)
    monkeypatch.setattr(places_router, "get_conn", lambda: meta_conn)

    def install(*specs):
        monkeypatch.setattr(ps, "_kpi_config", {"locality": list(specs), "county": [],
                                                "featured_localities": FEATURED})
    install()
    return tmp_path, install


def _spec(**kw):
    base = {"key": "domicile_population", "label": "Pop", "label_en": "Pop", "unit": "pers.",
            "unit_kind": "count", "source_code": "TST001", "measure": "additive",
            "parquet": "pop_localitate.parquet", "area_column": "REF_AREA_2",
            "partitions": ["AGE", "SEX"]}
    base.update(kw)
    return base


COLS = ["AGE", "SEX", "REF_AREA", "REF_AREA_2", "TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"]


def _rows(values: dict, areas=(("Alpha", "111 MUNICIPIUL BIGCITY"), ("Alpha", "222 ORAS SMALLTOWN"))):
    rows = []
    for year, tot in values.items():
        for county, loc in areas:
            for age in ("0-4", "5+"):
                for sex in ("F", "M"):
                    rows.append((age, sex, county, loc, str(year), "n",
                                 tot / 4 if loc.startswith("111") else 1.0))
    return rows


# ---- /api/places -----------------------------------------------------------------

def test_places_list_adds_featured_localities_and_marks_bucharest_once(env):
    out = places_router.list_places()["places"]
    cities = [p for p in out if p["type"] == "locality"]
    assert [(p["slug"], p["name"], p["county"]) for p in cities] == \
        [("municipiul-bigcity", "Bigcity", "Alpha")]
    assert all(p["featured"] for p in cities)
    bucharest = [p for p in out if p["slug"] == "municipiul-bucuresti"]
    assert len(bucharest) == 1 and bucharest[0]["type"] == "county" and bucharest[0]["featured"]
    assert not any(p["slug"] in ("oras-smalltown", "comuna-village") for p in out)   # not every locality
    assert not [p for p in out if p["type"] == "county" and p["slug"] == "alpha" and p.get("featured")]


# ---- resolution ------------------------------------------------------------------

def test_a_listed_city_resolves_with_siruta_and_county_parent(env, meta_conn):
    p = ps.resolve_place("locality", "municipiul-bigcity", conn=meta_conn)
    assert (p["name"], p["siruta"]) == ("Bigcity", "111")
    assert (p["parent_type"], p["parent_slug"], p["parent_name"]) == ("county", "alpha", "Alpha")


def test_a_county_still_has_a_region_parent_type(env, meta_conn):
    assert ps.resolve_place("county", "alpha", conn=meta_conn)["parent_type"] == "region"


# ---- KPI card --------------------------------------------------------------------

def test_locality_kpi_sums_the_partitions_for_that_city_only(env, meta_conn):
    tmp, install = env
    spec = _spec()
    _write(tmp / spec["parquet"], COLS, _rows({2024: 400, 2025: 440}))
    install(spec)
    rep = ps.get_place_kpi_report("locality", "municipiul-bigcity", conn=meta_conn)
    assert rep["omitted"] == []
    k = rep["kpis"][0]
    assert (k["period"], k["value"]) == ("2025", 440.0)          # the other town's rows are not added
    assert k["method"]["code"] == "sum_partition"
    assert k["change"]["status"] == "ok" and k["change"]["value"] == 10.0


def test_a_city_year_with_a_missing_group_is_absent_not_zero(env, meta_conn):
    tmp, install = env
    spec = _spec()
    rows = [r for r in _rows({2024: 400, 2025: 440})
            if not (r[4] == "2025" and r[3].startswith("111") and r[1] == "F" and r[0] == "5+")]
    _write(tmp / spec["parquet"], COLS, rows)
    install(spec)
    k = ps.get_place_kpi_report("locality", "municipiul-bigcity", conn=meta_conn)["kpis"][0]
    assert (k["period"], k["value"]) == ("2024", 400.0)


def test_a_repeated_key_refuses_the_card(env, meta_conn):
    tmp, install = env
    spec = _spec()
    rows = _rows({2025: 400}) + [r for r in _rows({2025: 800}) if r[3].startswith("111")]   # same keys, other value
    _write(tmp / spec["parquet"], COLS, rows)
    install(spec)
    rep = ps.get_place_kpi_report("locality", "municipiul-bigcity", conn=meta_conn)
    assert rep["kpis"] == [] and rep["omitted"][0]["reason"] in ("conflicting_grain", "duplicate_keys")


def test_a_suppressed_locality_kpi_is_listed_as_omitted(env, meta_conn):
    tmp, install = env
    install(_spec(key="tourist_arrivals", suppress="type_coverage_varies", suppress_note="n"))
    rep = ps.get_place_kpi_report("locality", "municipiul-bigcity", conn=meta_conn)
    assert rep["kpis"] == [] and rep["omitted"][0]["reason"] == "type_coverage_varies"


def test_an_unlisted_locality_gets_no_kpis(env, meta_conn):
    tmp, install = env
    spec = _spec()
    _write(tmp / spec["parquet"], COLS, _rows({2025: 400}))
    install(spec)
    assert ps.get_place_kpi_report("locality", "oras-smalltown", conn=meta_conn) == {"kpis": [], "omitted": []}


# ---- peers and baselines ---------------------------------------------------------

def test_a_city_has_the_other_listed_cities_as_peers_and_no_baselines(env, meta_conn):
    tmp, install = env
    spec = _spec()
    install(spec)
    peers = ps.get_place_peers("locality", "oras-smalltown", conn=meta_conn)
    assert peers == {"same_region": [], "similar_size": []}
    peers = ps.get_place_peers("locality", "municipiul-bigcity", conn=meta_conn)
    assert peers["same_region"] == [] and peers["similar_size"] == []    # Bucharest is a county: not a peer
    b = ps.get_kpi_baselines("locality", "municipiul-bigcity", "domicile_population")
    assert b["national"] == [] and b["region"] == []
    assert b["national_meta"]["available"] is False


# ---- the shipped config ----------------------------------------------------------

def test_the_shipped_config_is_consistent():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    feat = cfg["featured_localities"]
    assert feat["threshold"] == 200000 and feat["population_year"]
    slugs = [i["slug"] for i in feat["items"]]
    assert len(slugs) == len(set(slugs))
    cities = [i for i in feat["items"] if i.get("type", "locality") == "locality"]
    assert len({i["siruta"] for i in cities}) == len(cities)
    assert all(i["slug"].startswith("municipiul-") and i["county_slug"] and i["county"] for i in cities)
    assert any(i["type"] == "county" and i["slug"] == "municipiul-bucuresti" for i in feat["items"])
    keys = [s["key"] for s in cfg["locality"]]
    assert len(keys) == len(set(keys)) and keys
    for s in cfg["locality"]:
        assert s["area_column"] == "REF_AREA_2" and s["parquet"].endswith("_localitate.parquet")
        if not s.get("suppress"):
            assert s["measure"] == "additive" and s["source_code"]
