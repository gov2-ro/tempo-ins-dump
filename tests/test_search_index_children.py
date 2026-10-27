"""The search index gives split children their parent's text (AQ live test, 2026-10-27).

A split child has only its own title in `matrices`; the English name, definition, tags and context
path live on the parent, which is not canonical and so not indexed. Children were found by title
words alone: "unitati invatamant" ranked SCL101A_judete 89th, behind unrelated national files.
"""
import importlib.util
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent


def _builder(db: Path, out: Path):
    spec = importlib.util.spec_from_file_location("build_search_index", ROOT / "scripts" / "build-search-index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB_PATH, mod.SEARCH_DB_PATH = db, out
    return mod


def test_split_children_inherit_the_parents_text_and_are_found_by_it(tmp_path):
    db = tmp_path / "metadata.duckdb"
    c = duckdb.connect(str(db))
    c.execute("""CREATE TABLE matrices (matrix_code VARCHAR, matrix_name VARCHAR, matrix_name_en VARCHAR,
                 definitie VARCHAR, is_canonical BOOLEAN, is_split BOOLEAN, parent_matrix_code VARCHAR,
                 ancestor_codes INTEGER[])""")
    c.execute("CREATE TABLE dataset_tags (matrix_code VARCHAR, tag_ro VARCHAR, tag_en VARCHAR)")
    c.execute("CREATE TABLE contexts (context_code VARCHAR, context_name VARCHAR, context_name_en VARCHAR)")
    c.execute("""INSERT INTO matrices VALUES
        ('SCLA', 'Unitatile de invatamant pe judete', 'Education units by county',
         'Unitatea de invatamant este o scoala cu personalitate juridica', FALSE, FALSE, NULL, [7]),
        ('SCLA_judete', 'Unitatile de invatamant pe judete [judete]', NULL, NULL, TRUE, TRUE, 'SCLA', NULL),
        ('OTHER', 'Alt indicator national', 'Another national indicator', 'fara legatura', TRUE, FALSE, NULL, [8])""")
    c.execute("INSERT INTO dataset_tags VALUES ('SCLA', 'scoli', 'schools')")
    c.execute("INSERT INTO contexts VALUES ('7', 'Educatie', 'Education'), ('8', 'Altele', 'Other')")
    c.close()
    out = tmp_path / "search.duckdb"
    _builder(db, out).build_index()

    s = duckdb.connect(str(out), read_only=True)
    name_en, definitie, tags_en, ctx_ro, text = s.execute(
        "SELECT name_en, definitie, tags_en, context_ro, search_text FROM search_docs WHERE matrix_code = 'SCLA_judete'").fetchone()
    assert name_en == "Education units by county [judete]"
    assert definitie.startswith("Unitatea de invatamant") and tags_en == "schools" and ctx_ro == "Educatie"
    assert "scoala" in text
    s.execute("LOAD fts")
    hits = [r[0] for r in s.execute("""
        SELECT matrix_code FROM (SELECT matrix_code, fts_main_search_docs.match_bm25(matrix_code, 'schools') AS score
                                 FROM search_docs) WHERE score IS NOT NULL""").fetchall()]
    assert hits == ["SCLA_judete"]
    assert s.execute("SELECT count(*) FROM search_docs WHERE matrix_code = 'SCLA'").fetchone()[0] == 0   # parent not indexed
