#!/usr/bin/env python3
"""Check summed KPIs against the totals INS itself publishes (FIX-03 repair).

Stage 6 drops options labelled exactly "Total" when fetching, so most parquets have
no source total row, and a KPI that sums a dimension rests on dimension_structure
saying that dimension is a disjoint partition. `profile_flat` only means the
profiler found no hierarchy pattern. This script asks INS for the one cell that
should equal each summed KPI: same matrix, same period, the same pinned values, and
the "Total" option on every summed dimension.

  collect  compute every served dataset's latest KPI with the app's own services
           (read-only, TEMPO_DATA_DIR) and keep those that sum a dimension.
  check    resolve each KPI to one INS cell (parent matrix + nomItemIds), fetch it
           (cached, throttled; --offline uses only the cache), compare and report.

Split children are mapped to their parent: shared columns by name, and the values a
split fixed (e.g. UNIT_MEASURE) recovered by matching sampled child rows to the
parent parquet. A KPI is `unresolved` when that, a value's option or a Total option
cannot be determined; nothing is guessed.

  python scripts/check-kpi-totals.py collect --data-dir DIR --out kpis.json [--codes-file F]
  python scripts/check-kpi-totals.py check --data-dir DIR --kpis kpis.json --cache DIR \
      --out report.json [--md report.md] [--tol 0.005] [--delay 0.7] [--limit N] [--offline]
      [--write-db COPY/corpus/metadata.duckdb]
"""
import argparse
import collections
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from sdmx_labels import norm_label, norm_label_cs, parse_time_period  # noqa: E402

PIVOT_URL = "http://statistici.insse.ro:8077/tempo-ins/pivot"
SUMMED = ("partition", "level")
PINNED = ("singleton", "unit_pinned", "pinned_value", "pinned_aggregate")
TOTAL_RE = re.compile(r"^total(\s+din care:?)?$")


# ------------------------------------------------------------------ collect
def collect(data_dir: Path, codes=None) -> dict:
    os.environ["TEMPO_DATA_DIR"] = str(data_dir.resolve())
    import duckdb
    from app.services import insights
    from app.services.insights import compute_insights
    # Collect what the app would compute *before* the source-total gate, which is
    # fed by this script's own results (a KPI it withholds was never checked).
    if hasattr(insights, "_source_total_gate"):
        insights._source_total_gate = lambda *a, **k: (None, None)
    con = duckdb.connect(str(data_dir / "corpus" / "metadata.duckdb"), read_only=True)
    if codes is None:
        codes = [r[0] for r in con.execute(
            "SELECT matrix_code FROM matrices WHERE is_canonical OR is_split ORDER BY 1").fetchall()
            if (data_dir / "corpus" / "parquet" / f"{r[0]}.parquet").exists()]
    con.close()
    out, errors = {}, 0
    for i, code in enumerate(codes, 1):
        try:
            ins = compute_insights(code, "ro")
        except Exception as e:  # one dataset must not stop the sweep
            errors += 1
            out[code] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
            continue
        k = next((k for k in (ins or {}).get("kpis", []) if k["key"] == "latest"), None)
        if k:
            p = k.get("provenance") or {}
            dims = p.get("dimensions") or []
            if any(d.get("treatment") in SUMMED for d in dims):
                out[code] = {"value": k["value"], "period": p.get("period"), "filters": p.get("filters") or {},
                             "levels": p.get("levels") or {}, "method": p.get("method"),
                             "verification": p.get("verification"), "dimensions": dims}
        if i % 250 == 0:
            print(f"  {i}/{len(codes)}", file=sys.stderr, flush=True)
    return {"data_dir": str(data_dir), "datasets": len(codes), "errors": errors, "kpis": out}


# ------------------------------------------------------------------ resolve
def _match_option(options, value):
    """Metadata option for a parquet value: time by ISO period, else label (exact case first)."""
    v = str(value)
    hits = [o for o in options if parse_time_period(o["label"]) == v]
    if len(hits) == 1:
        return hits[0]
    for norm in (norm_label_cs, norm_label):
        hits = [o for o in options if norm(o["label"]) == norm(v)]
        if len(hits) == 1:
            return hits[0]
    return None


def _total_option(options):
    tot = [o for o in options if TOTAL_RE.match(norm_label(o["label"]))]
    exact = [o for o in tot if norm_label(o["label"]) == "total"]
    if len(exact) == 1:
        return exact[0]
    return tot[0] if len(tot) == 1 else None


