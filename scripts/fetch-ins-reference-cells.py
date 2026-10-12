#!/usr/bin/env python3
"""Fetch named INS reference cells (incl. "Total" options) as retained evidence.

Stage 6 drops every option labelled "Total", so the corpus cannot answer questions
whose statistic is a published total (county mean earnings over all activities,
both-sexes unemployment rate) and cannot verify a summed partition. This script asks
the TEMPO pivot API for exactly the cells a spec names and keeps INS's answer
verbatim, with what was asked and when. It never writes the corpus.

  python scripts/fetch-ins-reference-cells.py --spec SPEC.json \
      --meta-dir DATA/2-metas/ro --out EVIDENCE_DIR [--only ID] [--delay 1.0] [--dry-run]

Spec: {"queries": [{"id": ..., "matrix": ..., "select": [PICK, ...]}]}, one PICK per
matrix dimension, in dimension order:
  {"pick": "total"}                       the option labelled Total/TOTAL
  {"pick": "all"}                         every option (e.g. a one-option UM dim)
  {"pick": "labels", "labels": [...]}     exact labels (trimmed)
  {"pick": "counties", "total": true}     41 counties + Bucharest (+ TOTAL)
  {"pick": "years", "from": Y1, "to": Y2} "Anul Y" options in that range
  {"pick": "years", "from": Y1}           every "Anul Y" from Y1 that the metadata lists

Option ids come from the retained metadata (--meta-dir). INS's answer echoes labels,
so `labels_ok` in the manifest records whether every returned row names a requested
option: a renumbered option shows up there instead of silently answering another cell.
Output: <out>/<id>.csv (INS bytes) and <out>/manifest.json (request, payload, time,
sha256, row count, ':'/blank cells). Exit 1 if any query failed.
"""
import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PIVOT_URL = "http://statistici.insse.ro:8077/tempo-ins/pivot"
REFERER = "http://statistici.insse.ro:8077/tempo-online/"
CELL_LIMIT = 30000  # INS refuses larger pivot requests


def _is_total(label: str) -> bool:
    return label.strip().lower() == "total"


def _is_county(label: str) -> bool:
    s = label.strip()
    return not (_is_total(s) or s.upper().startswith("MACROREGIUNEA")
                or s.lower().startswith("regiunea"))


def pick_options(dim: dict, pick: dict) -> list[dict]:
    opts = dim["options"]
    kind = pick["pick"]
    if kind == "total":
        out = [o for o in opts if _is_total(o["label"])]
    elif kind == "all":
        out = list(opts)
    elif kind == "labels":
        want = [w.strip() for w in pick["labels"]]
        by = {o["label"].strip(): o for o in opts}
        missing = [w for w in want if w not in by]
        if missing:
            raise ValueError(f"labels not in metadata: {missing}")
        out = [by[w] for w in want]
    elif kind == "counties":
        out = [o for o in opts if _is_county(o["label"])]
        if pick.get("total"):
            out = [o for o in opts if _is_total(o["label"])] + out
    elif kind == "years" and pick.get("to") is None:
        # open-ended: every annual period from `from` that the metadata lists
        out = [o for o in opts if re.fullmatch(r"Anul (\d{4})", o["label"].strip())
               and int(o["label"].strip()[5:]) >= int(pick["from"])]
    elif kind == "years":
        want = {f"Anul {y}" for y in range(int(pick["from"]), int(pick["to"]) + 1)}
        out = [o for o in opts if o["label"].strip() in want]
        if len(out) != len(want):
            raise ValueError(f"years missing from metadata: "
                             f"{sorted(want - {o['label'].strip() for o in out})}")
    else:
        raise ValueError(f"unknown pick {kind!r}")
    if not out:
        raise ValueError(f"pick {pick} selected nothing in {dim['label']!r}")
    return out


