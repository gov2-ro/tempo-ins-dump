#!/usr/bin/env python3
"""
Build the generation manifest (FIX-03 "Artifact and repair policy") for one corpus.

READ-ONLY on the corpus (DuckDB opened read_only, parquets only read). The only
write is the explicit --out file.

A generation is the set {metadata.duckdb, parquet/*.parquet, view-profiles/*.json,
search.duckdb}. The manifest ties them together:

  schema, kind, generation_id   sha256 over the component digests (below)
  built_at                      --built-at, else mtime of the DB (NOT part of the id)
  db                            file sha256/size + row count of every main-schema table
  parquet                       count, digest, by_category and per-file
                                {sha256, size, rows, category, schema}
  view_profiles                 count + digest (sha256 over sorted name:sha256 lines)
  search_index                  sha256/size, or null when search.duckdb is absent
  provenance                    max/min ultima_actualizare, matrices with a date
  audit                         audit summary counts, strict violation counts and the
                                violating codes (what `audit-corpus.py --strict` flags)

generation_id = sha256 of the canonical JSON of
  {db_sha256, parquet_digest, view_profiles_digest, search_sha256}
so the id changes iff any artifact byte changes. Output is deterministic.

Usage: python scripts/build-generation-manifest.py --out FILE [--data-dir DIR]
       [--built-at ISO] [--no-grain]
`scripts/release-check.py` verifies a staged copy against this file.
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent
SCHEMA = 1
KIND = "generation-manifest"


def _load_audit():
    spec = importlib.util.spec_from_file_location("audit_corpus", REPO / "scripts" / "audit-corpus.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_lines(pairs) -> str:
    """sha256 over sorted 'name:sha256' lines (same recipe is used by release-check)."""
    return hashlib.sha256("\n".join(f"{n}:{s}" for n, s in sorted(pairs)).encode()).hexdigest()


def compute_generation_id(db_sha, parquet_digest, vp_digest, search_sha) -> str:
    blob = json.dumps({"db_sha256": db_sha, "parquet_digest": parquet_digest,
                       "view_profiles_digest": vp_digest, "search_sha256": search_sha},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def db_info(db_file: Path) -> dict:
    conn = duckdb.connect(str(db_file), read_only=True)
    try:
        tables = sorted(r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main' "
            "AND table_type='BASE TABLE'").fetchall())
        counts = {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        prov = {"latest_observation_date": None, "earliest_observation_date": None, "matrices_with_date": 0}
        if "matrices" in counts:
            try:
                mx, mn, n = conn.execute(
                    "SELECT max(ultima_actualizare), min(ultima_actualizare), count(ultima_actualizare) "
                    "FROM matrices").fetchone()
                prov = {"latest_observation_date": str(mx) if mx is not None else None,
                        "earliest_observation_date": str(mn) if mn is not None else None,
                        "matrices_with_date": n}
            except Exception:
                pass
    finally:
        conn.close()
    return {"row_counts": counts, "provenance": prov}


def build(data_dir: Path, do_grain=True, built_at=None) -> dict:
    audit = _load_audit()
    corpus = data_dir / "corpus"
    db_file, search_file, vp_dir = corpus / "metadata.duckdb", corpus / "search.duckdb", corpus / "view-profiles"
    if not db_file.exists():
        raise SystemExit(f"metadata.duckdb not found in {corpus}")
    rep = audit.audit(data_dir, do_grain=do_grain, do_hashes=True)

    db_sha = sha256_file(db_file)
    di = db_info(db_file)
    search_sha = sha256_file(search_file) if search_file.exists() else None

    files = {}
    for code, r in sorted(rep["files"].items()):
        files[code] = {"sha256": r["sha256"], "size": r["size"], "rows": r.get("rows"),
                       "category": r["category"], "schema": r.get("schema")}
    parquet_digest = digest_lines((c + ".parquet", f["sha256"]) for c, f in files.items())
    by_cat = {c: sum(1 for f in files.values() if f["category"] == c) for c in audit.FILE_CATEGORIES}

    vp = [(p.name, sha256_file(p)) for p in vp_dir.glob("*.json")] if vp_dir.exists() else []
    vp_digest = digest_lines(vp)

    if built_at is None:
        built_at = datetime.fromtimestamp(db_file.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")

    s = rep["summary"]
    return {
        "schema": SCHEMA, "kind": KIND,
        "generation_id": compute_generation_id(db_sha, parquet_digest, vp_digest, search_sha),
        "built_at": built_at,
        "db": {"file": "metadata.duckdb", "sha256": db_sha, "size": db_file.stat().st_size,
               "row_counts": di["row_counts"]},
        "parquet": {"count": len(files), "digest": parquet_digest, "by_category": by_cat, "files": files},
        "view_profiles": {"count": len(vp), "digest": vp_digest},
        "search_index": ({"file": "search.duckdb", "sha256": search_sha, "size": search_file.stat().st_size}
                         if search_sha else None),
        "provenance": di["provenance"],
        "audit": {
            "grain_checked": do_grain,
            "warnings": rep["warnings"],
            "summary": {k: s[k] for k in ("parquet_files", "matrices_rows", "split_registrations",
                                          "files_by_category", "metadata_only_by_category",
                                          "findings_counts", "registration_issue_counts",
                                          "schema_shapes")},
            "violation_counts": s["violation_counts"],
            "violations": rep["violations"],
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build generation-manifest.json (read-only on the corpus)")
    ap.add_argument("--data-dir", default=str(REPO / "data"))
    ap.add_argument("--out", required=True, help="where to write the manifest (explicit; never defaulted)")
    ap.add_argument("--built-at", help="ISO timestamp recorded as built_at (default: DB mtime)")
    ap.add_argument("--no-grain", action="store_true", help="skip grain checks (conflicting_grain not reported)")
    a = ap.parse_args(argv)
    data_dir = Path(a.data_dir).resolve()
    out = Path(a.out).resolve()
    if (data_dir / "corpus") in out.parents:
        ap.error("--out must not be inside the audited corpus/ (copy it in when publishing a generation)")
    m = build(data_dir, do_grain=not a.no_grain, built_at=a.built_at)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(m, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"generation {m['generation_id'][:16]}  parquet={m['parquet']['count']} "
          f"vp={m['view_profiles']['count']}  violations={m['audit']['violation_counts']}  -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