class Resolver:
    def __init__(self, data_dir: Path):
        import duckdb
        self.data_dir = data_dir
        self.pq = data_dir / "corpus" / "parquet"
        self.con = duckdb.connect(str(data_dir / "corpus" / "metadata.duckdb"), read_only=True)
        self.pcon = duckdb.connect()
        self.parent = dict(self.con.execute(
            "SELECT sub_matrix_code, parent_matrix_code FROM dataset_splits").fetchall())

    def _columns(self, code):
        """{parquet column: dim_code} via dimensions (legacy names resolved through sdmx_column_map)."""
        cmap = dict(self.con.execute("SELECT old_column_name, sdmx_column_name FROM sdmx_column_map "
                                     "WHERE matrix_code = ?", [code]).fetchall())
        out = {}
        for col, dcode in self.con.execute("SELECT dim_column_name, dim_code FROM dimensions "
                                           "WHERE matrix_code = ?", [code]).fetchall():
            out[cmap.get(col, col) if col.endswith("_nom_id") else col] = dcode
        return out

    def _pcols(self, code):
        return [r[0] for r in self.pcon.execute("DESCRIBE SELECT * FROM read_parquet(?)",
                                                [str(self.pq / f"{code}.parquet")]).fetchall()]

    def fixed_values(self, child, parent):
        """Parent columns a split removed, with the one value every sampled child row has there."""
        ccols, pcols = self._pcols(child), self._pcols(parent)
        shared = [c for c in ccols if c in pcols and c != "OBS_VALUE"]
        absent = [c for c in pcols if c not in ccols and c != "OBS_VALUE"]
        if not absent:
            return {}
        rows = self.pcon.execute(
            f"SELECT {', '.join(f'{chr(34)}{c}{chr(34)}' for c in shared)}, OBS_VALUE FROM read_parquet(?) "
            "WHERE OBS_VALUE IS NOT NULL AND OBS_VALUE <> 0 USING SAMPLE 12 ROWS",
            [str(self.pq / f"{child}.parquet")]).fetchall()
        seen = set()
        for r in rows:
            where = " AND ".join(f'"{c}" IS NOT DISTINCT FROM ?' for c in shared) + " AND OBS_VALUE = ?"
            got = self.pcon.execute(
                f"SELECT DISTINCT {', '.join(f'{chr(34)}{c}{chr(34)}' for c in absent)} FROM read_parquet(?) "
                f"WHERE {where}", [str(self.pq / f"{parent}.parquet"), *r]).fetchall()
            if len(got) != 1:
                return None
            seen.add(got[0])
        return dict(zip(absent, seen.pop())) if len(seen) == 1 else None

    def resolve(self, code, kpi):
        """One INS cell for a KPI: {'matrix', 'ids', 'labels'} or {'unresolved': reason}."""
        parent = self.parent.get(code, code)
        meta_f = self.data_dir / "2-metas" / "ro" / f"{parent}.json"
        if not meta_f.exists():
            return {"unresolved": "no_parent_metadata"}
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        by_code = {d.get("dimCode"): d for d in meta["dimensionsMap"]}
        pcols = self._columns(parent)                 # parent column -> dim_code
        fixed = {}
        if parent != code:
            fixed = self.fixed_values(code, parent)
            if fixed is None:
                return {"unresolved": "split_value_not_recovered"}
        treat = {d["column"]: d.get("treatment") for d in kpi["dimensions"]}
        choice = {}                                   # dim_code -> option
        for col, t in treat.items():
            dcode = pcols.get(col)
            if dcode is None or dcode not in by_code:
                return {"unresolved": f"column_not_in_parent:{col}"}
            opts = by_code[dcode]["options"]
            if t == "time":
                o = _match_option(opts, kpi["period"])
            elif t in SUMMED:
                o = _total_option(opts)
                if o is None:
                    return {"unresolved": f"no_total_option:{col}"}
            elif t in PINNED:
                vals = kpi["filters"].get(col)
                if not vals and t == "singleton":
                    vals = [r[0] for r in self.pcon.execute(
                        f'SELECT DISTINCT "{col}" FROM read_parquet(?)',
                        [str(self.pq / f"{code}.parquet")]).fetchall()]
                if not vals or len(vals) != 1:
                    return {"unresolved": f"pin_not_single:{col}"}
                o = _match_option(opts, vals[0])
            else:
                return {"unresolved": f"treatment:{t}:{col}"}
            if o is None:
                return {"unresolved": f"option_not_found:{col}"}
            choice[dcode] = o
        for col, val in fixed.items():
            dcode = pcols.get(col)
            if dcode is None or dcode not in by_code:
                return {"unresolved": f"fixed_column_not_in_parent:{col}"}
            o = _match_option(by_code[dcode]["options"], val)
            if o is None:
                return {"unresolved": f"option_not_found:{col}"}
            choice[dcode] = o
        missing = [d["label"] for d in meta["dimensionsMap"] if d.get("dimCode") not in choice]
        if missing:
            return {"unresolved": f"dimension_not_covered:{missing[0][:40]}"}
        dims = meta["dimensionsMap"]
        return {"matrix": parent, "ids": [choice[d["dimCode"]]["nomItemId"] for d in dims],
                "labels": [choice[d["dimCode"]]["label"].strip() for d in dims],
                "details": {k: meta["details"].get(k) for k in ("matMaxDim", "matUMSpec", "matRegJ")}}