def build_request(meta: dict, query: dict) -> tuple[dict, list[list[str]]]:
    dims = meta["dimensionsMap"]
    if len(query["select"]) != len(dims):
        raise ValueError(f"{query['id']}: {len(query['select'])} picks for {len(dims)} dimensions")
    chosen = [pick_options(d, p) for d, p in zip(dims, query["select"])]
    cells = 1
    for c in chosen:
        cells *= len(c)
    if cells > CELL_LIMIT:
        raise ValueError(f"{query['id']}: {cells} cells > INS limit {CELL_LIMIT}")
    det = meta["details"]
    payload = {"language": "ro", "matCode": query["matrix"],
               "encQuery": ":".join(",".join(str(o["nomItemId"]) for o in c) for c in chosen),
               "matMaxDim": det["matMaxDim"], "matUMSpec": det["matUMSpec"],
               "matRegJ": det.get("matRegJ") or 0}
    return payload, [[o["label"].strip() for o in c] for c in chosen]


def summarize(text: str, labels: list[list[str]]) -> dict:
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(x.strip() for x in r)]
    body = rows[1:]
    wanted = [set(ls) for ls in labels]
    # INS strips commas inside labels in CSV answers; compare without them.
    norm = lambda s: s.replace(",", "").strip()
    wanted_n = [{norm(x) for x in w} for w in wanted]
    labels_ok = all(len(r) == len(labels) + 1 and
                    all(norm(v) in wanted_n[i] for i, v in enumerate(r[:-1]))
                    for r in body)
    blank = sum(1 for r in body if r[-1].strip() in ("", ":", "-", "x"))
    return {"header": rows[0] if rows else None, "rows": len(body),
            "blank_or_suppressed": blank, "labels_ok": labels_ok}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", required=True)
    ap.add_argument("--meta-dir", required=True, help="retained INS metadata, e.g. DATA/2-metas/ro")
    ap.add_argument("--out", required=True, help="evidence directory (never inside corpus/)")
    ap.add_argument("--only", action="append", help="query id(s) to run")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between INS requests")
    ap.add_argument("--dry-run", action="store_true", help="resolve and print payloads only")
    args = ap.parse_args(argv)

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    out = Path(args.out)
    if "corpus" in out.resolve().parts:
        ap.error("--out must not be inside a corpus directory")
    queries = [q for q in spec["queries"] if not args.only or q["id"] in args.only]
    manifest_path = out / "manifest.json"
    manifest = (json.loads(manifest_path.read_text()) if manifest_path.exists()
                else {"kind": "ins-reference-cells", "spec": str(args.spec), "fetches": {}})

    failed = 0
    for i, q in enumerate(queries):
        meta_file = Path(args.meta_dir) / f"{q['matrix']}.json"
        meta_bytes = meta_file.read_bytes()
        try:
            payload, labels = build_request(json.loads(meta_bytes), q)
        except ValueError as e:
            print(f"{q['id']}: {e}", file=sys.stderr)
            failed += 1
            continue
        if args.dry_run:
            print(json.dumps({"id": q["id"], "payload": payload,
                              "cells": [len(x) for x in labels]}, ensure_ascii=False))
            continue
        import requests
        if i:
            time.sleep(args.delay)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            r = requests.post(PIVOT_URL, json=payload, timeout=120,
                              headers={"Content-Type": "application/json", "Referer": REFERER})
            r.raise_for_status()
        except Exception as e:
            print(f"{q['id']}: request failed: {type(e).__name__}: {e}", file=sys.stderr)
            failed += 1
            continue
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{q['id']}.csv").write_bytes(r.content)
        text = r.content.decode("utf-8", errors="replace")
        info = summarize(text, labels)
        manifest["fetches"][q["id"]] = {
            "matrix": q["matrix"], "select": q["select"], "payload": payload,
            "url": PIVOT_URL, "fetched_at": fetched_at, "http_status": r.status_code,
            "file": f"{q['id']}.csv", "sha256": hashlib.sha256(r.content).hexdigest(),
            "meta_file": str(meta_file), "meta_sha256": hashlib.sha256(meta_bytes).hexdigest(),
            **info}
        ok = info["rows"] > 0 and info["labels_ok"]
        failed += 0 if ok else 1
        print(f"{q['id']}: {info['rows']} rows, {info['blank_or_suppressed']} blank, "
              f"labels_ok={info['labels_ok']}")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
