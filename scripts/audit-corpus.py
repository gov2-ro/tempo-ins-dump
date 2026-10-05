#!/usr/bin/env python3
"""
Deterministic, READ-ONLY audit of the data corpus (FIX-03).

Cross-references the parquet files in <data-dir>/corpus/parquet, the DuckDB
metadata (<data-dir>/corpus/metadata.duckdb, opened read_only) and the view
profiles (<data-dir>/corpus/view-profiles). Never writes inside the data dir;
the only output is stdout and, optionally, --json-out.

File categories (mutually exclusive, first match wins)
  invalid              unreadable, no value column, or zero rows
  registered_split     stem is a sub_matrix_code in dataset_splits
  served_canonical     matrices row with is_canonical = TRUE (not a split child)
  noncanonical_parent  matrices row with is_canonical = FALSE (e.g. a split parent)
  leftover             no matrices row and no dataset_splits row

Metadata-only entries (matrices / dataset_splits rows without a parquet file)
  intentional_unavailable   matrices row with is_canonical = FALSE (nothing is served)
  invalid                   a row that should be served (canonical matrix or
                            registered split) but has no readable file

Per-file checks (readable files): schema shape (sdmx | legacy | unknown), NULL
dimension values, TIME_PERIOD validity, grain uniqueness (repeated dimension keys,
and keys repeated with *differing* values), registration consistency (path / row
count), mapping and profile coverage. Findings are listed per code, not hidden
behind numeric allowlists; judging them against the serving contract is a
separate step.

Usage
  python scripts/audit-corpus.py [--data-dir DIR] [--json-out FILE] [--hashes]
                                 [--no-grain] [--full] [--strict] [--limit N]
Deterministic: output depends only on the inputs (no timestamps, sorted keys).
Exit code: 0, or 1 with --strict when a served/registered file has a violation.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent

# What stage 9 / sdmx_labels.parse_time_period can emit: 2020, 2020-Q1, 2020-S1,
# 2020-03, 2020-03-15, 2020-P5Y, 2020-D2.
TIME_RE = r"^\d{4}(-(Q[1-4]|S[12]|D[0-9]+|P[0-9]+Y|(0[1-9]|1[0-2])(-[0-9]{2})?))?$"
INVALID_TIME_SHARE = 0.20  # same threshold as the 2026-10 audit baseline

FILE_CATEGORIES = ["served_canonical", "noncanonical_parent", "registered_split", "leftover", "invalid"]
META_CATEGORIES = ["intentional_unavailable", "invalid"]
PROFILE_TABLES = {
    "column_map": "sdmx_column_map",
    "matrix_profile": "matrix_profiles",
    "dimension_structure": "dimension_structure",
    "coverage": "dataset_coverage",
    "value_profile": "dataset_value_profiles",
    "trend": "dataset_trends",
}


def q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- DB
def load_db(db_file: Path, warnings: list):
    """Return dict of registration/coverage sets read from the metadata DB."""
    out = {"matrices": {}, "splits": [], "coverage": {k: set() for k in PROFILE_TABLES}}
    if not db_file.exists():
        warnings.append(f"metadata DB not found: {db_file}")
        return out
    conn = duckdb.connect(str(db_file), read_only=True)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}

        def has_cols(t, cols):
            have = {r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name=?", [t]).fetchall()}
            return [c for c in cols if c in have]

        if "matrices" in tables:
            want = ["matrix_code", "is_canonical", "is_split", "parent_matrix_code",
                    "parquet_path", "row_count", "ultima_actualizare"]
            cols = has_cols("matrices", want)
            for row in conn.execute(f"SELECT {', '.join(cols)} FROM matrices ORDER BY matrix_code").fetchall():
                rec = dict(zip(cols, row))
                if rec.get("ultima_actualizare") is not None:
                    rec["ultima_actualizare"] = str(rec["ultima_actualizare"])
                out["matrices"][rec["matrix_code"]] = rec
        else:
            warnings.append("table matrices missing")
        if "dataset_splits" in tables:
            out["splits"] = conn.execute(
                "SELECT parent_matrix_code, sub_matrix_code, parquet_path, row_count "
                "FROM dataset_splits ORDER BY sub_matrix_code, parent_matrix_code").fetchall()
        else:
            warnings.append("table dataset_splits missing")
        for key, t in PROFILE_TABLES.items():
            if t in tables:
                out["coverage"][key] = {r[0] for r in conn.execute(
                    f"SELECT DISTINCT matrix_code FROM {t}").fetchall()}
            else:
                warnings.append(f"table {t} missing (coverage '{key}' counted as empty)")
    finally:
        conn.close()
    return out


# ------------------------------------------------------------------ per file
def inspect_parquet(pconn, path: Path, do_grain: bool) -> dict:
    """Read-only structural checks of one parquet file."""
    info = {"readable": True, "size": path.stat().st_size}
    try:
        cols = [(r[0], r[1]) for r in pconn.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()]
    except Exception as e:
        return {**info, "readable": False, "error": str(e).splitlines()[0][:200]}
    names = [c for c, _ in cols]
    info["columns"] = names
    if "OBS_VALUE" in names:
        value_col, info["schema"] = "OBS_VALUE", "sdmx"
    elif "value" in names and any(c.endswith("_nom_id") for c in names):
        value_col, info["schema"] = "value", "legacy"
    else:
        value_col, info["schema"] = None, "unknown"
    dims = [c for c in names if c != value_col]
    info["n_dims"] = len(dims)
    try:
        exprs = ["count(*)"]
        exprs += [f"count(*) FILTER (WHERE {q(c)} IS NULL)" for c in dims]
        has_time = "TIME_PERIOD" in names
        if has_time:
            exprs.append(f"count(*) FILTER (WHERE TIME_PERIOD IS NOT NULL AND "
                         f"NOT regexp_matches(CAST(TIME_PERIOD AS VARCHAR), '{TIME_RE}'))")
        if value_col:
            exprs.append(f"count({q(value_col)})")
        row = pconn.execute(f"SELECT {', '.join(exprs)} FROM read_parquet(?)", [str(path)]).fetchone()
        info["rows"] = row[0]
        nulls = {c: row[1 + i] for i, c in enumerate(dims) if row[1 + i]}
        info["null_dims"] = nulls
        i = 1 + len(dims)
        if has_time:
            info["time_invalid"] = row[i]
            info["time_invalid_share"] = round(row[i] / row[0], 4) if row[0] else 0.0
            i += 1
        else:
            info["time_invalid"] = None
        if value_col:
            info["values_non_null"] = row[i]
        if do_grain and value_col and dims and row[0]:
            key = ", ".join(q(c) for c in dims)
            g = pconn.execute(
                f"SELECT count(*), coalesce(sum(c), 0), count(*) FILTER (WHERE d > 1) FROM ("
                f"SELECT count(*) c, count(DISTINCT {q(value_col)}) d FROM read_parquet(?) "
                f"GROUP BY {key} HAVING count(*) > 1)", [str(path)]).fetchone()
            info["dup_keys"], info["dup_rows"], info["conflicting_keys"] = int(g[0]), int(g[1]), int(g[2])
        else:
            info["dup_keys"] = info["dup_rows"] = info["conflicting_keys"] = None
    except Exception as e:
        info.update(readable=False, error=str(e).splitlines()[0][:200])
    return info


def audit(data_dir: Path, do_grain=True, do_hashes=False, limit=None) -> dict:
    warnings: list[str] = []
    corpus = data_dir / "corpus"
    parquet_dir = corpus / "parquet"
    vp_dir = corpus / "view-profiles"

    db = load_db(corpus / "metadata.duckdb", warnings)
    matrices = db["matrices"]
    parent_of: dict[str, list[str]] = {}
    for parent, sub, _, _ in db["splits"]:
        parent_of.setdefault(sub, []).append(parent)
    split_subs = set(parent_of)
    split_parents = {p for ps in parent_of.values() for p in ps}

    files = sorted(parquet_dir.glob("*.parquet")) if parquet_dir.exists() else []
    if not parquet_dir.exists():
        warnings.append(f"parquet dir not found: {parquet_dir}")
    if limit:
        files = files[:limit]
    stems = {f.stem for f in files}
    vp_codes = {f.stem for f in vp_dir.glob("*.json") if not f.name.startswith("_")} if vp_dir.exists() else set()
    if not vp_dir.exists():
        warnings.append(f"view-profiles dir not found: {vp_dir}")

    pconn = duckdb.connect()  # in-memory; reads parquet only
    records: dict[str, dict] = {}
    for f in files:
        code = f.stem
        info = inspect_parquet(pconn, f, do_grain)
        if do_hashes:
            info["sha256"] = sha256(f)
        reason = None
        if not info["readable"]:
            reason = "unreadable: " + info.get("error", "")
        elif info["schema"] == "unknown":
            reason = "no OBS_VALUE/value column"
        elif info.get("rows") == 0:
            reason = "zero rows"
        m = matrices.get(code)
        if reason:
            cat = "invalid"
        elif code in split_subs:
            cat = "registered_split"
        elif m is not None:
            cat = "served_canonical" if m.get("is_canonical") else "noncanonical_parent"
        else:
            cat = "leftover"
        info["category"] = cat
        if reason:
            info["invalid_reason"] = reason
        info["registered_in_matrices"] = m is not None
        info["registered_split_of"] = sorted(parent_of.get(code, []))
        if m is not None:
            info["source_update"] = m.get("ultima_actualizare")
        records[code] = info
    pconn.close()

    # ---- metadata-only entries -------------------------------------------
    meta_only: dict[str, dict] = {}
    for code, m in matrices.items():
        if code in stems:
            continue
        if code in split_subs:
            meta_only[code] = {"category": "invalid", "reason": "registered split without parquet",
                               "parents": sorted(parent_of[code])}
        elif m.get("is_canonical"):
            meta_only[code] = {"category": "invalid", "reason": "canonical matrix without parquet"}
        else:
            why = "split parent (children served instead)" if code in split_parents else "noncanonical, not served"
            meta_only[code] = {"category": "intentional_unavailable", "reason": why}
    for parent, sub, _, _ in db["splits"]:
        if sub not in matrices and sub not in stems and sub not in meta_only:
            meta_only[sub] = {"category": "invalid", "reason": "split registered, no matrices row and no parquet",
                              "parents": [parent]}

    if limit:
        meta_only = {}  # a partial file scan cannot tell which entries lack a file

    # ---- aggregates --------------------------------------------------------
    def by_cat(recs, cats):
        return {c: sum(1 for r in recs.values() if r["category"] == c) for c in cats}

    served_cats = ("served_canonical", "registered_split")
    served = {c: r for c, r in records.items() if r["category"] in served_cats}
    readable = {c: r for c, r in records.items() if r["readable"]}

    def codes(pred, src=None):
        return sorted(c for c, r in (src if src is not None else readable).items() if pred(r))

    findings = {
        "null_dims": codes(lambda r: bool(r.get("null_dims"))),
        "time_invalid_gt_20pct": codes(lambda r: (r.get("time_invalid_share") or 0) > INVALID_TIME_SHARE),
        "time_any_invalid": codes(lambda r: (r.get("time_invalid") or 0) > 0),
        "no_time_period_column": codes(lambda r: "TIME_PERIOD" not in r["columns"]),
        "legacy_shape": codes(lambda r: r["schema"] == "legacy"),
        "duplicate_grain": codes(lambda r: (r.get("dup_keys") or 0) > 0),
        "conflicting_grain": codes(lambda r: (r.get("conflicting_keys") or 0) > 0),
        "unreadable": sorted(c for c, r in records.items() if not r["readable"]),
    }

    # registration consistency
    reg_issues: dict[str, list] = {
        "path_mismatch": [], "row_count_mismatch": [], "split_row_count_mismatch": [],
        "duplicate_split_registrations": [], "recursive_splits": [],
        "split_parent_not_in_matrices": [], "split_sub_not_flagged_split": [],
    }
    for code, r in records.items():
        m = matrices.get(code)
        if m and m.get("parquet_path") and Path(str(m["parquet_path"])).name != f"{code}.parquet":
            reg_issues["path_mismatch"].append(code)
        if m and r.get("rows") is not None and m.get("row_count") is not None and m["row_count"] != r["rows"]:
            reg_issues["row_count_mismatch"].append(code)
    sub_counts: dict[str, int] = {}
    for parent, sub, _, rc in db["splits"]:
        sub_counts[sub] = sub_counts.get(sub, 0) + 1
        r = records.get(sub)
        if r and r.get("rows") is not None and rc is not None and rc != r["rows"]:
            reg_issues["split_row_count_mismatch"].append(sub)
        if parent not in matrices:
            reg_issues["split_parent_not_in_matrices"].append(sub)
        if sub in split_parents:
            reg_issues["recursive_splits"].append(sub)
        if sub in matrices and not matrices[sub].get("is_split"):
            reg_issues["split_sub_not_flagged_split"].append(sub)
    reg_issues["duplicate_split_registrations"] = sorted(c for c, n in sub_counts.items() if n > 1)
    reg_issues = {k: sorted(set(v)) for k, v in reg_issues.items()}

    # profile / mapping coverage (denominator: files that should be served)
    coverage = {}
    for key, have in db["coverage"].items():
        missing = sorted(c for c in served if c not in have)
        coverage[key] = {"served_total": len(served), "served_with": len(served) - len(missing),
                         "served_missing": missing}
    vp_missing_all = sorted(c for c in records if c not in vp_codes)
    vp_missing_served = sorted(c for c in served if c not in vp_codes)
    vp_orphans = sorted(c for c in vp_codes if c not in stems)
    view_profiles = {
        "dir": str(vp_dir), "total": len(vp_codes),
        "parquets_without_profile_all": len(vp_missing_all),
        "parquets_without_profile_served": len(vp_missing_served),
        "served_without_profile": vp_missing_served,
        "profiles_without_parquet": vp_orphans,
        "profiles_for_nonserved_files": sorted(c for c in vp_codes if c in records and c not in served),
    }

    # served violations: the gate FIX-03 wants at zero (or explained)
    violations = {
        "invalid": sorted(c for c, r in records.items()
                          if r["category"] == "invalid" and (c in matrices or c in split_subs)),
        "null_dims": [c for c in findings["null_dims"] if c in served],
        "time_invalid_gt_20pct": [c for c in findings["time_invalid_gt_20pct"] if c in served],
        "conflicting_grain": [c for c in findings["conflicting_grain"] if c in served],
        "metadata_only_should_be_served": sorted(c for c, v in meta_only.items() if v["category"] == "invalid"),
    }

    summary = {
        "parquet_files": len(files),
        "readable_parquets": len(readable),
        "matrices_rows": len(matrices),
        "split_registrations": len(db["splits"]),
        "distinct_split_children": len(split_subs),
        "files_by_category": by_cat(records, FILE_CATEGORIES),
        "metadata_only_by_category": by_cat(meta_only, META_CATEGORIES),
        "files_without_matrices_row": sum(1 for c in records if c not in matrices),
        "matrices_without_file": len(meta_only) if not limit else None,
        "findings_counts": {k: len(v) for k, v in findings.items()},
        "registration_issue_counts": {k: len(v) for k, v in reg_issues.items()},
        "violation_counts": {k: len(v) for k, v in violations.items()},
        "view_profiles_total": len(vp_codes),
        "parquets_without_view_profile": len(vp_missing_all),
        "profiles_without_parquet": len(vp_orphans),
        "schema_shapes": {s: sum(1 for r in readable.values() if r["schema"] == s)
                          for s in ("sdmx", "legacy", "unknown")},
    }
    return {
        "data_dir": str(data_dir), "options": {"grain": do_grain, "hashes": do_hashes, "limit": limit},
        "warnings": warnings, "summary": summary, "findings": findings,
        "registration_issues": reg_issues, "coverage": coverage, "view_profiles": view_profiles,
        "violations": violations, "metadata_only": meta_only, "files": records,
    }


# ------------------------------------------------------------------ output
def render_human(rep: dict) -> str:
    s = rep["summary"]
    L = ["=" * 66, "  CORPUS AUDIT (read-only)", "=" * 66, f"  data dir: {rep['data_dir']}"]
    for w in rep["warnings"]:
        L.append(f"  WARNING: {w}")
    L += ["", f"  parquet files: {s['parquet_files']}   readable: {s['readable_parquets']}   "
              f"matrices rows: {s['matrices_rows']}",
          f"  split registrations: {s['split_registrations']}   distinct children: {s['distinct_split_children']}",
          f"  schema shapes: {s['schema_shapes']}", "", "  Files by category:"]
    for c in FILE_CATEGORIES:
        L.append(f"    {c:<22}{s['files_by_category'][c]:>6}")
    L += [f"    (files without matrices row: {s['files_without_matrices_row']})", "",
          "  Metadata-only entries (no parquet):"]
    for c in META_CATEGORIES:
        L.append(f"    {c:<24}{s['metadata_only_by_category'][c]:>6}")
    L += ["", "  Findings (readable files):"]
    for k, n in s["findings_counts"].items():
        L.append(f"    {k:<26}{n:>6}")
    L += ["", "  Registration issues:"]
    for k, n in s["registration_issue_counts"].items():
        L.append(f"    {k:<32}{n:>6}")
    L += ["", "  Coverage of served files (canonical + registered splits):"]
    for k, v in rep["coverage"].items():
        L.append(f"    {k:<22}{v['served_with']:>6} / {v['served_total']}")
    vp = rep["view_profiles"]
    L += ["", f"  View profiles ({vp['dir']}): {vp['total']}",
          f"    parquets without profile: {vp['parquets_without_profile_all']} "
          f"(of which served: {vp['parquets_without_profile_served']})",
          f"    profiles without parquet: {len(vp['profiles_without_parquet'])}",
          "", "  Served violations (to be zero or explained):"]
    for k, n in s["violation_counts"].items():
        L.append(f"    {k:<32}{n:>6}")
    L.append("=" * 66)
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only deterministic corpus audit (FIX-03)")
    ap.add_argument("--data-dir", default=str(REPO / "data"),
                    help="data directory containing corpus/ (default: <repo>/data)")
    ap.add_argument("--json-out", help="write the JSON report here (never inside the audited corpus/)")
    ap.add_argument("--hashes", action="store_true", help="include sha256 per parquet (slower)")
    ap.add_argument("--no-grain", action="store_true", help="skip the (heavier) grain uniqueness check")
    ap.add_argument("--full", action="store_true", help="keep per-file records in the JSON (default: summary + lists)")
    ap.add_argument("--limit", type=int, help="audit only the first N parquet files (debug)")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any served/registered file has a violation")
    ap.add_argument("--quiet", action="store_true", help="no human summary")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir).resolve()
    if args.json_out:
        out = Path(args.json_out).resolve()
        if (data_dir / "corpus") in out.parents:
            ap.error("--json-out must not be inside the audited corpus/ directory")
    rep = audit(data_dir, do_grain=not args.no_grain, do_hashes=args.hashes, limit=args.limit)
    if not args.quiet:
        print(render_human(rep))
    if args.json_out:
        slim = rep if args.full else {k: v for k, v in rep.items() if k != "files"}
        Path(args.json_out).write_text(json.dumps(slim, indent=2, sort_keys=True, default=str), encoding="utf-8")
        if not args.quiet:
            print(f"  JSON report: {args.json_out}")
    if args.strict and any(rep["violations"].values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
