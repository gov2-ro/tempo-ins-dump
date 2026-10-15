"""The landing lists each recent update under its theme or category: the corpus
summary keeps the last 30 days, at most 3 per second-level category, and says
where each dataset sits in the category tree."""
from datetime import date, timedelta

import duckdb

from at01_fixtures import add_dataset, add_search_columns, make_env

TODAY = date.today()
TIME = ("TIME_PERIOD", "Perioade", "time", [("Anul 2024", {"year": 2024})])
# code: (days since its update, context code). Contexts: 10 > 1012 and 63 > 6025.
UPDATES = {"P1": (0, "1012"), "P2": (1, "1012"), "P3": (2, "10"), "P4": (3, "1012"),
           "T1": (5, "6025"), "T2": (30, "6025"), "OLD": (31, "6025")}


def build(corpus):
    for code in UPDATES:
        add_dataset(corpus, code, [TIME], [("Anul 2024", 1.0)])
    add_search_columns(corpus)       # after add_dataset, whose inserts list 6 profile columns
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    for ddl in ("trend_direction VARCHAR", "yoy_growth_latest DOUBLE"):
        db.execute(f"ALTER TABLE dataset_trends ADD COLUMN {ddl}")
    db.execute("UPDATE matrices SET ultima_actualizare = NULL")
    for code, (days, ctx) in UPDATES.items():
        db.execute("UPDATE matrices SET ultima_actualizare = ?, context_code = ? WHERE matrix_code = ?",
                   [str(TODAY - timedelta(days=days)), ctx, code])
    db.executemany("INSERT INTO contexts (context_code, context_name, parent_code, level) VALUES (?, ?, ?, ?)",
                   [("1", "A", "0", 0), ("10", "A.1", "1", 1), ("1012", "A.1.2", "10", 2),
                    ("2", "B", "0", 0), ("63", "B.18", "2", 1), ("6025", "B.18.1", "63", 2)])
    db.close()


def test_recent_updates_keep_30_days_and_three_per_category_with_context(tmp_path, monkeypatch):
    env = make_env(tmp_path, monkeypatch, build=build)
    import app.routers.categories as categories
    monkeypatch.setattr(categories, "compute_headlines", lambda *a, **k: [])
    recent = env.client.get("/api/corpus/summary").json()["recently_updated"]
    # A.1 keeps its 3 latest (P4 is fourth); B.18 keeps day 30, not day 31; newest first
    assert [(r["matrix_code"], r["context_code"]) for r in recent] == [
        ("P1", "1012"), ("P2", "1012"), ("P3", "10"), ("T1", "6025"), ("T2", "6025")]
    assert recent[0]["ultima_actualizare"] == str(TODAY)
