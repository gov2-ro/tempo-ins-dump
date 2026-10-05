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

NOTE: the manifest written by `manifest` is a PLACEHOLDER for the FIX-03
generation manifest. If <source>/generation-manifest.json exists it is embedded
verbatim under `generation.manifest`; replace `placeholder_generation()` with a
real consumer once FIX-03 defines the schema.
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
DB_FILES = ("metadata.duckdb", "search.duckdb")
MANIFEST_NAME = "MANIFEST.json"
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
    """Only what gets staged: DBs, parquet/*.parquet, view-profiles/*.json."""
    for n in DB_FILES:
        p = corpus / n
        if p.exists():
            yield n, p
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
def placeholder_generation(corpus: Path, files: dict) -> dict:
    """Placeholder until FIX-03 supplies a generation manifest."""
    gm = corpus / "generation-manifest.json"
    gen = {"status": "placeholder",
           "note": "FIX-03 generation manifest not available; id derived from DB hashes",
           "id": "staging-" + hashlib.sha256(
               "".join(files["corpus/" + n]["sha256"] for n in DB_FILES if "corpus/" + n in files).encode()
           ).hexdigest()[:12]}
    if gm.exists():
        try:
            gen["manifest"] = json.loads(gm.read_text())
            gen["status"] = "embedded"
            gen["id"] = gen["manifest"].get("generation_id", gen["id"])
        except Exception as e:  # unreadable manifest must not pass silently
            gen["status"] = f"unreadable: {e}"
    return gen


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
        "generation": placeholder_generation(corpus, files),
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


def check_stage(stage: Path, rep: Report, source: Path | None = None) -> dict | None:
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
    meta.close()

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
    if check_stage(prev, rep) is None or rep.failures:
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
    check_stage(stage, rep, Path(a.source) if a.source else None)
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
