"""The landing lists each recent update under its theme or category, so the corpus
summary must say where every recently updated dataset sits in the category tree."""
import duckdb

from at01_fixtures import add_search_columns, make_env


def build(corpus):
    add_search_columns(corpus)
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    for ddl in ("trend_direction VARCHAR", "yoy_growth_latest DOUBLE"):
        db.execute(f"ALTER TABLE dataset_trends ADD COLUMN {ddl}")
    db.execute("UPDATE matrices SET ultima_actualizare = '2026-01-0' || CAST(rowid + 1 AS VARCHAR), "
               "context_code = CASE WHEN rowid = 0 THEN '1012' ELSE '6025' END")
    db.close()


def test_recently_updated_items_carry_their_context(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, build=build)
    import app.routers.categories as categories
    monkeypatch.setattr(categories, "compute_headlines", lambda *a, **k: [])
    db = duckdb.connect(str(env.corpus / "metadata.duckdb"), read_only=True)
    expected = dict(db.execute("SELECT matrix_code, context_code FROM matrices").fetchall())
    db.close()                       # before the app opens its own connection
    body = env.client.get("/api/corpus/summary").json()
    recent = body["recently_updated"]
    assert recent and all(item["context_code"] == expected[item["matrix_code"]] for item in recent)
    assert {item["context_code"] for item in recent} == {"1012", "6025"}
