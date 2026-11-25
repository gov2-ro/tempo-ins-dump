"""HZ-5a: weekly refresh pieces. No network, no served data: synthetic DuckDB files in tmp_path.

Covers: the stale INS check rule, retired-child cleanup, DB compaction (and its verification),
the orchestrator's --drop-csv / --probe-only / atomic writes, and the run script's schedule,
run copy, live-tree guard and prune.
"""
import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from test_fix03_orchestrator import pipe  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parent.parent


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ stale INS check (Work 3)
from app.services.dataset_meta import source_total_gate  # noqa: E402

DDL = ("CREATE TABLE kpi_total_checks (matrix_code VARCHAR PRIMARY KEY, period VARCHAR, ours DOUBLE, "
       "ins DOUBLE, rel DOUBLE, status VARCHAR, reason VARCHAR)")


def _decision(*verifs):
    return SimpleNamespace(dimensions=[{'column': f'D{i}', 'treatment': 'partition', 'verification': v}
                                       for i, v in enumerate(verifs)])


@pytest.fixture
def gate_conn():
    c = duckdb.connect()
    c.execute(DDL)
    c.executemany("INSERT INTO kpi_total_checks VALUES (?, ?, ?, ?, ?, ?, ?)", [
        ('M23', '2023', 10.0, 10.0, 0.0, 'match', None),
        ('MQ', '2025-Q1', 10.0, 10.0, 0.0, 'match', None),
        ('X23', '2023', 10.0, 12.0, 0.2, 'mismatch', None),
        ('NT23', '2023', 10.0, None, None, 'unresolved', 'no_total_option:SEX'),
    ])
    return c


def test_match_for_an_older_period_is_unchecked(gate_conn):
    weak = _decision('profile_flat')
    assert source_total_gate(gate_conn, 'M23', weak, latest_period='2024')[0] == 'source_total_unchecked'
    # never shown with the old check attached
    assert source_total_gate(gate_conn, 'M23', weak, latest_period='2024')[1] is None
    assert source_total_gate(gate_conn, 'MQ', weak, latest_period='2025-Q2')[0] == 'source_total_unchecked'


def test_match_for_the_latest_period_stands(gate_conn):
    weak = _decision('profile_flat')
    assert source_total_gate(gate_conn, 'M23', weak, latest_period='2023') == (
        None, {'source': 'INS', 'period': '2023', 'value': 10.0, 'relative_diff': 0.0})
    assert source_total_gate(gate_conn, 'M23', weak, latest_period='Anul 2023')[0] is None


def test_verified_sum_with_a_stale_match_stands_like_an_unchecked_one(gate_conn):
    assert source_total_gate(gate_conn, 'M23', _decision('verified'), latest_period='2024') == (None, None)


def test_without_a_period_the_rule_is_off(gate_conn):
    weak = _decision('profile_flat')
    assert source_total_gate(gate_conn, 'M23', weak)[0] is None          # callers that pass none: unchanged


def test_stale_mismatch_still_withholds_and_no_total_stays_no_total(gate_conn):
    assert source_total_gate(gate_conn, 'X23', _decision('verified'), latest_period='2025')[0] == 'source_total_mismatch'
    assert source_total_gate(gate_conn, 'NT23', _decision('profile_flat'), latest_period='2025')[0] == 'no_source_total'


