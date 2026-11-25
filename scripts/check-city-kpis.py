#!/usr/bin/env python3
"""Check the city KPI cards against the cell INS publishes (brief CP, decision 3).

For each listed city (place_kpi_config.json `featured_localities`) and each locality KPI, this
computes the card with the app's own service and asks the INS pivot API for the same cell:
the parent matrix, the city's SIRUTA option, the card's period, and the "Total" option on every
dimension the card sums. Read-only: it reads `--data-dir` and writes only to `--cache`.

  python scripts/check-city-kpis.py --data-dir DIR --cache DIR [--tol 0.005] [--delay 0.7] [--offline]
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location("check_kpi_totals", REPO / "scripts" / "check-kpi-totals.py")
ckt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ckt)


def ins_cell(meta: dict, siruta: str, year: str):
    """Option ids (one per dimension) of the INS cell for a city and a year; None when a dimension
    cannot be resolved. Dimensions are told apart by their label: counties, localities, periods."""
    ids, labels = [], []
    loc = next(d for d in meta["dimensionsMap"] if d["label"].strip().startswith("Localit"))
    lo = next((o for o in loc["options"] if o["label"].startswith(f"{siruta} ")), None)
    if lo is None:
        return None
    for d in meta["dimensionsMap"]:
        name, opts = d["label"].strip(), d["options"]
        if name.startswith("Localit"):
            o = lo
        elif name.startswith("Jude"):
            o = next((x for x in opts if x["nomItemId"] == lo["parentId"]), None)
        elif name in ("Ani", "Perioade"):
            o = next((x for x in opts if x["label"].strip() == f"Anul {year}"), None)
        elif name.startswith("UM"):
            o = opts[0]
        else:
            o = ckt._total_option(opts)
        if o is None:
            return None
        ids.append(o["nomItemId"])
        labels.append(o["label"].strip())
    return ids, labels


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--tol", type=float, default=0.005)
    ap.add_argument("--delay", type=float, default=0.7)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)
    data_dir = Path(a.data_dir).resolve()
    os.environ["TEMPO_DATA_DIR"] = str(data_dir)
    from app.services import place_service as ps
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    bad = 0
    for it in ps.featured_localities()["items"]:
        if it.get("type", "locality") != "locality":
            continue
        report = ps.get_place_kpi_report("locality", it["slug"])
        for k in report["kpis"]:
            code = k["source"]["code"]
            meta = json.loads((data_dir / "2-metas" / "ro" / f"{code}.json").read_text(encoding="utf-8"))
            cell = ins_cell(meta, str(it["siruta"]), k["period"])
            row = f"{it['name']:<13}{k['key']:<22}{k['period']}  ours={k['value']:>10.0f}"
            if cell is None:
                print(row, " INS cell not resolved")
                bad += 1
                continue
            q = {"matrix": code, "ids": cell[0], "labels": cell[1],
                 "details": {x: meta["details"].get(x) for x in ("matMaxDim", "matUMSpec", "matRegJ")}}
            text, _ = ckt.fetch_cell(q, cache, a.delay, a.offline)
            ins = ckt.parse_cell(text) if text else None
            if ins is None:
                print(row, " INS blank or not fetched")
                bad += 1
                continue
            rel = abs(k["value"] - ins) / abs(ins) if ins else float(k["value"] != 0)
            ok = rel <= a.tol
            bad += 0 if ok else 1
            print(f"{row}  ins={ins:>10.0f}  {'match' if ok else 'MISMATCH'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
