#!/usr/bin/env python3
"""Measure KPI / composer-tile coverage on a data dir (FIX-03 structure backfill).

Calls the app's own services (compute_insights, get_dataset_meta composition) for
every served matrix (canonical + registered split child) and records, per code,
the KPIs produced and the suppression reasons. Run once against the real data dir
(before) and once against a data dir whose metadata.duckdb has the backfilled
dimension_structure (after), then diff the two JSON files with --compare.

READ-ONLY: it only reads the data dir; the in-process app opens DuckDB read_only.

  TEMPO_DATA_DIR is set from --data-dir BEFORE the app is imported, so run each
  measurement as its own process.

  python scripts/measure-structure-backfill.py --data-dir DIR --out FILE [--codes-file F] [--limit N]
  python scripts/measure-structure-backfill.py --compare BEFORE.json AFTER.json [--out FILE]
"""
import argparse
import collections
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KPI_KEYS = ("latest", "yoy", "prev", "overall")


def measure(codes):
    from app.services.insights import compute_insights
    from app.services.dataset_meta import get_dataset_meta
    out = {}
    for i, code in enumerate(codes, 1):
        rec = {"error": None}
        try:
            ins = compute_insights(code, "ro")
            if ins is None:
                rec["error"] = "no_insights"
            else:
                rec["kpis"] = sorted(k["key"] for k in ins["kpis"] if k["key"] in KPI_KEYS)
                rec["suppressed"] = [{"key": s["key"], "reason": s.get("reason"), "column": s.get("column")}
                                     for s in ins["suppressed"]]
        except Exception as e:  # measurement must not stop on one dataset
            rec["error"] = f"insights: {type(e).__name__}: {str(e)[:120]}"
        try:
            meta = get_dataset_meta(code, lang="ro")
            comp = ((meta or {}).get("chart_config") or {}).get("composition") or {}
            rec["tiles"] = len(comp.get("charts") or [])
            rec["tiles_suppressed"] = [{"id": s.get("id"), "reason": s.get("reason")}
                                       for s in comp.get("suppressed") or []]
        except Exception as e:
            rec["error"] = (rec["error"] or "") + f" composer: {type(e).__name__}: {str(e)[:120]}"
        out[code] = rec
        if i % 200 == 0:
            print(f"  {i}/{len(codes)}", file=sys.stderr, flush=True)
    return out


def summarize(res):
    n = len(res)
    has = {k: sum(1 for r in res.values() if k in r.get("kpis", [])) for k in KPI_KEYS}
    anyk = sum(1 for r in res.values() if r.get("kpis"))
    reasons = collections.Counter(s["reason"] for r in res.values() for s in r.get("suppressed", [])
                                  if s["key"] == "latest")
    tile_reasons = collections.Counter(s["reason"] for r in res.values() for s in r.get("tiles_suppressed", []))
    return {"datasets": n, "with_any_kpi": anyk, "kpi_counts": has,
            "suppressed_latest_reasons": dict(reasons.most_common()),
            "tiles_total": sum(r.get("tiles", 0) for r in res.values()),
            "tiles_suppressed_total": sum(len(r.get("tiles_suppressed", [])) for r in res.values()),
            "tiles_suppressed_reasons": dict(tile_reasons.most_common()),
            "errors": sum(1 for r in res.values() if r.get("error"))}


def compare(before, after):
    codes = sorted(set(before) & set(after))
    restored = [c for c in codes if "latest" not in before[c].get("kpis", []) and "latest" in after[c].get("kpis", [])]
    lost = [c for c in codes if "latest" in before[c].get("kpis", []) and "latest" not in after[c].get("kpis", [])]
    still = [c for c in codes if "latest" not in after[c].get("kpis", [])]
    why = collections.Counter(s["reason"] for c in still for s in after[c].get("suppressed", [])
                              if s["key"] == "latest")
    return {"compared": len(codes), "latest_restored": len(restored), "latest_lost": len(lost),
            "latest_still_missing": len(still), "still_missing_reasons": dict(why.most_common()),
            "restored_examples": restored[:15], "lost_examples": lost[:15],
            "before": summarize({c: before[c] for c in codes}), "after": summarize({c: after[c] for c in codes})}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir")
    ap.add_argument("--codes-file", help="one matrix code per line (default: all served from the DB)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    a = ap.parse_args()
    if a.compare:
        rep = compare(*(json.load(open(p))["results"] for p in a.compare))
    else:
        if not a.data_dir:
            ap.error("--data-dir required")
        os.environ["TEMPO_DATA_DIR"] = str(Path(a.data_dir).resolve())
        sys.path.insert(0, str(REPO))
        import duckdb
        db = Path(os.environ["TEMPO_DATA_DIR"]) / "corpus" / "metadata.duckdb"
        if a.codes_file:
            codes = [l.strip() for l in open(a.codes_file) if l.strip()]
        else:
            con = duckdb.connect(str(db), read_only=True)
            codes = [r[0] for r in con.execute(
                "SELECT matrix_code FROM matrices WHERE is_canonical ORDER BY 1").fetchall()]
            con.close()
        if a.limit:
            codes = codes[:a.limit]
        res = measure(codes)
        rep = {"data_dir": os.environ["TEMPO_DATA_DIR"], "summary": summarize(res), "results": res}
    text = json.dumps(rep, indent=1, sort_keys=True, default=str)
    if a.out:
        Path(a.out).write_text(text)
    print(json.dumps(rep.get("summary", {k: v for k, v in rep.items() if k not in ("results",)}),
                     indent=1, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
