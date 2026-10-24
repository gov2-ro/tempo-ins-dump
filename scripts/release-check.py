#!/usr/bin/env python
"""FIX-05 release gate: validate staged deploy data, optionally smoke the image.

One documented entry point (see readme.md "Release flow"):

    bash scripts/prepare-deploy-data.sh            # stage (atomic, with manifest)
    python scripts/release-check.py                # validate stage + run tests
    python scripts/release-check.py --docker       # + image build & smoke (needs docker)
    python scripts/release-check.py --local --stage DIR  # + the same smoke on this checkout, no image
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


# Audit violations the app enforces at query time, per generation (PA-04). A
# restriction is accepted only when the manifest lists the affected files where
# the enforcing code reads them, and that code is present in the release.
ENFORCED_RESTRICTIONS = {
    "conflicting_grain": {"findings": "conflicting_grain", "enforcer": "app/services/grain_guard.py"},
}


def accept_restrictions(g: dict, viol: dict, accepted: list, rep: "Report") -> dict:
    """Return the violations still blocking after accepted, enforceable ones."""
    left = dict(viol)
    for name in accepted or []:
        rule = ENFORCED_RESTRICTIONS.get(name)
        if rule is None:
            rep.fail(f"--accept-restriction {name}: no enforcement is defined for this violation")
            continue
        if name not in left:
            continue
        listed = set((g.get("audit", {}).get("grain_findings") or {}).get(rule["findings"]) or [])
        violating = set(g.get("audit", {}).get("violations", {}).get(name) or [])
        if not listed or not violating <= listed:
            rep.fail(f"restriction {name}: generation manifest lacks audit.grain_findings for "
                     f"{len(violating - listed)} violating files; the app could not enforce it")
            continue
        if not (ROOT / rule["enforcer"]).is_file():
            rep.fail(f"restriction {name}: enforcer {rule['enforcer']} missing from this release")
            continue
        rep.ok(f"accepted restriction {name}: {len(violating)} served files; aggregations over them "
               f"are refused by {rule['enforcer']} (generation-bound)")
        rep.restrictions.append({"violation": name, "files": len(violating), "enforcer": rule["enforcer"]})
        left.pop(name)
    return left


def check_generation(stage: Path, listed: dict, canon_db_counts: dict, rep: "Report",
                     allow_missing: bool, require_clean: bool, accepted=None):
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
        viol = accept_restrictions(g, viol, accepted, rep)
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
        self.failures, self.warnings, self.info, self.restrictions = [], [], [], []

    def ok(self, msg):
        print(f"  ok    {msg}")

    def fail(self, msg):
        self.failures.append(msg)
        print(f"  FAIL  {msg}")

    def warn(self, msg):
        self.warnings.append(msg)
        print(f"  warn  {msg}")


def check_stage(stage: Path, rep: Report, source: Path | None = None,
                allow_missing_generation: bool = False, require_clean_audit: bool = False,
                accepted_restrictions=None) -> dict | None:
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
    check_generation(stage, listed, counts, rep, allow_missing_generation, require_clean_audit,
                     accepted_restrictions)

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


STATIC_MAX_FILE = 15_000_000      # shared hosts and phones: no single file above this


def check_static(site: Path, rep: Report, source: Path | None = None, cases: Path | None = None):
    """Gate a static build (scripts/build-static.py): manifest hashes, generation,
    every dataset complete (data, policy, metadata ro/en, pages), site files,
    and optionally the API parity cases (tools/static-engine/api-parity.mjs)."""
    import gzip
    print(f"== static build {site}")
    build_p = site / "build.json"
    if not build_p.exists():
        rep.fail("build.json missing"); return
    build = json.loads(build_p.read_text())
    gid = (build.get("generation") or {}).get("id")
    if not gid:
        rep.fail("build.json has no generation id")
    else:
        rep.ok(f"generation {gid[:12]} (commit {str(build.get('commit'))[:12]})")
    if source is not None:
        gm = source / "generation-manifest.json"
        want = json.loads(gm.read_text()).get("generation_id") if gm.exists() else None
        (rep.ok if want == gid else rep.fail)(f"generation equals the source corpus ({str(want)[:12]})")
    cfg = (site / "js" / "config.js").read_text() if (site / "js" / "config.js").exists() else ""
    (rep.ok if '"mode": "static"' in cfg and (not gid or gid in cfg) else rep.fail)(
        "js/config.js switches the pages to static mode for this generation")
    try:
        api = json.loads(cfg.split("window.TEMPO_CONFIG = ", 1)[1].rstrip().rstrip(";")).get("api_origin")
    except (IndexError, ValueError):
        api = None
    # what the Ask page will do: name the API it sends questions to, or say it has none (AQ-06A)
    if api and not (api.startswith("https://") and api.count("/") == 2):
        rep.fail(f"js/config.js api_origin {api!r} is not a bare https origin")
    else:
        rep.ok(f"Ask: questions go to {api} (it must list this site in TEMPO_CORS_ORIGINS)" if api
               else "Ask: none (no --api-origin; the Ask page says it is unavailable)")
    mp = site / "static-manifest.json"
    if not mp.exists():
        rep.fail("static-manifest.json missing"); return
    files = json.loads(mp.read_text())["files"]
    bad, big = [], []
    for rel, (h, size) in files.items():
        p = site / rel
        if not p.exists() or p.stat().st_size != size or sha256(p) != h:
            bad.append(rel)
        if size > STATIC_MAX_FILE:
            big.append(rel)
    extra = [str(p.relative_to(site)) for p in site.rglob("*")
             if p.is_file() and p.name != "static-manifest.json" and str(p.relative_to(site)) not in files]
    (rep.ok if not bad else rep.fail)(f"{len(files)} files match static-manifest.json"
                                      + (f" ({len(bad)} differ, e.g. {bad[:3]})" if bad else ""))
    (rep.ok if not extra else rep.fail)("no files outside the manifest" + (f": {extra[:3]}" if extra else ""))
    (rep.ok if not big else rep.fail)(f"no file over {STATIC_MAX_FILE // 1_000_000} MB" + (f": {big[:3]}" if big else ""))
    parts = set(build.get("partitioned") or [])
    missing = []
    for pol in sorted((site / "policy").glob("*.json.gz")):
        code = pol.name[:-len(".json.gz")]
        need = [f"data/{code}.index.json" if code in parts else f"data/{code}.bin.gz",
                f"rec/datasets/{code}.ro.json.gz", f"rec/datasets/{code}.en.json.gz",
                f"rec/insights/{code}.ro.json.gz", f"dataset/{code}/index.html", f"dataset/{code}/en.html"]
        missing += [n for n in need if n not in files]
    n_ds = len(list((site / "policy").glob("*.json.gz")))
    (rep.ok if not missing and n_ds == build.get("datasets") else rep.fail)(
        f"{n_ds} datasets complete (data, policy, metadata ro/en, insights, pages)"
        + (f"; missing {missing[:4]}" if missing else ""))
    for rel in (".htaccess", "robots.txt", "sitemap.xml", "llms.txt", "index.html", "dataset-v2.html",
                "rec/catalog.json.gz", "search/concepts.json.gz", "search/index.json.gz"):
        (rep.ok if rel in files else rep.fail)(f"{rel} present")
    idx = json.loads(gzip.decompress((site / "search" / "index.json.gz").read_bytes())) \
        if "search/index.json.gz" in files else {}
    (rep.ok if idx.get("mode") == "fts" else rep.warn)(
        f"full-text index exported (mode {idx.get('mode')}); otherwise search falls back to name matching")
    for rp in sorted(site.glob("rec/recipe/*/latest.ro.json.gz")):
        r = json.loads(gzip.decompress(rp.read_bytes()))
        (rep.ok if "__status" not in r else rep.fail)(f"recipe {rp.parent.name} recorded ({r.get('year')})")
    if cases is not None:
        node = shutil.which("node")
        if not node:
            rep.fail("node not installed: cannot run the API parity cases")
        else:
            r = subprocess.run([node, "--max-old-space-size=6000", str(ROOT / "tools/static-engine/api-parity.mjs"),
                                "--build", str(site), "--cases", str(cases)], capture_output=True, text=True)
            last = (r.stdout.strip().splitlines() or ["{}"])[-1]
            (rep.ok if r.returncode == 0 else rep.fail)(f"API parity: {last}")


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


# ------------------------------------------------------------------ candidate smoke (image or local)
# The site origin the separate-origin checks stand in for (the static site; AQ-06A)
SITE_ORIGIN = "https://site.example"
FOREIGN_ORIGIN = "https://foreign.example"


def mcp_run_env(port: int) -> dict:
    """Switches of the second smoke run: the public MCP on (local-test origin) and the
    production shape of a separately served site (page links and CORS on SITE_ORIGIN)."""
    return {"TEMPO_MCP_ENABLED": "true", "TEMPO_MCP_LOCAL_TEST": "true",
            "TEMPO_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
            "TEMPO_PUBLIC_SITE_URL": SITE_ORIGIN, "TEMPO_CORS_ORIGINS": SITE_ORIGIN}


def _wait_health(base: str, tries: int = 40, proc=None):
    import urllib.request
    for _ in range(tries):
        if proc is not None and proc.poll() is not None:
            return None
        try:
            return json.load(urllib.request.urlopen(base + "/api/health", timeout=3))
        except Exception:
            time.sleep(1)
    return None


def _http(url: str, method: str = "GET", data: bytes | None = None, headers: dict | None = None,
          timeout: float = 60):
    """(status, headers, body) without raising on an HTTP error status."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def web_checks(rep: Report, base: str, stage: Path, where: str):
    """The candidate with its default switches: FTS, the staged generation, the public MCP
    and Ask both off, a search and a data call. Returns a dataset code for the MCP run."""
    health = _wait_health(base, tries=1)
    if health["search"]["mode"] != "fts":
        rep.fail(f"{where} runs without FTS: {health['search']}")
    else:
        rep.ok(f"{where}: LOAD fts works offline, search mode fts")
    want = json.loads((stage / MANIFEST_NAME).read_text())["generation"]["id"]
    served = (health.get("generation") or {}).get("id")
    (rep.ok if served == want else rep.fail)(
        f"{where} serves the staged generation ({str(served)[:12]}, stage {want[:12]})")
    if (health.get("mcp") or {}).get("enabled") is not False:
        rep.fail(f"the public MCP must ship disabled by default: {health.get('mcp')}")
    st, _, _ = _http(base + "/mcp", "POST", b"{}", {"content-type": "application/json"})
    (rep.ok if st == 404 else rep.fail)(f"disabled /mcp answers {st} (expected 404)")
    st, _, body = _http(base + "/api/ask/config")
    cfg = json.loads(body) if st == 200 else {}
    (rep.ok if st == 200 and cfg.get("available") is False else rep.fail)(
        f"Ask ships off: /api/ask/config {st}, available={cfg.get('available')}")
    st, _, body = _http(base + "/api/datasets?q=population&limit=1")
    res = json.loads(body) if st == 200 else {}
    if res.get("search_mode") != "fts" or not res.get("datasets"):
        rep.fail(f"FTS query via {where} returned nothing/non-fts: {res.get('search_mode')}")
        return None
    code = res["datasets"][0]["matrix_code"]
    st, _, body = _http(f"{base}/api/datasets/{code}/data?limit=5")
    (rep.ok if st == 200 else rep.fail)(
        f"{where} serves FTS query and data endpoint ({code}, keys {sorted(json.loads(body))[:4] if st == 200 else st})")
    return code


