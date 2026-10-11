#!/usr/bin/env python3
"""Record data_query.run_query answers as parity cases for the static engine.

For each dataset: the composed dashboard tile queries (what pages actually ask),
the headline series, and a seeded fuzz of group_by subsets, filter values
(single, several, totals, level members, unknown values), unknown columns,
malformed shapes and approximate on/off. Each case is one JSON line:

  {"code", "request": {filters, group_by, limit, approximate}, "response"} or
  {"code", "request", "error": {"status", "message"}}

`filters`/`group_by` use the sentinel "__MISSING__" for an absent parameter.

  TEMPO_DATA_DIR=<gen>/data python scripts/gen-parity-cases.py --out cases.jsonl \
      [--codes A,B] [--per-dataset 12] [--seed 1]
"""
import argparse
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

MISSING = "__MISSING__"


def requests_for(conn, code: str, rnd: random.Random, n_fuzz: int) -> list[dict]:
    from app.services.dataset_meta import get_dataset_meta
    from app.services.query_builder import resolve_parquet_schema
    from app.config import PARQUET_DIR
    meta = get_dataset_meta(code, lang="ro", conn=conn) or {}
    path = str(PARQUET_DIR / f"{code}.parquet")
    cols = [r[0] for r in conn.execute("DESCRIBE SELECT * FROM read_parquet(?)", [path]).fetchall()
            if r[0] != "OBS_VALUE"]
    values = {c: [r[0] for r in conn.execute(
        f'SELECT DISTINCT "{c}" FROM read_parquet(?) WHERE "{c}" IS NOT NULL ORDER BY 1 LIMIT 200',
        [path]).fetchall()] for c in cols}
    reqs = []
    add = lambda f=MISSING, g=MISSING, limit=50000, approximate=False: reqs.append(
        {"filters": f, "group_by": g, "limit": limit, "approximate": approximate})

    # what the pages ask
    comp = ((meta.get("chart_config") or {}).get("composition") or {})
    for ch in comp.get("charts") or []:
        d = ch.get("data") or {}
        add(d.get("filters") or {}, d.get("group_by") or MISSING)
    time_col = "TIME_PERIOD" if "TIME_PERIOD" in cols else None
    if time_col:
        add(MISSING, [time_col])
        add(MISSING, [time_col], approximate=True)
    add(MISSING, MISSING, limit=1000)

    # fuzz
    for _ in range(n_fuzz):
        k = rnd.choice([1, 1, 2, 2, 3])
        gb = rnd.sample(cols, min(k, len(cols))) if rnd.random() < 0.85 else MISSING
        flt = {}
        for c in rnd.sample(cols, rnd.randint(0, min(2, len(cols)))):
            if gb != MISSING and c in gb and rnd.random() < 0.5:
                continue
            vs = values[c]
            mode = rnd.random()
            if mode < 0.45 and vs:
                flt[c] = [rnd.choice(vs)]
            elif mode < 0.75 and len(vs) > 1:
                flt[c] = rnd.sample(vs, min(len(vs), rnd.randint(2, 5)))
            elif mode < 0.85:
                flt[c] = [rnd.choice(vs) if vs else "x", "__no_such_value__"]
            elif mode < 0.92:
                flt[c] = []
            else:
                flt[c] = [s for s in vs if s.strip().lower().startswith(("total", "toate"))][:1] or vs[:1]
        add(flt or MISSING, gb, limit=rnd.choice([50000, 50000, 5000, 3]),
            approximate=rnd.random() < 0.3)
    # invalid inputs (validation parity)
    add({"BOGUS": ["x"]}, MISSING)
    add(MISSING, ["BOGUS"])
    add(["REF_AREA"], MISSING)
    add({cols[0]: "x"} if cols else MISSING, MISSING)
    add({cols[0]: [None]} if cols else MISSING, MISSING)
    add(None, MISSING)
    add(MISSING, MISSING, limit=0)
    return reqs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--codes")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--per-dataset", type=int, default=12)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    from app.db import get_conn
    from app.services.data_query import QueryError, run_query
    from app.services.request_validation import MISSING as PY_MISSING
    conn = get_conn()
    if a.codes:
        codes = a.codes.split(",")
    else:
        from importlib import util
        spec = util.spec_from_file_location("bs", REPO / "scripts" / "build-static.py")
        bs = util.module_from_spec(spec)
        spec.loader.exec_module(bs)
        codes = bs.served_codes(conn)
    if a.limit:
        codes = codes[:a.limit]
    n = 0
    with open(a.out, "w", encoding="utf-8") as fh:
        for code in codes:
            rnd = random.Random(f"{a.seed}:{code}")
            for req in requests_for(conn, code, rnd, a.per_dataset):
                f = PY_MISSING if req["filters"] == MISSING else req["filters"]
                g = PY_MISSING if req["group_by"] == MISSING else req["group_by"]
                case = {"code": code, "request": req}
                try:
                    case["response"] = run_query(conn, code, f, g, req["limit"],
                                                 approximate=req["approximate"])
                except QueryError as e:
                    case["error"] = {"status": e.status, "message": e.message}
                fh.write(json.dumps(case, ensure_ascii=False, default=str, allow_nan=False) + "\n")
                n += 1
    print(f"{n} cases for {len(codes)} datasets -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
