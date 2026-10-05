"""Synthetic corpus for FIX-01 API tests: tiny metadata DuckDB + parquet files.

No real data, no home paths, no network. ``build_corpus(tmp_path)`` writes the
files; ``make_client`` points the app's config/db modules at them.
"""
from __future__ import annotations

import duckdb

# TIME_PERIOD values deliberately mix annual, quarterly and monthly formats in
# one dataset (MIXED1) to exercise the mixed-granularity policy.
ANNUAL_ROWS = [
    ("Total", "Cluj", "2019", 10.0),
    ("Total", "Cluj", "2020", 20.0),
    ("Total", "Iasi", "2020", 30.0),
    ("O'Brien & <Co>", "Cluj", "2021", 40.0),
]
MIXED_ROWS = [
    ("Total", "Cluj", "2019", 1.0),
    ("Total", "Cluj", "2020", 2.0),
    ("Total", "Cluj", "2020-Q1", 3.0),
    ("Total", "Cluj", "2020-Q3", 4.0),
    ("Total", "Cluj", "2020-03", 5.0),
    ("Total", "Cluj", "2020-11", 6.0),
    ("Total", "Cluj", "2021-02", 7.0),
    ("Total", "Cluj", "Anul 2020", 8.0),
]


def _write_parquet(path, rows):
    c = duckdb.connect()
    c.execute("CREATE TABLE t (CATEGORY VARCHAR, REF_AREA VARCHAR, "
              "TIME_PERIOD VARCHAR, OBS_VALUE DOUBLE)")
    c.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", rows)
    c.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    c.close()


def build_corpus(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "parquet").mkdir(parents=True)
    _write_parquet(corpus / "parquet" / "ANN1.parquet", ANNUAL_ROWS)
    _write_parquet(corpus / "parquet" / "MIXED1.parquet", MIXED_ROWS)

    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("""CREATE TABLE matrices (matrix_code VARCHAR, matrix_name VARCHAR,
                  matrix_name_en VARCHAR, row_count BIGINT, parent_matrix_code VARCHAR)""")
    db.execute("""CREATE TABLE dimensions (dimension_id BIGINT, matrix_code VARCHAR,
                  dim_code INTEGER, dim_label VARCHAR, dim_column_name VARCHAR,
                  option_count INTEGER)""")
    db.execute("""CREATE TABLE dimension_options (dimension_id BIGINT,
                  nom_item_id INTEGER, option_label VARCHAR)""")
    db.execute("""CREATE TABLE matrix_profiles (matrix_code VARCHAR,
                  primary_unit_type VARCHAR, time_year_min INTEGER,
                  time_year_max INTEGER)""")
    db.execute("""CREATE TABLE sdmx_column_map (matrix_code VARCHAR,
                  sdmx_column_name VARCHAR, old_column_name VARCHAR)""")
    db.execute("""CREATE TABLE dataset_splits (parent_matrix_code VARCHAR,
                  sub_matrix_code VARCHAR, suffix_label VARCHAR, display_name VARCHAR)""")
    db.execute("""CREATE TABLE dataset_relationships (matrix_a VARCHAR, matrix_b VARCHAR,
                  similarity_score DOUBLE, relationship_type VARCHAR,
                  shared_dim_types VARCHAR)""")
    did = 0
    for code, nrows in (("ANN1", len(ANNUAL_ROWS)), ("MIXED1", len(MIXED_ROWS))):
        db.execute("INSERT INTO matrices VALUES (?, ?, ?, ?, NULL)",
                   [code, f"Test {code}", f"Test {code} en", nrows])
        db.execute("INSERT INTO matrix_profiles VALUES (?, 'count', 2019, 2021)", [code])
        for i, (label, col) in enumerate(
                [("Category", "CATEGORY"), ("Area", "REF_AREA"), ("Time", "TIME_PERIOD")], 1):
            did += 1
            db.execute("INSERT INTO dimensions VALUES (?, ?, ?, ?, ?, 3)",
                       [did, code, i, label, col])
            if col == "CATEGORY":
                for n, opt in enumerate(["Total", "O'Brien & <Co>"], 1):
                    db.execute("INSERT INTO dimension_options VALUES (?, ?, ?)", [did, n, opt])
    db.close()
    return corpus


def make_client(tmp_path, monkeypatch):
    """TestClient on the app with all data paths pointed at a synthetic corpus."""
    from fastapi.testclient import TestClient
    import app.config as config
    import app.db as appdb
    import app.routers.sdmx as sdmx_router
    import app.routers.dataset_data as dd
    import app.services.query_builder as qb

    corpus = build_corpus(tmp_path)
    monkeypatch.setattr(config, "CORPUS_DIR", corpus)
    monkeypatch.setattr(config, "DB_PATH", corpus / "metadata.duckdb")
    monkeypatch.setattr(appdb, "DB_PATH", corpus / "metadata.duckdb")
    monkeypatch.setattr(appdb, "_conn", None)
    for mod in (sdmx_router, dd, qb):
        monkeypatch.setattr(mod, "PARQUET_DIR", corpus / "parquet")
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)
