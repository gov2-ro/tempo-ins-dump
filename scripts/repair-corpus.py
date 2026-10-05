#!/usr/bin/env python3
"""
Corpus repair planner (FIX-03). DRY-RUN BY DEFAULT; never writes in place.

Reads the corpus (DuckDB read_only, parquet read-only, raw metas/CSVs/logs
read-only) and produces a repair plan with four sections:

  quarantine          leftover / zero-row parquets that no matrices or
                      dataset_splits row refers to: file, sha256, rows, reason.
  metadata_only       served-but-fileless matrices, explained from data/2-metas,
                      data/4-datasets and the fetch log (empty at source, CSV never
                      fetched, fetch failure, conversion failure, ...).
  time_misclassified  served files whose TIME_PERIOD is >20% invalid, classified
                      by sampled values with a *proposed* column remap. Report only;
                      free text is never reinterpreted as a date.
  conflicting_grain   served files with the same dimension key carrying differing
                      values, classified per the FIX-03 county-split policy using
                      aggregation_policy additivity. Report only.

--apply --target-dir DIR performs ONLY the quarantine step, and only on an explicit
COPY of the corpus: files are moved from <DIR>/corpus/parquet/ to <DIR>/quarantine/
together with quarantine-manifest.json. It refuses when DIR (or any file it would
move) resolves inside the source data dir, so it can never act in place or through a
symlink to the real corpus. There is no publish step in this phase.

Usage
  python scripts/repair-corpus.py [--data-dir DIR] [--report-json F] [--report-md F]
                                  [--audit-json F] [--no-grain]
  python scripts/repair-corpus.py --apply --target-dir COPY_DIR [--data-dir DIR]
Report files must not be inside <data-dir>/corpus.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _load_audit():
    spec = importlib.util.spec_from_file_location("audit_corpus", REPO / "scripts" / "audit-corpus.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _strip(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inside(path: Path, root: Path) -> bool:
    path, root = path.resolve(), root.resolve()
    return path == root or root in path.parents


# ------------------------------------------------------------------ quarantine
def plan_quarantine(rep: dict, matrices: dict, split_subs: set) -> dict:
    """Leftovers + unregistered zero-row/unreadable files. Registered files never qualify."""
    items = []
    known = set(matrices)
    for code, r in sorted(rep["files"].items()):
        if code in known or code in split_subs:
            continue
        if r["category"] not in ("leftover", "invalid"):
            continue
        if r["category"] == "invalid":
            reason = f"invalid, unregistered: {r.get('invalid_reason', 'unknown')}"
        else:
            reason = "leftover: no matrices row and no dataset_splits row"
        # nearest registered ancestor by '_' prefix, to make triage easier
        parts = code.split("_")
        related = next(("_".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)
                        if "_".join(parts[:i]) in known), None)
        if related and r["category"] == "leftover":
            reason += f" (name derives from registered {related}: likely stale split/rename)"
        items.append({"file": f"{code}.parquet", "code": code, "sha256": r.get("sha256"), "size": r["size"],
                      "rows": r.get("rows"), "category": r["category"], "reason": reason,
                      "related_registered": related})
    by_cat = {}
    for i in items:
        by_cat[i["category"]] = by_cat.get(i["category"], 0) + 1
    return {"count": len(items), "by_category": by_cat, "files": items}


def apply_quarantine(plan: dict, data_dir: Path, target: Path) -> dict:
    """Move planned files inside an explicit COPY. Refuses anything touching the source."""
    src_corpus = data_dir / "corpus"
    if inside(target, src_corpus) or inside(src_corpus, target) or target.resolve() == data_dir.resolve():
        raise SystemExit(f"refusing: --target-dir {target} overlaps the source corpus {src_corpus} "
                         "(--apply only works on a separate copy)")
    pq = target / "corpus" / "parquet"
    if not pq.is_dir():
        raise SystemExit(f"refusing: {pq} not found; --target-dir must be a copy of the data dir")
    if inside(pq, src_corpus):
        raise SystemExit("refusing: target parquet dir resolves into the source corpus")
    qdir = target / "quarantine"
    if qdir.exists() and any(qdir.iterdir()):
        raise SystemExit(f"refusing: {qdir} already exists and is not empty")
    # verify everything before moving anything
    for it in plan["files"]:
        p = pq / it["file"]
        if not p.is_file():
            raise SystemExit(f"refusing: planned file missing in copy: {p}")
        if inside(p, src_corpus):
            raise SystemExit(f"refusing: {p} resolves into the source corpus (symlink?)")
        if sha256_file(p) != it["sha256"]:
            raise SystemExit(f"refusing: hash of {p} differs from the plan (copy is not the audited generation)")
    qdir.mkdir(parents=True)
    moved = []
    for it in plan["files"]:
        shutil.move(str(pq / it["file"]), str(qdir / it["file"]))
        moved.append({k: it[k] for k in ("file", "sha256", "size", "rows", "category", "reason")})
    manifest = {"kind": "quarantine-manifest", "schema": 1, "source_data_dir": str(data_dir),
                "count": len(moved), "files": moved}
    (qdir / "quarantine-manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return {"moved": len(moved), "quarantine_dir": str(qdir)}


# ------------------------------------------------------------------ metadata-only
def _log_hits(log_files, codes):
    hits = {c: [] for c in codes}
    for lf in log_files:
        try:
            for line in open(lf, errors="replace"):
                for c in codes:
                    if f"{c}.csv" in line or f" {c} " in line or f"{c}:" in line:
                        hits[c].append((Path(lf).name, line.strip()[:220]))
        except OSError:
            pass
    return hits


def explain_metadata_only(rep: dict, data_dir: Path, lang="ro") -> dict:
    codes = sorted(c for c, v in rep["metadata_only"].items() if v["category"] == "invalid")
    metas, csvs, logs = data_dir / "2-metas" / lang, data_dir / "4-datasets" / lang, data_dir / "logs"
    log_files = sorted(logs.glob("fetch-csv*.log")) + sorted(logs.glob("*conversion*.log"))
    hits = _log_hits(log_files, codes)
    out = {}
    for c in codes:
        mp, cp = metas / f"{c}.json", csvs / f"{c}.csv"
        ev = {"reason_in_audit": rep["metadata_only"][c]["reason"], "meta_json": mp.is_file(),
              "csv_exists": cp.is_file()}
        fetch_hits = [h for h in hits[c] if h[0].startswith("fetch-csv")]
        conv_hits = [h for h in hits[c] if "conversion" in h[0]]
        empty_hits = [h for h in fetch_hits if "Empty dataset" in h[1] or "no data" in h[1] or "FAIL" in h[1]]
        err_hits = [h for h in fetch_hits if re.search(r"ERROR|Traceback|HTTP \d{3}|timeout|FAILED", h[1], re.I)
                    and h not in empty_hits]
        if mp.is_file():
            try:
                j = json.loads(mp.read_text())
                ev["matrixName"] = j.get("matrixName")
                ev["meta_ultimaActualizare"] = j.get("ultimaActualizare")
            except Exception as e:
                ev["meta_unreadable"] = str(e)[:100]
        if cp.is_file():
            n = sum(1 for _ in open(cp, errors="replace"))
            ev["csv_lines"], ev["csv_bytes"] = n, cp.stat().st_size
        ev["fetch_log_empty_dataset_hits"] = len(empty_hits)
        ev["fetch_log_error_hits"] = len(err_hits)
        ev["conversion_log_hits"] = len(conv_hits)
        if not mp.is_file():
            cls, why = "metadata_missing", "no 2-metas file: the matrix was never fetched at all"
        elif cp.is_file() and ev["csv_lines"] <= 1:
            cls = "empty_at_source"
            why = (f"CSV is header-only ({ev['csv_bytes']} bytes); fetch log reports 'Empty dataset' "
                   f"{len(empty_hits)}x and the retry with 'Total' options also failed. INS serves an "
                   "empty export, so there is nothing to convert.")
        elif cp.is_file():
            cls = "conversion_or_import_failure"
            why = f"CSV has {ev['csv_lines']} lines but no parquet: stage 9 failed or was never run for it"
        elif err_hits:
            cls, why = "fetch_failure", "fetch log records errors for this matrix and no CSV was written"
        else:
            cls = "csv_never_fetched"
            why = ("metadata fetched (stage 3) but no CSV on disk and no mention in the fetch log: stage 6 "
                   "never attempted/completed it (typically a matrix added after the last CSV batch)")
        ev["class"], ev["explanation"] = cls, why
        out[c] = ev
    by = {}
    for v in out.values():
        by[v["class"]] = by.get(v["class"], 0) + 1
    return {"count": len(out), "by_class": by, "matrices": out}


# ------------------------------------------------------------------ time
HOURS_RE = re.compile(r"\bore?\b|\bora\b", re.I)
MONTHS = {"ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie",
          "octombrie", "noiembrie", "decembrie"}
YEAR_PREFIX_RE = re.compile(r"^\s*(19|20)\d{2}\b")


def classify_time(pconn, path: Path, cols: list, time_re: str) -> dict:
    tcols = [c for c in cols if c.startswith("TIME_PERIOD")]
    stats = {}
    for t in tcols:
        inv, total, dist = pconn.execute(
            f'SELECT count(*) FILTER (WHERE NOT regexp_matches(CAST("{t}" AS VARCHAR), ?)), count(*), '
            f'count(DISTINCT "{t}") FROM read_parquet(?) WHERE "{t}" IS NOT NULL', [time_re, str(path)]).fetchone()
        samples = [r[0] for r in pconn.execute(
            f'SELECT CAST("{t}" AS VARCHAR) v FROM read_parquet(?) WHERE "{t}" IS NOT NULL '
            f'AND NOT regexp_matches(CAST("{t}" AS VARCHAR), ?) GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 6',
            [str(path), time_re]).fetchall()]
        distinct_invalid = [r[0] for r in pconn.execute(
            f'SELECT DISTINCT CAST("{t}" AS VARCHAR) FROM read_parquet(?) WHERE "{t}" IS NOT NULL '
            f'AND NOT regexp_matches(CAST("{t}" AS VARCHAR), ?) LIMIT 500', [str(path), time_re]).fetchall()]
        stats[t] = {"invalid_share": round(inv / total, 4) if total else 0.0, "distinct": dist,
                    "invalid_samples": samples, "_distinct_invalid": distinct_invalid}
    main = stats.get("TIME_PERIOD")
    alts = sorted(t for t, s in stats.items() if t != "TIME_PERIOD" and s["invalid_share"] <= 0.02)
    out = {"time_columns": stats}
    if main is None:
        return {**out, "class": "no_time_period_column"}
    if main["invalid_share"] >= 0.98 and alts:
        norm = [_strip(s) for s in main["_distinct_invalid"]]
        ore = sum(1 for s in norm if HOURS_RE.search(s))
        if main["distinct"] == 1:
            sub, new = "constant_indicator_label", "INDICATOR"
        elif norm and ore / len(norm) >= 0.6:  # most labels are hour bands; a few qualifiers ("Nu poate fi indicata...") ride along
            sub, new = "hours_worked_bands", "HOURS_WORKED"
        elif norm and all(re.match(r"^an(ul)? baza\b", s) for s in norm):
            sub, new = "base_year_labels", "BASE_YEAR"
        elif norm and all(s.strip() in MONTHS for s in norm):
            sub, new = "month_names", "MONTH_OF_YEAR"
        else:
            sub, new = "other_categorical_labels", "CATEGORY"
        remap = {"TIME_PERIOD": new, alts[0]: "TIME_PERIOD"}
        out.update({"class": f"shifted_time_column/{sub}", "proposed_remap": remap,
                    "needs_decision": "month names need composition with the year column (YYYY-MM)"
                    if sub == "month_names" else None})
    elif main["invalid_share"] >= 0.98:
        out["class"] = "no_valid_time_alternative"
    else:
        if main["invalid_samples"] and all(YEAR_PREFIX_RE.match(s) for s in main["invalid_samples"]):
            out["class"] = "partial_invalid/year_with_qualifier"
        else:
            out["class"] = "partial_invalid/mixed_values"
    for st in stats.values():
        st.pop("_distinct_invalid", None)
    return out


def report_time(rep: dict, data_dir: Path, audit) -> dict:
    pdir = data_dir / "corpus" / "parquet"
    codes = sorted(rep["violations"]["time_invalid_gt_20pct"])
    pconn = duckdb.connect()
    items = {}
    for c in codes:
        r = rep["files"][c]
        items[c] = {"category": r["category"], "rows": r.get("rows"),
                    "invalid_share": r.get("time_invalid_share"),
                    **classify_time(pconn, pdir / f"{c}.parquet", r["columns"], audit.TIME_RE)}
    pconn.close()
    by = {}
    for v in items.values():
        by[v["class"]] = by.get(v["class"], 0) + 1
    return {"count": len(items), "by_class": dict(sorted(by.items())), "files": items}


# ------------------------------------------------------------------ grain
def _dim_structure_verified(conn, matrix_code, column) -> bool:
    try:
        row = conn.execute("SELECT levels FROM dimension_structure WHERE matrix_code=? AND dim_column=?",
                           [matrix_code, column]).fetchone()
    except Exception:
        return False
    if not row or not row[0]:
        return False
    try:
        lv = json.loads(row[0])
    except Exception:
        return False
    return bool(lv) and all(l.get("verified") for l in lv)


def classify_grain(conn, rep: dict, data_dir: Path) -> dict:
    from app.services import aggregation_policy as ap
    from sdmx_labels import norm_label
    files = rep["files"]
    codes = sorted(rep["violations"]["conflicting_grain"])
    splits = {r[0]: r for r in conn.execute(
        "SELECT sub_matrix_code, parent_matrix_code, split_pattern, split_dimension FROM dataset_splits").fetchall()}
    names = dict(conn.execute("SELECT matrix_code, matrix_name FROM matrices").fetchall())
    units = dict(conn.execute("SELECT matrix_code, primary_unit_type FROM matrix_profiles").fetchall())
    out = {}
    for c in codes:
        r = files[c]
        rec = {"category": r["category"], "rows": r.get("rows"), "conflicting_keys": r.get("conflicting_keys"),
               "dup_rows": r.get("dup_rows")}
        sp = splits.get(c)
        parent = sp[1] if sp else None
        pr = files.get(parent) if parent else None
        unit_type = units.get(c) or (units.get(parent) if parent else None)
        text = names.get(c) or names.get(parent) or ""
        rec["unit_type"] = unit_type
        measure = ap.classify_measure(unit_type, _strip(text))
        rec["measure"] = measure
        if sp:
            rec.update(parent=parent, split_pattern=sp[2], split_dimension=sp[3])
            dropped = sorted((set(pr["columns"]) - set(r["columns"])) - {"OBS_VALUE", "value"}) if pr else []
            rec["dropped_dimensions"] = dropped
            rec["parent_also_conflicting"] = bool(pr and (pr.get("conflicting_keys") or 0) > 0)
            loc = [d for d in dropped if d == "REF_AREA_2" or "locali" in _strip(
                (conn.execute("SELECT dim_label FROM dimensions WHERE matrix_code=? AND dim_column_name=?",
                              [parent, d]).fetchone() or [""])[0])]
            if loc:
                rec["cause"] = "county_split_dropped_locality"
                rec["locality_dimension"] = loc[0]
                rec["disjoint_verified"] = _dim_structure_verified(conn, parent, loc[0])
                if measure == "additive" and rec["disjoint_verified"]:
                    rec["decision"] = "sum_localities_by_remaining_dims"
                elif measure == "additive":
                    rec["decision"] = "preserve_locality_grain_until_disjointness_verified"
                else:
                    rec["decision"] = "preserve_locality_grain_or_mark_county_aggregate_unavailable"
            elif dropped:
                rec["cause"] = "split_dropped_other_dimension"
                rec["decision"] = "restore_dropped_dimension_or_split_finer"
            else:
                rec["cause"] = "inherited_from_parent_source_duplicates" if rec["parent_also_conflicting"] \
                    else "split_introduced_collision_no_dropped_dimension"
                rec["decision"] = "investigate_source_do_not_deduplicate"
        else:
            # canonical/non-split file: every dimension is present, so look for
            # distinct source options that collapse onto one normalized label.
            coll = {}
            for did, col, n in conn.execute(
                    "SELECT dimension_id, dim_column_name, option_count FROM dimensions WHERE matrix_code=?", [c]).fetchall():
                labels = [x[0] for x in conn.execute(
                    "SELECT option_label FROM dimension_options WHERE dimension_id=?", [did]).fetchall()]
                if len({norm_label(l or "") for l in labels}) < len(labels):
                    coll[col] = len(labels) - len({norm_label(l or "") for l in labels})
            rec["label_collisions"] = coll
            rec["cause"] = "label_collision_in_source_options" if coll else "unexplained_duplicate_keys"
            rec["decision"] = "investigate_source_do_not_deduplicate"
        out[c] = rec
    by_cause, by_decision = {}, {}
    for v in out.values():
        by_cause[v["cause"]] = by_cause.get(v["cause"], 0) + 1
        by_decision[v["decision"]] = by_decision.get(v["decision"], 0) + 1
    return {"count": len(out), "by_cause": dict(sorted(by_cause.items())),
            "by_decision": dict(sorted(by_decision.items())), "files": out}


# ------------------------------------------------------------------ main
def build_plan(data_dir: Path, do_grain=True, audit_json=None) -> dict:
    audit = _load_audit()
    if audit_json:
        rep = json.loads(Path(audit_json).read_text())
        if "files" not in rep or not any("sha256" in v for v in rep["files"].values()):
            raise SystemExit("--audit-json needs an audit-corpus.py --full --hashes report")
    else:
        rep = audit.audit(data_dir, do_grain=do_grain, do_hashes=True)
    conn = duckdb.connect(str(data_dir / "corpus" / "metadata.duckdb"), read_only=True)
    try:
        matrices = {r[0]: r for r in conn.execute("SELECT matrix_code FROM matrices").fetchall()}
        split_subs = {r[0] for r in conn.execute("SELECT sub_matrix_code FROM dataset_splits").fetchall()}
        plan = {
            "kind": "repair-plan", "schema": 1, "mode": "dry-run", "data_dir": str(data_dir),
            "audit_summary": rep["summary"],
            "quarantine": plan_quarantine(rep, matrices, split_subs),
            "metadata_only": explain_metadata_only(rep, data_dir),
            "time_misclassified": report_time(rep, data_dir, audit),
            "conflicting_grain": classify_grain(conn, rep, data_dir) if do_grain or audit_json else
            {"count": 0, "skipped": "--no-grain"},
        }
    finally:
        conn.close()
    return plan


def render_md(p: dict) -> str:
    q, m, t, g = p["quarantine"], p["metadata_only"], p["time_misclassified"], p["conflicting_grain"]
    L = ["# Corpus repair plan (dry run)", "", f"Data dir: `{p['data_dir']}`", "",
         f"## Quarantine plan: {q['count']} files {q['by_category']}", ""]
    for i in q["files"][:12]:
        L.append(f"- `{i['file']}` rows={i['rows']} {i['reason']}")
    L += ["- ...", "", f"## Metadata-only matrices: {m['count']} {m['by_class']}", ""]
    for c, v in m["matrices"].items():
        L.append(f"- **{c}** ({v['class']}): {v['explanation']}")
    L += ["", f"## Time misclassification: {t['count']} served files", ""]
    for k, n in t["by_class"].items():
        ex = [c for c, v in t["files"].items() if v["class"] == k][:4]
        L.append(f"- `{k}`: {n}  e.g. {', '.join(ex)}")
    L += ["", f"## Conflicting grain: {g['count']} served files", ""]
    for k, n in g.get("by_cause", {}).items():
        L.append(f"- cause `{k}`: {n}")
    for k, n in g.get("by_decision", {}).items():
        L.append(f"- decision `{k}`: {n}")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Corpus repair planner (dry-run by default)")
    ap.add_argument("--data-dir", default=str(REPO / "data"))
    ap.add_argument("--report-json")
    ap.add_argument("--report-md")
    ap.add_argument("--audit-json", help="reuse an audit-corpus.py --full --hashes JSON (skips the scan)")
    ap.add_argument("--no-grain", action="store_true")
    ap.add_argument("--apply", action="store_true", help="quarantine step only, on --target-dir (a COPY)")
    ap.add_argument("--target-dir", help="copy of the data dir to apply to; required with --apply")
    a = ap.parse_args(argv)
    data_dir = Path(a.data_dir).resolve()
    if a.apply and not a.target_dir:
        ap.error("--apply requires --target-dir (an explicit copy; in-place repair is not supported)")
    if a.target_dir and not a.apply:
        ap.error("--target-dir only makes sense with --apply")
    for f in (a.report_json, a.report_md):
        if f and inside(Path(f).resolve(), data_dir / "corpus"):
            ap.error("report files must not be inside the corpus")

    plan = build_plan(data_dir, do_grain=not a.no_grain, audit_json=a.audit_json)
    if a.apply:
        # re-derive nothing from the copy: the plan is from the SOURCE audit; hashes are re-verified
        res = apply_quarantine(plan["quarantine"], data_dir, Path(a.target_dir).resolve())
        plan["mode"] = "apply-quarantine"
        plan["applied"] = res
        print(f"quarantined {res['moved']} files into {res['quarantine_dir']}")
    else:
        print(render_md(plan))
    if a.report_json:
        Path(a.report_json).write_text(json.dumps(plan, indent=1, sort_keys=True, default=str) + "\n")
    if a.report_md:
        Path(a.report_md).write_text(render_md(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
