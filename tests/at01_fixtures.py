"""Synthetic corpora for the AT-01 tool tests (`tempo-tools/1`).

Builds on fix02b_corpus (POPX, ADDX, RATEX, INCX with complete metadata tables)
and adds datasets with `add_dataset`. Order matters:

  1. make_env(tmp_path, monkeypatch, build=fn)  -> fn(corpus) adds datasets
  2. the manifest is written last (its db size must match the finished DB)
  3. only then call tools: the app opens the DB read-only on first use, and
     DuckDB refuses a second connection to that file with another config.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import duckdb

from fix02b_corpus import _write, make_client

GENERATION = "gen-at01-fixture"


def add_dataset(corpus, code: str, dims: list, rows: list, *, unit_type: str | None = "count",
                name: str | None = None, definition: str | None = None, parent: str | None = None,
                updated: str | None = "2026-01-15", file: bool = True):
    """dims: [(column, label, dim_type | None, [(option_label, parsed), ...])] in file
    column order; rows: tuples (dim values..., OBS_VALUE). Every dim is VARCHAR.
    `parsed` keys: year, quarter, month, geo_level, geo_name_clean, gender,
    age_min, age_max. `file=False` registers a metadata-only (split parent) row."""
    if file:
        ddl = ", ".join(f"{c} VARCHAR" for c, *_ in dims) + ", OBS_VALUE DOUBLE"
        if rows:
            _write(corpus / "parquet" / f"{code}.parquet", ddl, rows)
        else:
            c = duckdb.connect()
            c.execute(f"CREATE TABLE t ({ddl})")
            c.execute(f"COPY t TO '{corpus / 'parquet' / f'{code}.parquet'}' (FORMAT PARQUET)")
            c.close()
    years = [int(o[1]["year"]) for c, _, t, opts in dims if t == "time" for o in opts
             if o[1].get("year")]
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    did = db.execute("SELECT coalesce(max(dimension_id), 0) FROM dimensions").fetchone()[0]
    nid = db.execute("SELECT coalesce(max(nom_item_id), 0) FROM dimension_options").fetchone()[0]
    db.execute("INSERT INTO matrices (matrix_code, matrix_name, matrix_name_en, row_count, "
               "definitie, parent_matrix_code, is_split, ultima_actualizare) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
               [code, name or code, name or code, len(rows), definition or (name or code),
                parent, parent is not None, updated])
    db.execute("INSERT INTO matrix_profiles VALUES (?, ?, 'x', ?, ?, '[]')",
               [code, unit_type, min(years) if years else None, max(years) if years else None])
    for i, (col, label, dtype, opts) in enumerate(dims, 1):
        did += 1
        db.execute("INSERT INTO dimensions VALUES (?, ?, ?, ?, ?, ?)",
                   [did, code, i, label, col, len(opts)])
        for off, (olabel, parsed) in enumerate(opts):
            nid += 1
            p = {"year": None, "quarter": None, "month": None, "geo_level": None,
                 "geo_name_clean": None, "gender": None, "age_min": None, "age_max": None,
                 **parsed}
            db.execute("INSERT INTO dimension_options VALUES (?, ?, ?, ?, NULL)",
                       [did, nid, olabel, off])
            db.execute("INSERT INTO dimension_options_parsed VALUES "
                       "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 0.9)",
                       [nid, dtype, p["year"], p["quarter"], p["month"], p["geo_level"],
                        p["geo_name_clean"], p["gender"], p["age_min"], p["age_max"]])
            db.execute("INSERT INTO sdmx_codes VALUES (?, ?, ?)", [nid, olabel.strip(), olabel.strip()])
    db.close()


def add_split(corpus, parent: str, child: str, label: str, split_dimensions: dict):
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("INSERT INTO dataset_splits VALUES (?, ?, ?, NULL, ?)",
               [parent, child, label, json.dumps(split_dimensions)])
    db.close()


def add_search_columns(corpus):
    """Columns dataset_search filters on that fix02b's minimal schema lacks
    (discover_indicators' family results go through it)."""
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("ALTER TABLE matrices ADD COLUMN is_canonical BOOLEAN DEFAULT TRUE")
    for ddl in ("has_time BOOLEAN", "has_geo BOOLEAN", "time_granularity VARCHAR",
                "has_gender BOOLEAN", "has_age BOOLEAN", "has_residence BOOLEAN"):
        db.execute(f"ALTER TABLE matrix_profiles ADD COLUMN {ddl}")
    db.close()


def write_manifest(corpus, generation_id: str = GENERATION, *, conflicting=(), duplicate=()):
    m = {"generation_id": generation_id, "built_at": "2026-10-15T00:00:00+00:00",
         "db": {"size": (corpus / "metadata.duckdb").stat().st_size},
         "audit": {"grain_checked": True,
                   "violations": {"conflicting_grain": list(conflicting)},
                   "grain_findings": {"duplicate_grain": list(duplicate),
                                      "conflicting_grain": list(conflicting)}}}
    (corpus / "generation-manifest.json").write_text(json.dumps(m))


def make_env(tmp_path, monkeypatch, build=None, *, generation_id: str | None = GENERATION,
             conflicting=(), duplicate=()):
    """TestClient + corpus with every data path patched (fix02b_corpus.make_client).
    generation_id=None leaves the manifest missing."""
    client = make_client(tmp_path, monkeypatch)
    corpus = tmp_path / "corpus"
    if build:
        build(corpus)
    if generation_id:
        write_manifest(corpus, generation_id, conflicting=conflicting, duplicate=duplicate)
    from app.services import grain_guard
    monkeypatch.setattr(grain_guard, "_cache", type(grain_guard._cache)())
    return SimpleNamespace(client=client, corpus=corpus)


def call(name: str, **arguments) -> dict:
    """Run a tool through the registry and check its envelope against the schemas."""
    from app.services.tools.registry import call_tool, validate_result
    env = call_tool(name, arguments)
    validate_result(name, env)
    return env