# ------------------------------------------------------------------ retired children (Work 2)
def _corpus(tmp_path, with_orphans=True):
    data = tmp_path / "gen" / "data"
    corpus = data / "corpus"
    (corpus / "view-profiles").mkdir(parents=True)
    (corpus / "parquet").mkdir()
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("CREATE TABLE contexts (context_code VARCHAR PRIMARY KEY)")
    db.execute("CREATE TABLE matrices (matrix_code VARCHAR PRIMARY KEY, context_code VARCHAR REFERENCES contexts(context_code), "
               "parent_matrix_code VARCHAR)")
    db.execute("CREATE TABLE dimensions (dimension_id INTEGER PRIMARY KEY, matrix_code VARCHAR REFERENCES matrices(matrix_code))")
    db.execute("CREATE TABLE dimension_options (option_id INTEGER PRIMARY KEY, dimension_id INTEGER REFERENCES dimensions(dimension_id))")
    db.execute("CREATE TABLE dataset_splits (sub_matrix_code VARCHAR, parent_matrix_code VARCHAR)")
    for t in ("matrix_profiles", "dataset_trends", "dataset_coverage", "kpi_total_checks"):
        db.execute(f"CREATE TABLE {t} (matrix_code VARCHAR PRIMARY KEY, v INTEGER)")
    db.execute("CREATE TABLE dimension_structure (matrix_code VARCHAR, dim_column VARCHAR, PRIMARY KEY (matrix_code, dim_column))")
    db.execute("CREATE TABLE sdmx_column_map (matrix_code VARCHAR, old_column_name VARCHAR, PRIMARY KEY (matrix_code, old_column_name))")
    db.execute("CREATE TABLE dataset_relationships (matrix_a VARCHAR, matrix_b VARCHAR)")
    db.execute("INSERT INTO contexts VALUES ('C')")
    live = ["P1", "P1_a", "P1_b", "Q1"]
    for c in live:
        db.execute("INSERT INTO matrices VALUES (?, 'C', NULL)", [c])
    db.execute("INSERT INTO dimensions VALUES (1, 'P1'), (2, 'Q1')")
    db.execute("INSERT INTO dimension_options VALUES (1, 1), (2, 2)")
    db.execute("INSERT INTO dataset_splits VALUES ('P1_a', 'P1'), ('P1_b', 'P1')")
    codes = live + (["P1_old", "P1_older"] if with_orphans else [])
    for c in codes:
        for t in ("matrix_profiles", "dataset_trends", "dataset_coverage", "kpi_total_checks"):
            db.execute(f"INSERT INTO {t} VALUES (?, 1)", [c])
        db.execute("INSERT INTO dimension_structure VALUES (?, 'REF_AREA')", [c])
        db.execute("INSERT INTO sdmx_column_map VALUES (?, 'x')", [c])
        (corpus / "view-profiles" / f"{c}.json").write_text("{}")
    if with_orphans:
        db.execute("INSERT INTO dataset_splits VALUES ('P1_old', 'P1')")
        db.execute("INSERT INTO dataset_relationships VALUES ('P1', 'P1_old'), ('P1', 'Q1')")
    db.close()
    (corpus / "view-profiles" / "_index.json").write_text(json.dumps([{"code": c} for c in codes]))
    for c in live:
        (corpus / "parquet" / f"{c}.parquet").write_bytes(b"x")
    return data


def test_cleanup_removes_every_row_file_and_index_entry_of_a_retired_code(tmp_path):
    cleanup = load("cleanup_t", "scripts/cleanup-retired-children.py")
    data = _corpus(tmp_path)
    rep = cleanup.cleanup(data)
    assert rep["codes"] == ["P1_old", "P1_older"]
    assert set(rep["tables"]) == {"matrix_profiles", "dataset_trends", "dataset_coverage", "kpi_total_checks",
                                  "dimension_structure", "sdmx_column_map", "dataset_splits", "dataset_relationships"}
    db = duckdb.connect(str(data / "corpus" / "metadata.duckdb"), read_only=True)
    for t in ("matrix_profiles", "dimension_structure", "sdmx_column_map", "kpi_total_checks"):
        assert {r[0] for r in db.execute(f"SELECT matrix_code FROM {t}").fetchall()} == {"P1", "P1_a", "P1_b", "Q1"}
    assert db.execute("SELECT COUNT(*) FROM dataset_splits").fetchone()[0] == 2        # live children stay
    assert db.execute("SELECT matrix_b FROM dataset_relationships").fetchall() == [("Q1",)]   # the live pair stays
    db.close()


