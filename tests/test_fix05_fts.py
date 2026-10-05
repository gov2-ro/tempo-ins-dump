"""FIX-05: FTS sidecar search on a tiny synthetic catalog (no corpus needed)."""
import threading

import duckdb
import pytest

from app.services import dataset_search as ds

DOCS = [
    # code, name_ro, name_en, definitie, tags_ro, tags_en
    ("AAA001", "Populatia rezidenta", "Resident population", "Numarul persoanelor", "demografie locuitori", "demography inhabitants"),
    ("AAA002", "Populatia la 1 iulie", "Population on 1 July", "Estimare", "demografie", "demography"),
    ("BBB001", "Indicatori economici", "Economic indicators", "Definitia somajului BIM", "somaj forta de munca", "unemployment labour force"),
    ("CCC001", "Productia agricola", "Agricultural output", "Cereale", "agricultura cereale", "agriculture cereals"),
    ("CCC002", "Suprafata cultivata", "Cultivated area", "Cereale", "agricultura cereale", "agriculture cereals"),
]


@pytest.fixture()
def catalog(tmp_path, monkeypatch):
    try:
        probe = duckdb.connect(":memory:")
        probe.execute("LOAD fts")
        probe.close()
    except Exception as e:  # extension not installed and no network
        pytest.skip(f"duckdb fts extension unavailable: {e}")

    sdb = tmp_path / "search.duckdb"
    c = duckdb.connect(str(sdb))
    c.execute("LOAD fts")
    c.execute("CREATE TABLE search_docs(matrix_code VARCHAR PRIMARY KEY, name_ro VARCHAR, "
              "name_en VARCHAR, definitie VARCHAR, tags_ro VARCHAR, tags_en VARCHAR, search_text VARCHAR)")
    for code, nr, ne, d, tr, te in DOCS:
        c.execute("INSERT INTO search_docs VALUES (?,?,?,?,?,?,?)",
                  [code, nr, ne, d, tr, te, " ".join([nr, ne, d, tr, te, code])])
    c.execute("PRAGMA create_fts_index('search_docs','matrix_code','search_text','name_ro','name_en',"
              "stemmer='none',stopwords='none',ignore='(\\.|[^a-zA-Z0-9\\s])+',lower=1,overwrite=1)")
    c.close()

    m = duckdb.connect(":memory:")
    m.execute("""CREATE TABLE matrices(matrix_code VARCHAR, matrix_name VARCHAR, matrix_name_en VARCHAR,
        context_code VARCHAR, ancestor_codes VARCHAR[], ultima_actualizare DATE, row_count BIGINT,
        mat_max_dim INT, is_canonical BOOLEAN, is_split BOOLEAN, parent_matrix_code VARCHAR)""")
    m.execute("""CREATE TABLE matrix_profiles(matrix_code VARCHAR, archetype VARCHAR, has_time BOOLEAN,
        has_geo BOOLEAN, time_year_min INT, time_year_max INT, primary_unit_type VARCHAR,
        time_granularity VARCHAR, has_gender BOOLEAN, has_age BOOLEAN, has_residence BOOLEAN)""")
    m.execute("CREATE TABLE dataset_splits(parent_matrix_code VARCHAR, sub_matrix_code VARCHAR)")
    m.execute("CREATE TABLE dimensions(matrix_code VARCHAR, dim_label VARCHAR, option_count INT)")
    for code, nr, ne, *_ in DOCS:
        # identical dates => ties must resolve by matrix_code
        m.execute("INSERT INTO matrices VALUES (?,?,?,'1',[],DATE '2024-01-01',10,2,TRUE,FALSE,NULL)",
                  [code, nr, ne])
    monkeypatch.setattr(ds, "SEARCH_DB_PATH", sdb)
    ds._reset_for_tests()
    yield m
    ds._reset_for_tests()


def codes(res):
    return [d["matrix_code"] for d in res["datasets"]]


def test_fts_matches_tags_and_definitions_not_just_names(catalog):
    # "somaj" only appears in tags/definitie of BBB001, never in its name
    r = ds.search_datasets("somaj", conn=catalog)
    assert codes(r) == ["BBB001"] and r["search_mode"] == "fts"
    # English multiword on tags
    r = ds.search_datasets("unemployment labour", conn=catalog)
    assert codes(r) == ["BBB001"]
    # Romanian multiword: both agri docs, stable order by code
    r = ds.search_datasets("agricultura cereale", conn=catalog)
    assert codes(r) == ["CCC001", "CCC002"]


def test_total_is_full_match_set_not_cutoff(catalog):
    r = ds.search_datasets("cereale demografie", conn=catalog, limit=1)
    assert r["total"] == 4 and len(r["datasets"]) == 1
    assert r["total_basis"] == "all_matches"


def test_tie_order_is_stable(catalog):
    first = codes(ds.search_datasets("demography", conn=catalog))
    for _ in range(5):
        assert codes(ds.search_datasets("demography", conn=catalog)) == first
    assert first == sorted(first)


def test_status_fts_and_fallback_observable(catalog, monkeypatch, caplog):
    assert ds.search_status()["mode"] == "fts"
    monkeypatch.setattr(ds, "SEARCH_DB_PATH", ds.SEARCH_DB_PATH.with_name("nope.duckdb"))
    monkeypatch.setattr(ds, "DEBUG", False)
    ds._reset_for_tests()
    with caplog.at_level("ERROR"):
        r = ds.search_datasets("populatia", conn=catalog)
    assert r["search_mode"] == "name_like" and "AAA001" in codes(r)
    st = ds.search_status()
    assert st["mode"] == "fallback" and st["production"] is True
    assert any("IN PRODUCTION" in rec.message for rec in caplog.records)


def test_concurrent_searches_isolated(catalog):
    expect = {"somaj": ["BBB001"], "agricultura": ["CCC001", "CCC002"],
              "demography": ["AAA001", "AAA002"]}
    errors, lock = [], threading.Lock()

    def worker(q):
        cur = catalog.cursor()  # cursor per thread, as get_conn() does
        for _ in range(30):
            got = codes(ds.search_datasets(q, conn=cur))
            if got != expect[q]:
                with lock:
                    errors.append((q, got))

    ts = [threading.Thread(target=worker, args=(q,)) for q in list(expect) * 4]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, errors[:3]


def test_health_endpoint_reports_fts_mode(catalog, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["search"]["mode"] == "fts"
    monkeypatch.setattr(ds, "SEARCH_DB_PATH", ds.SEARCH_DB_PATH.with_name("nope.duckdb"))
    ds._reset_for_tests()
    body = client.get("/api/health").json()
    assert body["status"] == "degraded" and body["search"]["mode"] == "fallback"
    assert "path" not in body["search"]
