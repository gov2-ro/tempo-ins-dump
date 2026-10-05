"""Synthetic corpus for the FIX-03c tests (manifest, release-check, repair planner).

Layout written under <root>/corpus (+ <root>/2-metas/ro, 4-datasets/ro, logs):
  GOOD1            served canonical, clean
  PAR1             noncanonical split parent (locality REF_AREA_2 present)
  PAR1_judet       registered split, REF_AREA_2 dropped -> keys collide (count unit, additive)
  PAR2_judet       registered split, locality dropped, percentage unit (non-additive)
  SHIFT1           served; TIME_PERIOD holds hour bands, TIME_PERIOD_2 holds years
  LEFT1            leftover (no registration)
  EMPTY1           unregistered zero-row parquet
  NOFILE1          canonical matrix, CSV header-only      -> empty_at_source
  NOFILE2          canonical matrix, meta only            -> csv_never_fetched
"""
import json
from pathlib import Path

import duckdb


def write_parquet(path: Path, cols, rows):
    c = duckdb.connect()
    defs = ", ".join(f'"{n}" {t}' for n, t in cols)
    c.execute(f"CREATE TABLE t ({defs})")
    for r in rows:
        c.execute(f"INSERT INTO t VALUES ({', '.join('?' for _ in cols)})", list(r))
    c.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    c.close()


V, D = "VARCHAR", "DOUBLE"


def fts_available() -> bool:
    c = duckdb.connect(":memory:")
    try:
        c.execute("LOAD fts")
        return True
    except Exception:
        return False