def test_cleanup_view_profiles_and_index(tmp_path):
    cleanup = load("cleanup_t2", "scripts/cleanup-retired-children.py")
    data = _corpus(tmp_path)
    rep = cleanup.cleanup(data)
    vp = data / "corpus" / "view-profiles"
    assert sorted(p.stem for p in vp.glob("*.json")) == ["P1", "P1_a", "P1_b", "Q1", "_index"]
    assert [e["code"] for e in json.loads((vp / "_index.json").read_text())] == ["P1", "P1_a", "P1_b", "Q1"]
    assert rep["index_entries"] == 2 and sorted(rep["view_profiles"]) == ["P1_old", "P1_older"]


def test_cleanup_is_a_noop_on_a_clean_corpus_and_dry_run_writes_nothing(tmp_path):
    cleanup = load("cleanup_t3", "scripts/cleanup-retired-children.py")
    data = _corpus(tmp_path, with_orphans=False)
    assert cleanup.cleanup(data)["codes"] == []
    data2 = _corpus(tmp_path / "b")
    before = (data2 / "corpus" / "metadata.duckdb").read_bytes()
    rep = cleanup.cleanup(data2, dry_run=True)
    assert rep["codes"] and (data2 / "corpus" / "metadata.duckdb").read_bytes() == before
    assert (data2 / "corpus" / "view-profiles" / "P1_old.json").exists()


def test_cleanup_reports_but_keeps_orphan_parquet(tmp_path):
    cleanup = load("cleanup_t4", "scripts/cleanup-retired-children.py")
    data = _corpus(tmp_path)
    (data / "corpus" / "parquet" / "P1_old.parquet").write_bytes(b"x")
    rep = cleanup.cleanup(data)
    assert rep["orphan_parquet"] == ["P1_old"] and (data / "corpus" / "parquet" / "P1_old.parquet").exists()


def test_cleanup_refuses_the_repository_data_dir():
    cleanup = load("cleanup_t5", "scripts/cleanup-retired-children.py")
    with pytest.raises(SystemExit):
        cleanup.main(["--data-dir", str(ROOT / "data")])


# ------------------------------------------------------------------ compaction (Work 4)
def _bloated(tmp_path):
    p = tmp_path / "src.duckdb"
    db = duckdb.connect(str(p))
    db.execute("CREATE SEQUENCE seq_dimension_id START 101")
    db.execute("CREATE TABLE contexts (context_code VARCHAR PRIMARY KEY, n INTEGER)")
    db.execute("CREATE TABLE matrices (matrix_code VARCHAR PRIMARY KEY, context_code VARCHAR REFERENCES contexts(context_code), "
               "name VARCHAR, row_count BIGINT, is_split BOOLEAN DEFAULT CAST('f' AS BOOLEAN))")
    db.execute("CREATE TABLE dimensions (dimension_id INTEGER PRIMARY KEY, matrix_code VARCHAR REFERENCES matrices(matrix_code), "
               "label VARCHAR)")
    db.execute("CREATE TABLE dimension_options (option_id INTEGER PRIMARY KEY, dimension_id INTEGER REFERENCES dimensions(dimension_id), "
               "label VARCHAR)")
    db.execute("CREATE TABLE notes (matrix_code VARCHAR, note VARCHAR, ts TIMESTAMP DEFAULT current_timestamp)")
    db.execute("CREATE INDEX idx_dim_label ON dimensions(label)")
    db.execute("CREATE VIEW v_big AS SELECT matrix_code FROM matrices WHERE row_count > 5")
    db.execute("INSERT INTO contexts VALUES ('C', 1)")
    db.execute("INSERT INTO matrices VALUES ('A', 'C', 'ñame ăș', 10, false), ('B', 'C', NULL, 3, true)")
    db.execute("INSERT INTO dimensions SELECT i, CASE WHEN i % 2 = 0 THEN 'A' ELSE 'B' END, 'd' || i FROM range(1, 40) t(i)")
    db.execute("INSERT INTO dimension_options SELECT i, 1 + i % 39, 'o' || i FROM range(1, 4000) t(i)")
    db.execute("INSERT INTO notes SELECT 'A', repeat(md5(random()::VARCHAR), 12), now() FROM range(60000)")
    db.execute("DELETE FROM notes WHERE rowid % 50 <> 0")        # leaves free blocks behind
    db.execute("CHECKPOINT")
    db.close()
    return p


