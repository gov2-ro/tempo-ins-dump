"""Synthetic corpus for FIX-02 phase 2 (grouped API / agent / consumers agreeing).

Three tiny datasets with known answers; metadata tables are complete enough for
get_dataset_meta (so the shared aggregation context is the real one):

  POPX   POP107A-like. AGE has 5 single years AND one 0-4 band (overlapping
         grains), SEX is a flat partition. Per year the true population is 100
         (singles) — a naive SUM over every AGE option gives 200.
  ADDX   additive counts: CATEGORY has a Total row (120 = 50 + 70 in 2023).
  RATEX  percentage rates by region, no total: an unweighted mean is not an
         official rate.
"""
from __future__ import annotations

import duckdb

POPX_ROWS = []
for year, k in (("2024", 1.0), ("2025", 1.1)):
    for sex in ("Masculin", "Feminin"):
        for a in range(5):
            POPX_ROWS.append((f"{a} ani", sex, year, 10.0 * k))
        POPX_ROWS.append(("0-4 ani", sex, year, 50.0 * k))   # band = sum of singles
POPX_TRUE_2025 = 100.0 * 1.1
POPX_NAIVE_2025 = 200.0 * 1.1

ADDX_ROWS = [("Total", "2022", 100.0), ("A", "2022", 40.0), ("B", "2022", 60.0),
             ("Total", "2023", 120.0), ("A", "2023", 50.0), ("B", "2023", 70.0)]
RATEX_ROWS = [("Nord", "2023", 10.0), ("Sud", "2023", 20.0),
              ("Nord", "2024", 12.0), ("Sud", "2024", 22.0)]


def _write(path, ddl, rows):
    c = duckdb.connect()
    c.execute(f"CREATE TABLE t ({ddl})")
    n = len(rows[0])
    c.executemany(f"INSERT INTO t VALUES ({','.join('?' * n)})", rows)
    c.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    c.close()


