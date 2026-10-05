#!/usr/bin/env python
"""FIX-05 release gate: validate staged deploy data, optionally smoke the image.

One documented entry point (see readme.md "Release flow"):

    bash scripts/prepare-deploy-data.sh            # stage (atomic, with manifest)
    python scripts/release-check.py                # validate stage + run tests
    python scripts/release-check.py --docker       # + image build & smoke (needs docker)
    python scripts/release-check.py --docker --deploy   # + `fly deploy` (explicit only)
    python scripts/release-check.py --rollback     # swap deploy-data <-> deploy-data.prev

Nothing here deploys unless --deploy is passed, and validation never needs Fly
secrets. Exit code is non-zero on any failed gate.

Also used by prepare-deploy-data.sh via the `snapshot` and `manifest` helpers.

Generation manifest (FIX-03, scripts/build-generation-manifest.py): if
<source>/generation-manifest.json exists it is staged as
corpus/generation-manifest.json and summarised under `generation` in MANIFEST.json.
check_stage() FAILS when it is absent (unless --allow-missing-generation, which
prepare-deploy-data.sh uses for its internal pre-swap validation so staging still
works without one) and when it disagrees with the staged files: DB / search
sha256, parquet set + hashes + categories, view-profile digest, generation id,
DB row counts. Known audit violations are warnings (--require-clean-audit fails).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def digest_lines(pairs) -> str:
    """Same recipe as build-generation-manifest.digest_lines."""
    return hashlib.sha256("\n".join(f"{n}:{s}" for n, s in sorted(pairs)).encode()).hexdigest()


def compute_generation_id(db_sha, parquet_digest, vp_digest, search_sha) -> str:
    blob = json.dumps({"db_sha256": db_sha, "parquet_digest": parquet_digest,
                       "view_profiles_digest": vp_digest, "search_sha256": search_sha},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()

DB_FILES = ("metadata.duckdb", "search.duckdb")
MANIFEST_NAME = "MANIFEST.json"
GEN_NAME = "generation-manifest.json"
SCHEMA = 1


# ------------------------------------------------------------------ helpers
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stage_files(root: Path):
    """Relative paths of every file under the stage root except the manifest."""
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != MANIFEST_NAME:
            yield p.relative_to(root).as_posix(), p


# ------------------------------------------------------------------ snapshot
def source_files(corpus: Path):
    """Only what gets staged: DBs, generation manifest, parquet/*.parquet, view-profiles/*.json."""
    for n in DB_FILES:
        p = corpus / n
        if p.exists():
            yield n, p
    if (corpus / GEN_NAME).exists():
        yield GEN_NAME, corpus / GEN_NAME
    for sub, pat in (("parquet", "*.parquet"), ("view-profiles", "*.json")):
        for p in sorted((corpus / sub).glob(pat)):
            yield f"{sub}/{p.name}", p


def snapshot(corpus: Path) -> dict:
    """size+mtime for every staged source file, sha256 for the DBs.

    Taken before and after copying; any difference means the source changed
    mid-copy and the staging is rejected.
    """
    snap = {}
    for rel, p in source_files(corpus):
        st = p.stat()
        snap[rel] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
                     **({"sha256": sha256(p)} if rel in DB_FILES else {})}
    return snap


# ------------------------------------------------------------------ manifest
def generation_summary(stage_corpus: Path, files: dict) -> dict:
    """Summary of the staged generation manifest, or status 'absent'/'unreadable'."""
    gm = stage_corpus / GEN_NAME
    if not gm.exists():
        return {"status": "absent",
                "id": "staging-" + hashlib.sha256("".join(
                    files["corpus/" + n]["sha256"] for n in DB_FILES if "corpus/" + n in files
                ).encode()).hexdigest()[:12]}
    try:
        g = json.loads(gm.read_text())
        return {"status": "present", "id": g["generation_id"], "built_at": g.get("built_at"),
                "file": "corpus/" + GEN_NAME, "file_sha256": sha256(gm),
                "violation_counts": g.get("audit", {}).get("violation_counts"),
                "latest_observation_date": g.get("provenance", {}).get("latest_observation_date")}
    except Exception as e:  # unreadable manifest must not pass silently
        return {"status": f"unreadable: {e}", "id": "unreadable"}


def check_generation(stage: Path, listed: dict, canon_db_counts: dict, rep: "Report",
                     allow_missing: bool, require_clean: bool):
    """Verify corpus/generation-manifest.json against the staged files."""
    key = "corpus/" + GEN_NAME
    gp = stage / "corpus" / GEN_NAME
    if key not in listed or not gp.is_file():
        msg = f"corpus/{GEN_NAME} missing: no generation manifest ties DB, parquets, profiles and index together"
        (rep.warn if allow_missing else rep.fail)(msg + " (build with scripts/build-generation-manifest.py)")
        return None
    try:
        g = json.loads(gp.read_text())
        assert g["kind"] == "generation-manifest" and g["schema"] == 1
        gdb, gpq, gvp = g["db"], g["parquet"], g["view_profiles"]
        gsearch = g.get("search_index")
    except Exception as e:
        rep.fail(f"generation manifest unreadable/unsupported: {e!r}")
        return None
    problems = []
    # DB + search index
    if gdb["sha256"] != listed.get("corpus/metadata.duckdb", {}).get("sha256"):
        problems.append("metadata.duckdb sha256 differs from generation manifest")
    s_sha = listed.get("corpus/search.duckdb", {}).get("sha256")
    if (gsearch or {}).get("sha256") != s_sha:
        problems.append("search.duckdb sha256 differs from generation manifest")
    # parquet set + hashes
    staged_pq = {r.rsplit("/", 1)[1]: v["sha256"] for r, v in listed.items()
                 if r.startswith("corpus/parquet/") and r.endswith(".parquet")}
    want_pq = {c + ".parquet": f["sha256"] for c, f in gpq["files"].items()}
    miss, extra = sorted(set(want_pq) - set(staged_pq)), sorted(set(staged_pq) - set(want_pq))
    diff = sorted(n for n in set(want_pq) & set(staged_pq) if want_pq[n] != staged_pq[n])
    if miss or extra or diff:
        problems.append(f"parquet set differs: {len(miss)} missing, {len(extra)} unlisted, {len(diff)} hash "
                        f"mismatches, e.g. {(miss + extra + diff)[:3]}")
    if gpq["digest"] != digest_lines(staged_pq.items()) or gpq["count"] != len(gpq["files"]):
        problems.append("parquet digest/count inconsistent")
    # view profiles
    staged_vp = {r.rsplit("/", 1)[1]: v["sha256"] for r, v in listed.items()
                 if r.startswith("corpus/view-profiles/") and r.endswith(".json")}
    if gvp["digest"] != digest_lines(staged_vp.items()) or gvp["count"] != len(staged_vp):
        problems.append(f"view-profile digest/count differs ({len(staged_vp)} staged vs {gvp['count']})")
    # generation id
    gid = compute_generation_id(gdb["sha256"], gpq["digest"], gvp["digest"], (gsearch or {}).get("sha256"))
    if gid != g["generation_id"]:
        problems.append("generation_id does not match its component digests")
    # DB row counts
    bad_counts = sorted(t for t, n in gdb["row_counts"].items() if canon_db_counts.get(t) != n)
    if bad_counts:
        problems.append(f"DB table row counts differ for {bad_counts[:5]}")
    if problems:
        for p in problems:
            rep.fail("generation manifest vs staged files: " + p)
    else:
        rep.ok(f"generation manifest {g['generation_id'][:12]} consistent with staged DB, "
               f"{len(staged_pq)} parquets, {len(staged_vp)} profiles, search index")
    viol = {k: n for k, n in g.get("audit", {}).get("violation_counts", {}).items() if n}
    if viol:
        (rep.fail if require_clean else rep.warn)(f"generation audit has violations: {viol}")
    return g


def cmd_manifest(stage: Path, corpus: Path):
    import duckdb
    files = {rel: {"size": p.stat().st_size, "sha256": sha256(p)}
             for rel, p in stage_files(stage)}
    con = duckdb.connect(str(stage / "corpus" / "metadata.duckdb"), read_only=True)
    latest_obs, canon = con.execute(
        "SELECT MAX(ultima_actualizare), COUNT(*) FILTER (WHERE is_canonical) FROM matrices"
    ).fetchone()
    con.close()
    m = {
        "schema": SCHEMA,
        "kind": "staging-manifest",
        "staged_at": now_iso(),
        "generation": generation_summary(stage / "corpus", files),
        "source": {
            "dir": str(corpus),
            # file timestamps of the source generation (when it was BUILT),
            # distinct from the data's own observation date below.
            "generation_built_at": {n: iso((corpus / n).stat().st_mtime)
                                    for n in DB_FILES if (corpus / n).exists()},
            # latest INS update recorded in the data: old-but-consistent is fine.
            "latest_observation_date": str(latest_obs) if latest_obs else None,
        },
        "counts": {
            "canonical_matrices": canon,
            "parquet": sum(1 for r in files if r.startswith("corpus/parquet/")),
            "view_profiles": sum(1 for r in files if r.startswith("corpus/view-profiles/")),
        },
        "files": files,
    }
    (stage / MANIFEST_NAME).write_text(json.dumps(m, indent=1, sort_keys=True))
    print(f"manifest: {len(files)} files, generation {m['generation']['id']}")


# ------------------------------------------------------------------ validation
class Report:
    def __init__(self):
        self.failures, self.warnings, self.info = [], [], []

    def ok(self, msg):
        print(f"  ok    {msg}")

    def fail(self, msg):
        self.failures.append(msg)
        print(f"  FAIL  {msg}")

    def warn(self, msg):
        self.warnings.append(msg)
        print(f"  warn  {msg}")


def check_stage(stage: Path, rep: Report, source: Path | None = None,
                allow_missing_generation: bool = False, require_clean_audit: bool = False) -> dict | None:
    print(f"== staged artifacts: {stage}")
    mp = stage / MANIFEST_NAME
    if not mp.exists():
        rep.fail(f"{MANIFEST_NAME} missing (stage not produced by prepare-deploy-data.sh)")
        return None
    m = json.loads(mp.read_text())
    listed = m.get("files", {})
    bad = []
    for rel, meta in listed.items():
        p = stage / rel
        if not p.is_file():
            bad.append(f"missing {rel}")
        elif p.stat().st_size != meta["size"] or sha256(p) != meta["sha256"]:
            bad.append(f"hash/size mismatch {rel}")
    extra = [r for r, _ in stage_files(stage) if r not in listed]
    bad += [f"unlisted {r}" for r in extra]
    if bad:
        rep.fail(f"manifest vs files: {len(bad)} problems, e.g. {bad[:3]}")
    else:
        rep.ok(f"manifest matches {len(listed)} files (size + sha256)")

    for n in DB_FILES:
        if "corpus/" + n not in listed:
            rep.fail(f"corpus/{n} not in stage")
    if rep.failures:
        return m

    import duckdb
    meta = duckdb.connect(str(stage / "corpus" / "metadata.duckdb"), read_only=True)
    canon = {r[0] for r in meta.execute(
        "SELECT matrix_code FROM matrices WHERE is_canonical").fetchall()}
    # FTS loads + works (offline: no INSTALL here, mirrors the runtime image)
    index_mode = "unavailable"
    try:
        sc = duckdb.connect(str(stage / "corpus" / "search.duckdb"), read_only=True)
        sc.execute("LOAD fts")
        docs = {r[0] for r in sc.execute("SELECT matrix_code FROM search_docs").fetchall()}
        hit = sc.execute(
            "SELECT COUNT(*) FROM (SELECT fts_main_search_docs.match_bm25(matrix_code, ?) s "
            "FROM search_docs) WHERE s IS NOT NULL", ["populatia population"]).fetchone()[0]
        sc.close()
        index_mode = "fts"
        rep.ok(f"search.duckdb loads, FTS query works ({hit} hits for a probe query)")
        if docs != canon:
            rep.fail("index generation mismatch: search_docs has %d codes, metadata has %d "
                     "canonical (missing from index: %d, extra: %d) -> rebuild with "
                     "scripts/build-search-index.py" % (len(docs), len(canon),
                                                        len(canon - docs), len(docs - canon)))
        else:
            rep.ok(f"index covers all {len(canon)} canonical matrices")
    except Exception as e:
        rep.fail(f"FTS unavailable in staged search.duckdb: {e}")

    pq = {r.rsplit("/", 1)[1][:-8] for r in listed
          if r.startswith("corpus/parquet/") and r.endswith(".parquet")}
    missing = sorted(canon - pq)
    if missing:
        rep.fail(f"{len(missing)} canonical matrices have no staged parquet, e.g. {missing[:5]}")
    else:
        rep.ok("every canonical matrix has a staged parquet")
    splits = {r[0] for r in meta.execute("SELECT sub_matrix_code FROM dataset_splits").fetchall()}
    ms = sorted(splits - pq)
    if ms:
        rep.fail(f"{len(ms)} registered split children have no parquet, e.g. {ms[:5]}")
    orphans = pq - canon - splits
    if orphans:
        rep.warn(f"{len(orphans)} staged parquet files are not canonical/registered "
                 "(leftovers or split parents; copied for runtime fallbacks)")
    counts = {t: meta.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in {
        r[0] for r in meta.execute("SELECT table_name FROM information_schema.tables "
                                   "WHERE table_schema='main' AND table_type='BASE TABLE'").fetchall()}}
    meta.close()
    check_generation(stage, listed, counts, rep, allow_missing_generation, require_clean_audit)

    if source is not None:
        cur = {n: sha256(source / n) for n in DB_FILES if (source / n).exists()}
        stale = [n for n, h in cur.items() if listed.get("corpus/" + n, {}).get("sha256") != h]
        if stale:
            rep.fail(f"staging is STALE vs source ({stale} changed since staging): re-run prepare")
        else:
            rep.ok("staged DBs match current source hashes")

    g = m["generation"]
    print(f"   generation id : {g['id']} ({g['status']})")
    print(f"   staged at     : {m['staged_at']}")
    print(f"   source built  : {m['source']['generation_built_at']}")
    print(f"   latest source observation (max ultima_actualizare): "
          f"{m['source']['latest_observation_date']}")
    print(f"   index mode    : {index_mode}")
    return m


def run_tests(rep: Report):
    print("== tests")
    r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-rs"],
                       cwd=ROOT, capture_output=True, text=True)
    tail = "\n".join(r.stdout.strip().splitlines()[-6:])
    print(tail)
    if r.returncode != 0:
        rep.fail("pytest failed")
    else:
        rep.ok("pytest passed (skips are NOT passes; see summary above)")


# ------------------------------------------------------------------ docker smoke
def docker_smoke(rep: Report, stage: Path, port: int):
    print("== docker build + smoke")
    if not shutil.which("docker") or subprocess.run(
            ["docker", "info"], capture_output=True).returncode != 0:
        rep.fail("docker unavailable (use CI/another host, or omit --docker)")
        return
    import urllib.request
    m = json.loads((stage / MANIFEST_NAME).read_text())
    tag = "tempo-release-check:" + m["generation"]["id"]
    if subprocess.run(["docker", "build", "-t", tag, "."], cwd=ROOT).returncode:
        rep.fail("docker build failed")
        return
    cid = subprocess.run(["docker", "run", "-d", "--rm", "-p", f"{port}:8080", tag],
                         capture_output=True, text=True).stdout.strip()
    try:
        base = f"http://127.0.0.1:{port}"
        health = None
        for _ in range(40):
            try:
                health = json.load(urllib.request.urlopen(base + "/api/health", timeout=3))
                break
            except Exception:
                time.sleep(1)
        if not health:
            rep.fail("container did not become healthy")
            return
        if health["search"]["mode"] != "fts":
            rep.fail(f"image runs without FTS: {health['search']}")
        else:
            rep.ok("image: LOAD fts works offline, search mode fts")
        res = json.load(urllib.request.urlopen(base + "/api/datasets?q=population&limit=1"))
        if res.get("search_mode") != "fts" or not res["datasets"]:
            rep.fail(f"FTS query via image returned nothing/non-fts: {res.get('search_mode')}")
            return
        code = res["datasets"][0]["matrix_code"]
        d = json.load(urllib.request.urlopen(f"{base}/api/datasets/{code}/data?limit=5"))
        rep.ok(f"image serves FTS query and data endpoint ({code}, keys {sorted(d)[:4]})")
    finally:
        subprocess.run(["docker", "stop", cid], capture_output=True)
    return tag


# ------------------------------------------------------------------ rollback
def cmd_rollback(stage: Path):
    prev = stage.with_name(stage.name + ".prev")
    if not prev.is_dir():
        sys.exit(f"no previous staging at {prev}")
    rep = Report()
    if check_stage(prev, rep, allow_missing_generation=True) is None or rep.failures:
        sys.exit("previous staging does not validate; refusing to roll back")
    tmp = stage.with_name(stage.name + ".swap")
    if tmp.exists():
        shutil.rmtree(tmp)
    if stage.exists():
        os.rename(stage, tmp)
    os.rename(prev, stage)
    if tmp.exists():
        os.rename(tmp, prev)  # reversible: roll back again to undo
    print(f"rolled back: {stage} <- previous generation (old current kept at {prev})")


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("snapshot"); s.add_argument("corpus")
    mf = sub.add_parser("manifest"); mf.add_argument("stage"); mf.add_argument("corpus")
    ap.add_argument("--stage", default=str(ROOT / "deploy-data"))
    ap.add_argument("--source", help="corpus dir; also checks staging is not stale vs it")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--allow-missing-generation", action="store_true",
                    help="downgrade a missing generation manifest to a warning (staging step only)")
    ap.add_argument("--require-clean-audit", action="store_true",
                    help="fail when the generation manifest records audit violations")
    ap.add_argument("--docker", action="store_true", help="build image and smoke it")
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--deploy", action="store_true",
                    help="run `fly deploy` after ALL gates pass (never implicit)")
    ap.add_argument("--rollback", action="store_true")
    a = ap.parse_args()

    if a.cmd == "snapshot":
        print(json.dumps(snapshot(Path(a.corpus)), sort_keys=True)); return
    if a.cmd == "manifest":
        cmd_manifest(Path(a.stage), Path(a.corpus)); return
    stage = Path(a.stage)
    if a.rollback:
        cmd_rollback(stage); return

    rep = Report()
    check_stage(stage, rep, Path(a.source) if a.source else None,
                a.allow_missing_generation, a.require_clean_audit)
    if not a.skip_tests:
        run_tests(rep)
    if a.docker and not rep.failures:
        docker_smoke(rep, stage, a.port)
    print("\n== result")
    for w in rep.warnings:
        print(f"  warn: {w}")
    if rep.failures:
        print(f"RELEASE BLOCKED ({len(rep.failures)} failure(s))")
        for f in rep.failures:
            print(f"  - {f}")
        sys.exit(1)
    print("RELEASE CHECK PASSED")
    if a.deploy:
        if not a.docker:
            sys.exit("--deploy requires --docker (image smoke must have passed)")
        print("running: fly deploy")
        sys.exit(subprocess.run(["fly", "deploy"], cwd=ROOT).returncode)
    print("(not deploying: pass --deploy to run `fly deploy`)")


if __name__ == "__main__":
    main()