def test_compact_copies_everything_in_fk_order_and_verifies(tmp_path):
    compact = load("compact_t", "scripts/compact-metadata.py")
    src = _bloated(tmp_path)
    dst = tmp_path / "out" / "dst.duckdb"
    dst.parent.mkdir()
    rep = compact.compact(src, dst)
    assert rep["ok"], rep
    assert rep["dst_bytes"] < rep["src_bytes"]
    db = duckdb.connect(str(dst), read_only=True)
    assert db.execute("SELECT COUNT(*) FROM dimension_options").fetchone()[0] == 3999
    assert db.execute("SELECT name FROM matrices WHERE matrix_code = 'A'").fetchone()[0] == 'ñame ăș'
    assert db.execute("SELECT COUNT(*) FROM v_big").fetchone()[0] == 1
    assert {r[0] for r in db.execute("SELECT index_name FROM duckdb_indexes()").fetchall()} == {"idx_dim_label"}
    db.close()
    w = duckdb.connect(str(dst))
    with pytest.raises(duckdb.Error):                                   # the FK still bites
        w.execute("INSERT INTO dimensions VALUES (999, 'NOPE', 'x')")
    w.close()


def test_compact_fk_order_puts_parents_first(tmp_path):
    compact = load("compact_t2", "scripts/compact-metadata.py")
    con = duckdb.connect()
    con.execute("ATTACH '" + str(_bloated(tmp_path)) + "' AS s (READ_ONLY)")
    order = compact.tables_in_fk_order(con, "s")
    assert order.index("contexts") < order.index("matrices") < order.index("dimensions") < order.index("dimension_options")


def test_compact_detects_a_difference_and_removes_the_result(tmp_path, monkeypatch):
    compact = load("compact_t3", "scripts/compact-metadata.py")
    src = _bloated(tmp_path)
    real = compact.fingerprint

    def lying(con, db):
        fp = real(con, db)
        if db == "dst":
            fp["tables"]["notes"]["hash"] = "0"
        return fp

    monkeypatch.setattr(compact, "fingerprint", lying)
    dst = tmp_path / "dst.duckdb"
    rep = compact.compact(src, dst)
    assert not rep["ok"] and any("notes: hash" in p for p in rep["problems"])
    assert not dst.exists()


def test_compact_hash_catches_a_changed_value(tmp_path):
    compact = load("compact_t4", "scripts/compact-metadata.py")
    a = duckdb.connect()
    a.execute("CREATE TABLE t (x VARCHAR, y INTEGER)")
    a.execute("INSERT INTO t VALUES ('a', 1), ('b', 2)")
    h1 = a.execute("SELECT SUM(hash(__row)::HUGEINT)::VARCHAR FROM t __row").fetchone()[0]
    a.execute("UPDATE t SET y = 3 WHERE x = 'b'")
    h2 = a.execute("SELECT SUM(hash(__row)::HUGEINT)::VARCHAR FROM t __row").fetchone()[0]
    assert h1 != h2


def test_compact_refuses_existing_destination_and_repo_data(tmp_path):
    compact = load("compact_t5", "scripts/compact-metadata.py")
    src = _bloated(tmp_path)
    existing = tmp_path / "e.duckdb"
    existing.write_bytes(b"x")
    with pytest.raises(SystemExit):
        compact.compact(src, existing)
    with pytest.raises(SystemExit):
        compact.compact(src, ROOT / "data" / "corpus" / "x.duckdb")