def make_corpus(root: Path, with_search=True, nofile=True) -> Path:
    corpus = root / "corpus"
    pq, vp = corpus / "parquet", corpus / "view-profiles"
    pq.mkdir(parents=True)
    vp.mkdir()
    std = [("REF_AREA", V), ("TIME_PERIOD", V), ("OBS_VALUE", D)]
    loc = [("REF_AREA", V), ("REF_AREA_2", V), ("TIME_PERIOD", V), ("OBS_VALUE", D)]
    write_parquet(pq / "GOOD1.parquet", std, [("RO", "2020", 1.0), ("RO", "2021", 2.0)])
    write_parquet(pq / "PAR1.parquet", loc, [("AB", "loc1", "2020", 5.0), ("AB", "loc2", "2020", 7.0)])
    write_parquet(pq / "PAR1_judet.parquet", std, [("AB", "2020", 5.0), ("AB", "2020", 7.0)])
    write_parquet(pq / "PAR2.parquet", loc, [("AB", "loc1", "2020", 5.0), ("AB", "loc2", "2020", 7.0)])
    write_parquet(pq / "PAR2_judet.parquet", std, [("AB", "2020", 5.0), ("AB", "2020", 7.0)])
    write_parquet(pq / "SHIFT1.parquet",
                  [("TIME_PERIOD", V), ("TIME_PERIOD_2", V), ("OBS_VALUE", D)],
                  [("40 ore", "2020", 1.0), ("11 - 20 ore", "2020", 2.0), ("Nu poate fi indicata", "2021", 3.0)])
    write_parquet(pq / "LEFT1.parquet", std, [("RO", "2020", 1.0)])
    write_parquet(pq / "EMPTY1.parquet", std, [])
    for code in ("GOOD1", "PAR1_judet", "PAR2_judet", "SHIFT1"):
        (vp / f"{code}.json").write_text("{}")

    m = duckdb.connect(str(corpus / "metadata.duckdb"))
    m.execute("""CREATE TABLE matrices (matrix_code VARCHAR, matrix_name VARCHAR, is_canonical BOOLEAN,
                 is_split BOOLEAN, parent_matrix_code VARCHAR, parquet_path VARCHAR, row_count BIGINT,
                 ultima_actualizare DATE)""")
    rows = [("GOOD1", "Populatia", True, False, None, None, 2, "2026-01-02"),
            ("PAR1", "Suprafata pe judete si localitati", False, False, None, None, 2, "2025-05-01"),
            ("PAR1_judet", "Suprafata [judet]", True, True, "PAR1", None, 2, None),
            ("PAR2", "Rata somajului pe judete si localitati", False, False, None, None, 2, None),
            ("PAR2_judet", "Rata somajului [judet]", True, True, "PAR2", None, 2, None),
            ("SHIFT1", "Ore lucrate", True, False, None, None, 3, None),
            ("NOFILE1", "Export gol", True, False, None, None, 0, "2025-05-28"),
            ("NOFILE2", "Matrice noua", True, False, None, None, None, "2026-04-20")]
    for r in rows:
        if not nofile and r[0].startswith("NOFILE"):
            continue   # a release-clean corpus has no canonical matrix without a parquet
        m.execute("INSERT INTO matrices VALUES (?,?,?,?,?,?,?,?)", list(r))
    m.execute("""CREATE TABLE dataset_splits (parent_matrix_code VARCHAR, sub_matrix_code VARCHAR,
                 split_pattern VARCHAR, split_dimension VARCHAR, split_value VARCHAR, parquet_path VARCHAR,
                 row_count BIGINT)""")
    m.execute("INSERT INTO dataset_splits VALUES ('PAR1','PAR1_judet','hierarchy','REF_AREA_2','judet',NULL,2),"
              "('PAR2','PAR2_judet','hierarchy','REF_AREA_2','judet',NULL,2)")
    m.execute("CREATE TABLE dimensions (dimension_id INTEGER, matrix_code VARCHAR, dim_code INTEGER, "
              "dim_label VARCHAR, dim_column_name VARCHAR, option_count INTEGER)")
    m.execute("INSERT INTO dimensions VALUES (1,'PAR1',1,'Judete','REF_AREA',1),(2,'PAR1',2,'Localitati','REF_AREA_2',2),"
              "(3,'PAR2',1,'Judete','REF_AREA',1),(4,'PAR2',2,'Localitati','REF_AREA_2',2)")
    m.execute("CREATE TABLE dimension_options (option_id INTEGER, dimension_id INTEGER, nom_item_id INTEGER, "
              "option_label VARCHAR, option_offset INTEGER, parent_id INTEGER)")
    m.execute("CREATE TABLE matrix_profiles (matrix_code VARCHAR, primary_unit_type VARCHAR)")
    m.execute("INSERT INTO matrix_profiles VALUES ('PAR1','count'),('PAR2','percentage')")
    m.execute("CREATE TABLE dimension_structure (matrix_code VARCHAR, dim_column VARCHAR, levels VARCHAR)")
    m.close()

    if with_search:
        s = duckdb.connect(str(corpus / "search.duckdb"))
        s.execute("LOAD fts")
        s.execute("CREATE TABLE search_docs(matrix_code VARCHAR PRIMARY KEY, search_text VARCHAR)")
        for c in ("GOOD1", "PAR1_judet", "PAR2_judet", "SHIFT1", *(("NOFILE1", "NOFILE2") if nofile else ())):
            s.execute("INSERT INTO search_docs VALUES (?, ?)", [c, f"populatia {c}"])
        s.execute("PRAGMA create_fts_index('search_docs','matrix_code','search_text',overwrite=1)")
        s.close()

    # raw sources for the metadata-only explanations
    (root / "2-metas" / "ro").mkdir(parents=True)
    (root / "4-datasets" / "ro").mkdir(parents=True)
    (root / "logs").mkdir()
    for code in ("NOFILE1", "NOFILE2"):
        (root / "2-metas" / "ro" / f"{code}.json").write_text(json.dumps({"matrixName": code, "ultimaActualizare": "20-04-2026"}))
    (root / "4-datasets" / "ro" / "NOFILE1.csv").write_text("Grupe, Perioade, UM, Valoare\n")
    (root / "logs" / "fetch-csv.log").write_text(
        "2025-11-11 - WARNING - NOFILE1.csv - Empty dataset (excluding Totals)\n"
        "2025-11-11 - WARNING - NOFILE1.csv - RETRY FAILED: NOFILE1 still has no data\n")
    return root