# ------------------------------------------------------------------ fetch
def fetch_cell(q, cache: Path, delay: float, offline: bool):
    key = hashlib.sha1(f"{q['matrix']}:{q['ids']}".encode()).hexdigest()[:20]
    f = cache / f"{q['matrix']}-{key}.csv"
    if f.exists():
        return f.read_text(encoding="utf-8"), True
    if offline:
        return None, False
    import requests
    payload = {"language": "ro", "encQuery": ":".join(str(i) for i in q["ids"]), "matCode": q["matrix"],
               "matMaxDim": q["details"]["matMaxDim"], "matUMSpec": q["details"]["matUMSpec"],
               "matRegJ": q["details"].get("matRegJ") or 0}
    time.sleep(delay)
    r = requests.post(PIVOT_URL, json=payload, timeout=60, headers={
        "Content-Type": "application/json", "Referer": "http://statistici.insse.ro:8077/tempo-online/"})
    r.raise_for_status()
    text = r.content.decode("utf-8", errors="replace")
    f.write_text(text, encoding="utf-8")
    return text, False


def parse_cell(text):
    """The value of a one-cell CSV answer; None when INS returns no row (':' / suppressed)."""
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return None
    if len(lines) > 2:
        raise ValueError(f"expected one data row, got {len(lines) - 1}")
    v = lines[1].rsplit(",", 1)[-1].strip()
    try:
        return float(v)
    except ValueError:
        return None


def check(data_dir: Path, kpis: dict, cache: Path, tol: float, delay: float, limit=None, offline=False):
    cache.mkdir(parents=True, exist_ok=True)
    res = Resolver(data_dir)
    out, fetched = {}, 0
    items = sorted(kpis.items())
    for i, (code, k) in enumerate(items, 1):
        if "error" in k:
            continue
        rec = {"ours": k["value"], "period": k["period"], "verification": k["verification"],
               "summed": [d["column"] for d in k["dimensions"] if d.get("treatment") in SUMMED],
               "summed_verification": sorted({d.get("verification") or "?" for d in k["dimensions"]
                                              if d.get("treatment") in SUMMED})}
        try:
            q = res.resolve(code, k)
        except Exception as e:
            q = {"unresolved": f"resolve_error:{type(e).__name__}:{str(e)[:80]}"}
        if "unresolved" in q:
            rec.update(status="unresolved", reason=q["unresolved"])
            out[code] = rec
            continue
        rec.update(matrix=q["matrix"], cell=q["labels"])
        try:
            text, hit = fetch_cell(q, cache, delay, offline or (limit is not None and fetched >= limit))
        except Exception as e:
            rec.update(status="fetch_error", reason=f"{type(e).__name__}: {str(e)[:120]}")
            out[code] = rec
            continue
        if text is None:
            rec.update(status="not_fetched")
            out[code] = rec
            continue
        fetched += 0 if hit else 1
        try:
            ins = parse_cell(text)
        except ValueError as e:
            rec.update(status="bad_answer", reason=str(e))
            out[code] = rec
            continue
        rec["ins"] = ins
        if ins is None:
            rec["status"] = "ins_blank"
        else:
            diff = k["value"] - ins
            rel = abs(diff) / abs(ins) if ins else (0.0 if diff == 0 else float("inf"))
            rec.update(diff=diff, rel=rel, status="match" if rel <= tol else "mismatch")
        out[code] = rec
        if i % 100 == 0:
            print(f"  {i}/{len(items)} ({fetched} fetched)", file=sys.stderr, flush=True)
    return out


def summarize(results: dict, tol: float) -> dict:
    st = collections.Counter(r["status"] for r in results.values())
    by_ver = collections.defaultdict(collections.Counter)
    for r in results.values():
        by_ver["+".join(r["summed_verification"])][r["status"]] += 1
    unresolved = collections.Counter(r["reason"].split(":")[0] for r in results.values()
                                     if r["status"] == "unresolved")
    rel = sorted(r["rel"] for r in results.values() if "rel" in r)
    exact = sum(1 for x in rel if x == 0)
    return {"kpis": len(results), "tolerance": tol, "status": dict(st.most_common()),
            "by_summed_verification": {k: dict(v) for k, v in sorted(by_ver.items())},
            "unresolved_reasons": dict(unresolved.most_common()),
            "compared": len(rel), "exact": exact,
            "rel_quantiles": {q: rel[int(q * (len(rel) - 1))] for q in (0.5, 0.9, 0.95, 0.99)} if rel else {}}