# ------------------------------------------------------------------ orchestrator additions
def test_drop_csv_removes_the_csv_after_stage_9_and_not_before(pipe):
    csv = pipe.tmp / "data" / "4-datasets" / "ro" / "AAA1.csv"
    csv.parent.mkdir(parents=True)
    csv.write_text("h\n1\n")
    seen = {}
    orig = pipe.mod.subprocess.run

    def watch(cmd, **kw):
        script = Path(cmd[1]).name
        if script in ("9-csv-to-parquet.py", "12-split-datasets.py"):
            seen[script] = csv.exists()
        return orig(cmd, **kw)

    pipe.mod.subprocess.run = watch
    pipe.feed([("05.05.2026", "AAA1")])
    assert pipe.go("--drop-csv") == 0
    assert seen == {"9-csv-to-parquet.py": True, "12-split-datasets.py": False}
    assert not csv.exists()


def test_csv_is_kept_without_the_flag_and_when_stage_9_fails(pipe):
    csv = pipe.tmp / "data" / "4-datasets" / "ro" / "AAA1.csv"
    csv.parent.mkdir(parents=True)
    csv.write_text("h\n1\n")
    pipe.feed([("05.05.2026", "AAA1")])
    assert pipe.go() == 0 and csv.exists()
    pipe.rcs[("9-csv-to-parquet.py", "AAA1")] = 1
    assert pipe.go("--drop-csv", "--matrix", "AAA1") == 1
    assert csv.exists()                                         # a failed matrix keeps its input for inspection


def test_probe_only_changes_nothing_and_reports_the_probe(pipe):
    assert pipe.go("--probe-only") == 0
    assert pipe.calls == [] and not pipe.state_path.exists()
    pipe.probe_fail = "HTTP 500"
    assert pipe.go("--probe-only") == 1
    assert pipe.calls == [] and not pipe.state_path.exists()


def test_fetch_meta_replaces_the_file_so_a_hard_link_keeps_the_old_content(tmp_path, monkeypatch):
    mod = load("up_t", "update-pipeline.py")
    monkeypatch.setattr(mod, "BASE_DIR", tmp_path)
    metas = tmp_path / "data" / "2-metas" / "ro"
    metas.mkdir(parents=True)
    (metas / "AAA1.json").write_text('{"v": 1}')
    live = tmp_path / "live.json"
    os.link(metas / "AAA1.json", live)
    resp = SimpleNamespace(content=b'{"v": 2}', raise_for_status=lambda: None)
    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: resp)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    assert mod.fetch_meta("AAA1", "ro", force=True)
    assert json.loads((metas / "AAA1.json").read_text()) == {"v": 2}
    assert json.loads(live.read_text()) == {"v": 1}


# ------------------------------------------------------------------ the run script
@pytest.fixture(scope="module")
def rr():
    return load("refresh_run_t", "scripts/refresh-run.py")


def test_schedule(rr):
    sun, mon = date(2026, 11, 22), date(2026, 11, 23)
    assert sun.weekday() == 6
    assert rr.is_due(sun, {}, 7, False)[0]
    assert not rr.is_due(mon, {}, 7, False)[0]
    assert rr.is_due(mon, {"pending_since": "2026-11-22"}, 7, False)[0]            # retry day
    assert rr.is_due(date(2026, 11, 28), {"pending_since": "2026-11-22"}, 7, False)[0]   # day 7: last try
    ok, why = rr.is_due(date(2026, 11, 29), {"pending_since": "2026-11-22"}, 7, False)
    assert not ok and "gave up" in why
    assert rr.is_due(mon, {}, 7, True)[0]


def _working_data(tmp_path):
    d = tmp_path / "base" / "data"
    (d / "corpus" / "parquet").mkdir(parents=True)
    (d / "corpus" / "view-profiles").mkdir()
    (d / "corpus" / "parquet" / "A.parquet").write_bytes(b"parquet-A")
    (d / "corpus" / "metadata.duckdb").write_bytes(b"db")
    (d / "corpus" / "view-profiles" / "A.json").write_text("{}")
    (d / "2-metas" / "ro").mkdir(parents=True)
    (d / "2-metas" / "ro" / "A.json").write_text("{}")
    (d / "logs").mkdir()
    (d / "logs" / "update-pipeline-state.json").write_text("{}")
    (d / "logs" / "fetch-csv.log").write_text("old log")
    (d / "4-datasets" / "ro").mkdir(parents=True)
    (d / "4-datasets" / "ro" / "A.csv").write_text("big")
    (d / "parquet-v2").mkdir()
    (d / "insse_news.csv").write_text("news")
    return d