def build_corpus(tmp_path, structure: bool = False):
    corpus = tmp_path / "corpus"
    (corpus / "parquet").mkdir(parents=True)
    _write(corpus / "parquet" / "POPX.parquet",
           "AGE VARCHAR, SEX VARCHAR, TIME_PERIOD VARCHAR, OBS_VALUE DOUBLE", POPX_ROWS)
    _write(corpus / "parquet" / "ADDX.parquet",
           "CATEGORY VARCHAR, TIME_PERIOD VARCHAR, OBS_VALUE DOUBLE", ADDX_ROWS)
    _write(corpus / "parquet" / "RATEX.parquet",
           "REF_AREA VARCHAR, TIME_PERIOD VARCHAR, OBS_VALUE DOUBLE", RATEX_ROWS)

    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("""CREATE TABLE matrices (matrix_code VARCHAR, matrix_name VARCHAR,
                  matrix_name_en VARCHAR, row_count BIGINT, parent_matrix_code VARCHAR,
                  context_code VARCHAR, ancestor_codes VARCHAR[], definitie VARCHAR,
                  metodologie VARCHAR, ultima_actualizare VARCHAR, observatii VARCHAR,
                  mat_max_dim INTEGER, is_split BOOLEAN)""")
    db.execute("""CREATE TABLE dimensions (dimension_id BIGINT, matrix_code VARCHAR,
                  dim_code INTEGER, dim_label VARCHAR, dim_column_name VARCHAR,
                  option_count INTEGER)""")
    db.execute("""CREATE TABLE dimension_options (dimension_id BIGINT, nom_item_id INTEGER,
                  option_label VARCHAR, option_offset INTEGER, parent_id INTEGER)""")
    db.execute("""CREATE TABLE dimension_options_parsed (nom_item_id INTEGER,
                  dim_type VARCHAR, year INTEGER, quarter INTEGER, month INTEGER,
                  geo_level VARCHAR, geo_name_clean VARCHAR, gender VARCHAR,
                  age_min INTEGER, age_max INTEGER, unit_type VARCHAR,
                  unit_scale VARCHAR, parse_confidence DOUBLE)""")
    db.execute("""CREATE TABLE sdmx_codes (nom_item_id INTEGER, sdmx_value VARCHAR,
                  display_label_en VARCHAR)""")
    db.execute("""CREATE TABLE sdmx_column_map (matrix_code VARCHAR,
                  sdmx_column_name VARCHAR, old_column_name VARCHAR)""")
    db.execute("""CREATE TABLE matrix_profiles (matrix_code VARCHAR,
                  primary_unit_type VARCHAR, archetype VARCHAR, time_year_min INTEGER,
                  time_year_max INTEGER, unit_types VARCHAR)""")
    db.execute("""CREATE TABLE dataset_splits (parent_matrix_code VARCHAR,
                  sub_matrix_code VARCHAR, split_value VARCHAR, row_count BIGINT,
                  split_dimensions VARCHAR)""")
    for t in ("dataset_coverage", "dataset_value_profiles", "dataset_trends"):
        db.execute(f"CREATE TABLE {t} (matrix_code VARCHAR)")
    db.execute("""CREATE TABLE contexts (context_code VARCHAR, context_name VARCHAR,
                  context_name_en VARCHAR, parent_code VARCHAR, level INTEGER)""")
    if structure:
        db.execute("""CREATE TABLE dimension_structure (matrix_code VARCHAR,
                      dim_column VARCHAR, levels VARCHAR, default_level VARCHAR,
                      n_levels INTEGER, aggregate_value VARCHAR,
                      aggregate_verified BOOLEAN, additive BOOLEAN, nests_in VARCHAR,
                      discrimination DOUBLE, dominance DOUBLE, confidence VARCHAR,
                      source VARCHAR)""")

    spec = {
        "POPX": ("Populatia rezidenta", "count", len(POPX_ROWS), [
            ("AGE", "Grupe de varsta", "age",
             [(f"{a} ani", dict(age_min=a, age_max=a)) for a in range(5)]
             + [("0-4 ani", dict(age_min=0, age_max=4))]),
            ("SEX", "Sexe", "gender",
             [("Masculin", dict(gender="M")), ("Feminin", dict(gender="F"))]),
            ("TIME_PERIOD", "Ani", "time",
             [("2024", dict(year=2024)), ("2025", dict(year=2025))])]),
        "ADDX": ("Productia de energie", "count", len(ADDX_ROWS), [
            ("CATEGORY", "Categorie", None, [("Total", {}), ("A", {}), ("B", {})]),
            ("TIME_PERIOD", "Ani", "time",
             [("2022", dict(year=2022)), ("2023", dict(year=2023))])]),
        "RATEX": ("Rata somajului", "percentage", len(RATEX_ROWS), [
            ("REF_AREA", "Regiuni", "geo",
             [("Nord", dict(geo_level="region")), ("Sud", dict(geo_level="region"))]),
            ("TIME_PERIOD", "Ani", "time",
             [("2023", dict(year=2023)), ("2024", dict(year=2024))])]),
    }
    did = nid = 0
    for code, (name, unit, nrows, dims) in spec.items():
        db.execute("INSERT INTO matrices (matrix_code, matrix_name, matrix_name_en, "
                   "row_count, definitie) VALUES (?, ?, ?, ?, ?)",
                   [code, name, name, nrows, name])
        db.execute("INSERT INTO matrix_profiles VALUES (?, ?, 'x', 2022, 2025, '[]')",
                   [code, unit])
        for i, (col, label, dtype, opts) in enumerate(dims, 1):
            did += 1
            db.execute("INSERT INTO dimensions VALUES (?, ?, ?, ?, ?, ?)",
                       [did, code, i, label, col, len(opts)])
            for off, (olabel, parsed) in enumerate(opts):
                nid += 1
                db.execute("INSERT INTO dimension_options VALUES (?, ?, ?, ?, NULL)",
                           [did, nid, olabel, off])
                p = {"year": None, "quarter": None, "month": None, "geo_level": None,
                     "geo_name_clean": None, "gender": None, "age_min": None,
                     "age_max": None, **parsed}
                db.execute("INSERT INTO dimension_options_parsed VALUES "
                           "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0.9)",
                           [nid, dtype, p["year"], p["quarter"], p["month"],
                            p["geo_level"], p["geo_name_clean"], p["gender"],
                            p["age_min"], p["age_max"]])
                db.execute("INSERT INTO sdmx_codes VALUES (?, ?, ?)", [nid, olabel, olabel])
    if structure:
        import json
        levels = [
            {"level_id": "age_y1", "name": "single years", "verified": True,
             "members": [f"{a} ani" for a in range(5)]},
            {"level_id": "age_w5", "name": "5-year bands", "verified": True,
             "members": ["0-4 ani"]}]
        db.execute("INSERT INTO dimension_structure VALUES ('POPX', 'AGE', ?, 'age_y1', "
                   "2, NULL, FALSE, NULL, NULL, 1.0, 1.0, 'verified', 'test')",
                   [json.dumps(levels)])
    db.close()
    return corpus


def make_client(tmp_path, monkeypatch, structure: bool = False):
    """TestClient on the real app with every data path pointed at the corpus."""
    from fastapi.testclient import TestClient
    import app.config as config
    import app.db as appdb
    import app.routers.dataset_data as dd
    import app.services.query_builder as qb
    import app.services.dataset_meta as dm
    import app.services.insights as ins
    import app.services.dimension_structure as dstruct

    corpus = build_corpus(tmp_path, structure)
    monkeypatch.setattr(config, "CORPUS_DIR", corpus)
    monkeypatch.setattr(config, "DB_PATH", corpus / "metadata.duckdb")
    monkeypatch.setattr(appdb, "DB_PATH", corpus / "metadata.duckdb")
    monkeypatch.setattr(appdb, "_conn", None)
    for mod in (dd, qb, dm):
        monkeypatch.setattr(mod, "PARQUET_DIR", corpus / "parquet")
    dm.clear_context_cache()
    dstruct._cache.clear()
    dstruct._TABLE_OK = None
    ins._cache.clear()
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)