def _sdk_session(base: str, steps):
    """Run `steps(session)` in the official MCP Python SDK client over Streamable HTTP."""
    import asyncio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def go():
        async with streamable_http_client(base + "/mcp") as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await steps(s)
    return asyncio.run(go())


def mcp_checks(rep: Report, base: str, code: str, where: str):
    """The public MCP on: the stdlib probe, the official SDK client, every reviewed recipe,
    generation-bound evidence, link origins and the separate-origin CORS policy."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import mcp_probe
    health = _wait_health(base, tries=1)
    if not (health or {}).get("mcp", {}).get("enabled"):
        rep.fail(f"{where} did not start with the MCP endpoint enabled: {health and health.get('mcp')}")
        return
    try:
        out = mcp_probe.probe(base, dataset=code)
        rep.ok(f"{where} serves the public MCP: {len(out['tools'])} tools, {code} describe -> "
               f"{out['call_status']}, structured == text fallback")
    except mcp_probe.ProbeError as e:
        rep.fail(f"MCP smoke failed: {e}")
        return
    st, _, body = _http(base + "/api/recipes")
    recipes = [r["id"] for r in json.loads(body)["recipes"]] if st == 200 else []

    async def steps(s):
        tools = [t.name for t in (await s.list_tools()).tools]
        runs = {rid: (await s.call_tool("run_recipe", {"recipe": rid})).structuredContent for rid in recipes}
        ok = [rid for rid, sc in runs.items() if sc["status"] == "ok"]
        ev = stale = None
        if ok:
            sc = runs[ok[0]]
            sel = {"kind": "recipe", "recipe": ok[0], "year": str(sc["data"]["year"])}
            gid = sc["provenance"]["generation"]["id"]
            ev = (await s.call_tool("get_evidence_links", {"selection": sel, "generation_id": gid})).structuredContent
            stale = (await s.call_tool("get_evidence_links", {"selection": sel, "generation_id": "0" * 12})).structuredContent
        return tools, runs, ok, ev, stale

    try:
        tools, runs, ok, ev, stale = _sdk_session(base, steps)
    except Exception as e:
        rep.fail(f"official MCP SDK client failed: {type(e).__name__}: {e}")
        return
    (rep.ok if tools == mcp_probe.EXPECTED else rep.fail)(f"official SDK client lists the {len(tools)} tools")
    for rid, sc in runs.items():
        if sc["status"] == "ok":
            rep.ok(f"MCP run_recipe {rid}: ok, year {sc['data']['year']}")
        else:   # a reviewed recipe the public profile refuses is a release limitation, not a crash
            rep.warn(f"MCP run_recipe {rid}: {sc['status']}/{sc.get('reason')} under the public profile")
    if not ok:
        rep.fail("no reviewed recipe runs through the public MCP")
        return
    links = {l["kind"]: l["url"] for l in (ev or {}).get("data", {}).get("links", [])}
    if ev is None or ev["status"] != "ok" or "evidence" not in links:
        rep.fail(f"get_evidence_links for {ok[0]}: {ev and (ev['status'], ev.get('reason'))}")
        return
    pages_on_site = links.get("dataset", "").startswith(SITE_ORIGIN + "/")
    api_on_base = all(links[k].startswith(base + "/api/") for k in ("live_selection", "evidence") if k in links)
    (rep.ok if pages_on_site and api_on_base else rep.fail)(
        f"evidence links: page on the site origin, API on the API origin ({links})")
    st, hdr, body = _http(links["evidence"], timeout=120)
    (rep.ok if st == 200 and "zip" in (hdr.get("content-type") or "") else rep.fail)(
        f"evidence bundle for {ok[0]} at the cited generation: {st}, {len(body)} bytes")
    gid = links["evidence"].rsplit("expected_generation=", 1)[1]
    st, _, _ = _http(links["evidence"].replace(gid, "0" * 12))
    (rep.ok if st == 409 else rep.fail)(f"evidence for another generation is refused: {st} (expected 409)")
    (rep.ok if stale and stale.get("reason") == "generation_changed" else rep.fail)(
        f"links for another generation: {stale and (stale['status'], stale.get('reason'))}")
    pre = {"access-control-request-method": "POST", "access-control-request-headers": "content-type"}
    st, hdr, _ = _http(base + "/api/ask", "OPTIONS", headers={"origin": SITE_ORIGIN, **pre})
    (rep.ok if st == 200 and hdr.get("access-control-allow-origin") == SITE_ORIGIN else rep.fail)(
        f"CORS: the listed site may call Ask ({st})")
    st, hdr, _ = _http(base + "/api/ask", "OPTIONS", headers={"origin": FOREIGN_ORIGIN, **pre})
    (rep.ok if "access-control-allow-origin" not in hdr else rep.fail)(f"CORS: another site is refused ({st})")
    st, hdr, _ = _http(base + "/mcp", "OPTIONS", headers={"origin": SITE_ORIGIN, **pre})
    (rep.ok if "access-control-allow-origin" not in hdr else rep.fail)(f"CORS never applies to /mcp ({st})")
    st, _, body = _http(base + "/api/ask/config")
    (rep.ok if st == 200 and json.loads(body).get("available") is False else rep.fail)(
        "Ask stays off while the MCP is on (no operator model calls)")


def fly_env() -> dict:
    """fly.toml [env]: the production switches the image runs with."""
    import tomllib
    return {k: str(v) for k, v in tomllib.loads((ROOT / "fly.toml").read_text()).get("env", {}).items()}


def _local_server(stage: Path, port: int, extra: dict, log: Path):
    """This checkout served like the image: the Dockerfile's uvicorn command (one worker) and
    fly.toml's [env], with the stage as the data dir. The caller's TEMPO_* switches and every
    *_API_KEY are dropped, so no model provider can be reached."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("TEMPO_") and not k.endswith("_API_KEY")}
    env.update(fly_env())
    env.update(TEMPO_DATA_DIR=str(stage.resolve()), **extra)
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"],
        cwd=ROOT, env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT)