def test_run_copy_links_only_parquet_and_skips_csv_and_old_logs(rr, tmp_path):
    src = _working_data(tmp_path)
    dst = tmp_path / "run" / "data"
    rr.copy_working_data(src, dst)
    assert os.path.samefile(src / "corpus/parquet/A.parquet", dst / "corpus/parquet/A.parquet")
    assert not os.path.samefile(src / "corpus/metadata.duckdb", dst / "corpus/metadata.duckdb")
    assert not os.path.samefile(src / "2-metas/ro/A.json", dst / "2-metas/ro/A.json")
    assert (dst / "insse_news.csv").read_text() == "news"
    assert sorted(p.name for p in (dst / "logs").iterdir()) == ["update-pipeline-state.json"]
    assert not (dst / "4-datasets").exists() and not (dst / "parquet-v2").exists()


def test_live_tree_guard_catches_an_in_place_parquet_write_and_not_a_replace(rr, tmp_path):
    src = _working_data(tmp_path)
    dst = tmp_path / "run" / "data"
    rr.copy_working_data(src, dst)
    before = rr.snapshot(src)
    # replace by rename (what stages 9 and 12 do): the live file keeps its inode and content
    tmp = dst / "corpus/parquet/A.parquet.tmp"
    tmp.write_bytes(b"new")
    os.replace(tmp, dst / "corpus/parquet/A.parquet")
    assert rr.changed_files(before, rr.snapshot(src)) == []
    assert (src / "corpus/parquet/A.parquet").read_bytes() == b"parquet-A"
    # a write into the shared inode is caught
    (dst / "corpus/parquet").joinpath("B.parquet").write_bytes(b"b")
    os.link(dst / "corpus/parquet/B.parquet", src / "corpus/parquet/B.parquet")
    before = rr.snapshot(src)
    with open(dst / "corpus/parquet/B.parquet", "ab") as f:
        f.write(b"more")
    assert rr.changed_files(before, rr.snapshot(src)) == ["corpus/parquet/B.parquet"]


def test_prune_keeps_the_newest_runs_and_the_protected_one(rr, tmp_path):
    base = tmp_path / "b"
    for n in ("20261101-0300", "20261108-0300", "20261115-0300", "20261122-0300"):
        (base / "runs" / n).mkdir(parents=True)
    rr._prune(base, keep=2, protect="20261108-0300")
    assert sorted(p.name for p in (base / "runs").iterdir()) == ["20261108-0300", "20261115-0300", "20261122-0300"]