TABLE_DDL = """CREATE OR REPLACE TABLE kpi_total_checks (
    matrix_code VARCHAR PRIMARY KEY, period VARCHAR, ours DOUBLE, ins DOUBLE, rel DOUBLE,
    status VARCHAR, reason VARCHAR, source_matrix VARCHAR, cell VARCHAR, checked_at TIMESTAMP)"""


def write_db(db: Path, results: dict) -> int:
    """Store results as kpi_total_checks in a COPY's metadata.duckdb (the app's gate reads it)."""
    import datetime
    import duckdb
    live = (REPO / "data" / "corpus").resolve()
    if db.resolve() == live or live in db.resolve().parents:
        raise SystemExit(f"refusing to write {db}: that is the repository's own corpus")
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    rows = [(c, r.get("period"), r.get("ours"), r.get("ins"),
             r.get("rel") if r.get("rel") not in (float("inf"),) else None, r["status"], r.get("reason"),
             r.get("matrix"), json.dumps(r.get("cell"), ensure_ascii=False) if r.get("cell") else None, now)
            for c, r in sorted(results.items())]
    con = duckdb.connect(str(db))
    try:
        con.execute(TABLE_DDL)
        con.executemany("INSERT INTO kpi_total_checks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    finally:
        con.close()
    return len(rows)


def render_md(summary, results, top=25):
    L = ["# KPI totals vs INS", "", f"Tolerance {summary['tolerance']:.2%} relative.", "",
         "| status | count |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in summary["status"].items()]
    L += ["", "By verification of the summed dimensions:", ""]
    L += [f"- `{k}`: {v}" for k, v in summary["by_summed_verification"].items()]
    if summary["unresolved_reasons"]:
        L += ["", "Unresolved: " + ", ".join(f"{k} {v}" for k, v in summary["unresolved_reasons"].items())]
    mism = sorted(((c, r) for c, r in results.items() if r["status"] == "mismatch"),
                  key=lambda x: -x[1]["rel"])
    if mism:
        L += ["", f"## Largest mismatches (of {len(mism)})", "", "| dataset | period | ours | INS | rel | summed |",
              "|---|---|---|---|---|---|"]
        L += [f"| {c} | {r['period']} | {r['ours']:,.6g} | {r['ins']:,.6g} | {r['rel']:.1%} | {', '.join(r['summed'])} |"
              for c, r in mism[:top]]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--data-dir", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--codes-file")
    k = sub.add_parser("check")
    k.add_argument("--data-dir", required=True)
    k.add_argument("--kpis", required=True)
    k.add_argument("--cache", required=True)
    k.add_argument("--out", required=True)
    k.add_argument("--md")
    k.add_argument("--codes-file", help="only these datasets")
    k.add_argument("--tol", type=float, default=0.005)
    k.add_argument("--delay", type=float, default=0.7, help="seconds between INS requests")
    k.add_argument("--limit", type=int, help="at most N new INS requests (cached answers are free)")
    k.add_argument("--offline", action="store_true", help="use cached answers only")
    k.add_argument("--write-db", help="store results as kpi_total_checks in this metadata.duckdb "
                                      "(a copy; replaces the table)")
    a = ap.parse_args(argv)
    data_dir = Path(a.data_dir).resolve()
    corpus = data_dir / "corpus"
    for f in (a.out, getattr(a, "md", None), getattr(a, "cache", None)):
        if f and corpus in Path(f).resolve().parents:
            ap.error("outputs must not be inside the corpus")
    if a.cmd == "collect":
        codes = [l.strip() for l in open(a.codes_file) if l.strip()] if a.codes_file else None
        rep = collect(data_dir, codes)
        Path(a.out).write_text(json.dumps(rep, indent=1, sort_keys=True, default=str) + "\n")
        print(f"{len(rep['kpis'])} summed latest KPIs of {rep['datasets']} datasets ({rep['errors']} errors)")
        return 0
    kpis = json.loads(Path(a.kpis).read_text())["kpis"]
    if a.codes_file:
        keep = {l.strip() for l in open(a.codes_file) if l.strip()}
        kpis = {c: v for c, v in kpis.items() if c in keep}
    results = check(data_dir, kpis, Path(a.cache), a.tol, a.delay, a.limit, a.offline)
    summary = summarize(results, a.tol)
    Path(a.out).write_text(json.dumps({"summary": summary, "results": results}, indent=1, sort_keys=True) + "\n")
    if a.md:
        Path(a.md).write_text(render_md(summary, results))
    if a.write_db:
        print(f"wrote {write_db(Path(a.write_db), results)} rows to kpi_total_checks in {a.write_db}",
              file=sys.stderr)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