def local_smoke(rep: Report, stage: Path, port: int):
    """The candidate checkout against the stage, without Docker: default switches, then the
    MCP run. Not an image, Linux or memory-limit result."""
    import tempfile
    print("== local candidate smoke (no image)")
    logs = Path(tempfile.mkdtemp(prefix="release-check-"))
    code = None
    for i, (extra, checks) in enumerate((({}, "default"), (mcp_run_env(port + 1), "mcp"))):
        p = port + i
        proc = _local_server(stage, p, extra, logs / f"{checks}.log")
        try:
            base = f"http://127.0.0.1:{p}"
            if not _wait_health(base, proc=proc):
                rep.fail(f"local candidate ({checks}) did not become healthy; log {logs / f'{checks}.log'}")
                return
            if checks == "default":
                code = web_checks(rep, base, stage, "local candidate")
                if not code:
                    return
            else:
                mcp_checks(rep, base, code, "local candidate")
        finally:
            proc.terminate()
            proc.wait(10)
    print(f"   server logs: {logs}")


def docker_smoke(rep: Report, stage: Path, port: int):
    print("== docker build + smoke")
    if stage.resolve() != (ROOT / "deploy-data").resolve():
        rep.fail(f"--docker builds the image from {ROOT / 'deploy-data'} (Dockerfile COPY), not {stage}: "
                 "stage the candidate there, or use --local")
        return
    if not shutil.which("docker") or subprocess.run(
            ["docker", "info"], capture_output=True).returncode != 0:
        rep.fail("docker unavailable (use CI/another host, or omit --docker)")
        return
    m = json.loads((stage / MANIFEST_NAME).read_text())
    tag = "tempo-release-check:" + m["generation"]["id"]
    if subprocess.run(["docker", "build", "-t", tag, "."], cwd=ROOT).returncode:
        rep.fail("docker build failed")
        return
    cid = subprocess.run(["docker", "run", "-d", "--rm", "-p", f"{port}:8080", tag],
                         capture_output=True, text=True).stdout.strip()
    try:
        base = f"http://127.0.0.1:{port}"
        if not _wait_health(base):
            rep.fail("container did not become healthy")
            return
        code = web_checks(rep, base, stage, "image")
    finally:
        subprocess.run(["docker", "stop", cid], capture_output=True)
    if not code:
        return tag
    env = [x for k, v in mcp_run_env(port + 1).items() for x in ("-e", f"{k}={v}")]
    cid = subprocess.run(["docker", "run", "-d", "--rm", "-p", f"{port + 1}:8080", *env, tag],
                         capture_output=True, text=True).stdout.strip()
    try:
        base = f"http://127.0.0.1:{port + 1}"
        if not _wait_health(base):
            rep.fail("MCP container did not become healthy")
        else:
            mcp_checks(rep, base, code, "image")
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
    ap.add_argument("--accept-restriction", action="append", default=[], metavar="VIOLATION",
                    help="treat an audit violation as an accepted, app-enforced restriction "
                         f"(supported: {', '.join(ENFORCED_RESTRICTIONS)}); listed in the result")
    ap.add_argument("--docker", action="store_true", help="build image and smoke it")
    ap.add_argument("--local", action="store_true",
                    help="smoke this checkout against --stage with the image's command and fly.toml "
                         "env, without Docker (not an image or memory-limit result)")
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--deploy", action="store_true",
                    help="run `fly deploy` after ALL gates pass (never implicit)")
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--static", metavar="DIR",
                    help="gate a static build (scripts/build-static.py) instead of the Docker stage")
    ap.add_argument("--api-cases", metavar="JSONL",
                    help="with --static: replay these scripts/gen-api-cases.py cases")
    a = ap.parse_args()

    if a.cmd == "snapshot":
        print(json.dumps(snapshot(Path(a.corpus)), sort_keys=True)); return
    if a.cmd == "manifest":
        cmd_manifest(Path(a.stage), Path(a.corpus)); return
    stage = Path(a.stage)
    if a.rollback:
        cmd_rollback(stage); return

    if a.static:
        rep = Report()
        check_static(Path(a.static), rep, Path(a.source) if a.source else None,
                     Path(a.api_cases) if a.api_cases else None)
        if not a.skip_tests:
            run_tests(rep)
        print("\n== result")
        for w in rep.warnings:
            print(f"  warn: {w}")
        if rep.failures:
            print(f"STATIC RELEASE BLOCKED ({len(rep.failures)} failure(s))")
            for f in rep.failures:
                print(f"  - {f}")
            sys.exit(1)
        print("STATIC RELEASE CHECK PASSED (not deploying: see scripts/deploy-static.sh)")
        return

    rep = Report()
    check_stage(stage, rep, Path(a.source) if a.source else None,
                a.allow_missing_generation, a.require_clean_audit, a.accept_restriction)
    if not a.skip_tests:
        run_tests(rep)
    if a.local and not rep.failures:
        local_smoke(rep, stage, a.port)
    if a.docker and not rep.failures:
        docker_smoke(rep, stage, a.port)
    print("\n== result")
    for r in rep.restrictions:
        print(f"  restriction: {r['violation']} ({r['files']} files) enforced by {r['enforcer']}")
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