def test_notify_posts_to_the_webhook_and_survives_a_failure(rr, monkeypatch, capsys):
    sent = []
    monkeypatch.setenv("TEMPO_NOTIFY_URL", "http://hook.invalid/x")

    class R:
        def read(self):
            return b""

    monkeypatch.setattr(rr.urllib.request, "urlopen", lambda req, timeout=0: (sent.append(req.data), R())[1])
    rr.notify("hello")
    assert sent == [b"hello"]
    monkeypatch.setattr(rr.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    rr.notify("again")                                           # must not raise
    assert "notification failed" in capsys.readouterr().out


def test_probe_failure_notifies_on_day_one_and_leaves_the_working_data_alone(rr, tmp_path, monkeypatch):
    base = tmp_path / "base"
    _working_data(tmp_path)
    msgs = []
    monkeypatch.setattr(rr, "notify", msgs.append)
    snap = rr.snapshot(base / "data")
    assert rr.main(["--base", str(base), "--force", "--simulate-probe-failure", "--run-id", "r1"]) == 0
    st = json.loads((base / "status.json").read_text())
    assert st["outcome"] == "probe_failed" and st["pending_since"] == date.today().isoformat()
    assert len(msgs) == 1 and "does not answer" in msgs[0]
    assert rr.changed_files(snap, rr.snapshot(base / "data")) == []
    assert not (base / "runs" / "r1").exists()
    # day two (the same pending day here): still failing, no new notification before day 7
    assert rr.main(["--base", str(base), "--force", "--simulate-probe-failure", "--run-id", "r2"]) == 0
    assert len(msgs) == 1


# ------------------------------------------------------------------ the stale rule end to end (insights)
def _client_with_period(tmp_path, monkeypatch, period):
    from fix02b_corpus import make_client
    client = make_client(tmp_path, monkeypatch, structure=True)
    db = duckdb.connect(str(tmp_path / "corpus" / "metadata.duckdb"))
    db.execute(DDL)
    db.execute("INSERT INTO kpi_total_checks VALUES ('POPX', ?, 110, 110, 0.0, 'match', NULL)", [period])
    db.close()
    return client


@pytest.mark.xfail(strict=True, reason="stale rule not yet active in insights.py: activate it after the full "
                   "INS re-check (docs/plans/hz-5-record.md section 8)")
def test_insights_publishes_a_current_match_and_withholds_an_older_one(tmp_path, monkeypatch):
    client = _client_with_period(tmp_path / "a", monkeypatch, '2025')
    assert any(k["key"] == "latest" for k in client.get("/api/datasets/POPX/insights").json()["kpis"])
    client = _client_with_period(tmp_path / "b", monkeypatch, '2024')
    ins = client.get("/api/datasets/POPX/insights").json()
    assert not any(k["key"] == "latest" for k in ins["kpis"])
    assert {"key": "latest", "reason": "source_total_unchecked"}.items() <= next(
        s for s in ins["suppressed"] if s["key"] == "latest").items()


# ------------------------------------------------------------------ the audit's bucketed grain check
def test_bucketed_grain_check_gives_the_single_pass_result(tmp_path, monkeypatch):
    audit = load("audit_t", "scripts/audit-corpus.py")
    f = tmp_path / "X.parquet"
    con = duckdb.connect()
    con.execute("CREATE TABLE t (REF_AREA VARCHAR, TIME_PERIOD VARCHAR, OBS_VALUE DOUBLE)")
    con.execute("INSERT INTO t SELECT 'A' || (i % 50), '2020', i FROM range(200) r(i)")      # 50 keys x 4 rows, all conflicting
    con.execute("INSERT INTO t SELECT 'B' || (i % 7), '2021', 1.0 FROM range(70) r(i)")      # 7 keys x 10 rows, same value
    con.execute("INSERT INTO t VALUES ('C', '2022', 1.0), (NULL, '2022', 1.0), (NULL, '2022', 2.0)")
    con.execute(f"COPY t TO '{f}' (FORMAT PARQUET)")
    monkeypatch.delenv("TEMPO_AUDIT_GRAIN_BUCKET_ROWS", raising=False)
    one = audit.inspect_parquet(duckdb.connect(), f, True)
    assert (one["dup_keys"], one["dup_rows"], one["conflicting_keys"]) == (58, 272, 51)
    for per in ("7", "30", "1000"):
        monkeypatch.setenv("TEMPO_AUDIT_GRAIN_BUCKET_ROWS", per)
        many = audit.inspect_parquet(duckdb.connect(), f, True)
        assert (many["dup_keys"], many["dup_rows"], many["conflicting_keys"]) == (58, 272, 51), per


# ------------------------------------------------------------------ check-kpi-totals --write-db with nothing to write
def test_write_db_with_no_results_replaces_the_touched_codes_and_keeps_the_rest(tmp_path):
    ck = load("ck_t", "scripts/check-kpi-totals.py")
    db = tmp_path / "m.duckdb"
    con = duckdb.connect(str(db))
    con.execute(ck.TABLE_DDL)
    con.execute("INSERT INTO kpi_total_checks VALUES ('OTHER', '2022', 1, 1, 0, 'match', NULL, NULL, NULL, NULL)")
    con.execute("INSERT INTO kpi_total_checks VALUES ('TOUCHED', '2020', 9, 9, 0, 'match', NULL, NULL, NULL, NULL)")
    con.close()
    # no result at all (the touched dataset sums nothing now): must not raise, must drop its old row
    assert ck.write_db(db, {}, codes={"TOUCHED"}) == 0
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("SELECT matrix_code FROM kpi_total_checks").fetchall() == [("OTHER",)]
    con.close()
    assert ck.write_db(db, {}) == 0


# ------------------------------------------------------------------ run script helpers
def test_sweep_codes_split_updates_from_codes_ins_no_longer_lists(rr, tmp_path):
    (tmp_path / "changes.csv").write_text(
        "code,kind,ins_update,db_update\nA1,updated,01-11-2026,2026-01-01\nB2,new_in_ins,01-11-2026,\n"
        "C3,not_listed_by_ins,01-01-2020,2020-01-01\n")
    assert rr.sweep_codes(tmp_path) == (["A1", "B2"], ["C3"])
    assert rr.sweep_codes(tmp_path / "missing") == ([], [])


def test_touched_codes_are_this_runs_ok_parents_and_their_children(rr, tmp_path):
    data = tmp_path / "data"
    (data / "corpus").mkdir(parents=True)
    (data / "logs").mkdir()
    db = duckdb.connect(str(data / "corpus" / "metadata.duckdb"))
    db.execute("CREATE TABLE dataset_splits (sub_matrix_code VARCHAR, parent_matrix_code VARCHAR)")
    db.execute("INSERT INTO dataset_splits VALUES ('P_a', 'P'), ('P_b', 'P'), ('Z_a', 'Z')")
    db.close()
    (data / "logs" / "update-pipeline-state.json").write_text(json.dumps({"matrices": {
        "P": {"outcome": "ok", "updated_at": "2026-11-25T03:00:10"},
        "Q": {"outcome": "failed", "updated_at": "2026-11-25T03:00:20"},
        "Z": {"outcome": "ok", "updated_at": "2026-11-18T03:00:10"},        # an earlier run
        "E": {"outcome": "empty", "updated_at": "2026-11-25T03:00:30"}}}))
    assert rr.touched_codes(data, "2026-11-25T03:00:00") == ["P", "P_a", "P_b"]


def test_stale_dimension_checks_of_touched_codes_are_dropped(rr, tmp_path):
    db = tmp_path / "m.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE kpi_dimension_checks (matrix_code VARCHAR, dim_column VARCHAR)")
    con.execute("INSERT INTO kpi_dimension_checks VALUES ('T', 'AGE'), ('KEEP', 'AGE')")
    con.close()
    rr.clear_stale_dim_checks(db, ["T"])
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("SELECT matrix_code FROM kpi_dimension_checks").fetchall() == [("KEEP",)]
    con.close()


def test_candidate_code_folder_has_what_deploy_sh_uploads(rr, tmp_path):
    out = rr.build_candidate(tmp_path, ROOT)
    for f in rr.CODE_FILES:
        assert (out / f).is_file(), f
    assert (out / "app" / "main.py").is_file()
    assert not list(out.rglob("__pycache__"))
    deploy = (ROOT / "scripts" / "deploy" / "hetzner" / "deploy.sh").read_text()
    for f in rr.CODE_FILES:                                         # the two lists must not drift apart
        assert f in deploy, f


def test_not_due_run_exits_quietly(rr, tmp_path, capsys):
    base = tmp_path / "base"
    (base / "data").mkdir(parents=True)
    if date.today().weekday() == 6:
        pytest.skip("today is a Sunday: a run is due")
    assert rr.main(["--base", str(base)]) == 0
    assert "not due" in capsys.readouterr().out
    assert not (base / "runs").exists()
