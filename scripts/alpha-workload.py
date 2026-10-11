#!/usr/bin/env python3
"""Bounded mixed workload for the public-alpha release gate (PA-04).

N concurrent clients run a mix of search, county queries, the tourism recipe,
canonical pages, evidence bundles and complete CSV exports for D seconds against
a NON-production server. Records latency percentiles per kind, status counts,
explicit limit responses (413/429/503), and inconsistencies: the same request
must always return the same body (cross-request leakage) and a CSV must contain
exactly the rows its headers promise. With --pid, the server's RSS is sampled.

  python scripts/alpha-workload.py --base http://127.0.0.1:8099 --clients 5 \
      --duration 600 --pid <uvicorn pid> --out report.json

Exit 1 on any unexpected 5xx, inconsistency or corrupt export.
"""
import argparse
import hashlib
import json
import random
import statistics
import subprocess
import sys
import threading
import time
from urllib.parse import quote

import httpx

PRODUCTION_HOSTS = ("ins.gov2.ro", "tempo-ins-explorer.fly.dev")

F = lambda d: quote(json.dumps(d, ensure_ascii=False))
REQUESTS = [
    # (kind, path, weight)
    ("search", "/api/search?q=" + quote("populatia rezidenta Cluj"), 3),
    ("search", "/api/search?q=" + quote("salariul mediu net Cluj Iasi Bucuresti"), 2),
    ("search", "/api/search?q=" + quote("unemployment rate") + "&lang=en", 2),
    ("search", "/api/datasets?q=turism&limit=20", 1),
    ("query", "/api/datasets/POP105A_judete_grupe/data?filters=" + F({"REF_AREA": ["Cluj"]})
     + "&group_by=" + F(["TIME_PERIOD"]), 3),
    ("query", "/api/datasets/TUR105D_judete/data?filters=" + F({"TIME_PERIOD": ["2024"]})
     + "&group_by=" + F(["REF_AREA"]), 2),
    ("query", "/api/datasets/SOM103A_judete/data?filters=" + F({"TIME_PERIOD": ["2024"]})
     + "&group_by=" + F(["REF_AREA"]), 1),
    ("query", "/api/datasets/FOM106F/data?group_by=" + F(["TIME_PERIOD", "ECON_ACTIVITY"]), 1),
    ("query", "/api/datasets/POP107D_grupe_judet/data?filters=" + F({"REF_AREA": ["Cluj"]})
     + "&group_by=" + F(["TIME_PERIOD"]), 1),
    ("recipe", "/api/recipes/tourism_intensity", 2),
    ("recipe", "/api/recipes/tourism_intensity?year=2019&areas=" + F(["Cluj", "Iasi", "Municipiul București"]), 1),
    ("page", "/dataset/POP105A_judete_grupe", 1),
    ("page", "/place/county/cluj", 1),
    ("place", "/api/places/county/cluj", 1),
    ("evidence", "/api/recipes/tourism_intensity/evidence", 1),
    ("evidence", "/api/datasets/POP105A_judete_grupe/evidence?filters=" + F({"REF_AREA": ["Cluj"]})
     + "&group_by=" + F(["TIME_PERIOD"]), 1),
    ("export", "/api/datasets/TUR105D_judete/download?format=csv", 1),
    ("export", "/api/datasets/POP105A_judete_varste/download?format=csv", 1),
]
# Responses that legitimately vary between identical requests.
VARIABLE = {"evidence"}         # manifest carries created_at


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--clients", type=int, default=5)
    ap.add_argument("--duration", type=int, default=600)
    ap.add_argument("--pid", type=int, help="server pid whose RSS is sampled every second")
    ap.add_argument("--out", help="write the JSON report here")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--only", action="append", help="restrict to these request kinds (diagnosis)")
    a = ap.parse_args()
    if any(h in a.base for h in PRODUCTION_HOSTS):
        sys.exit("refusing to load-test production")

    lock = threading.Lock()
    lat, status, first_hash = {}, {}, {}
    problems, rss = [], []
    stop = time.monotonic() + a.duration
    pool = [r for r in REQUESTS for _ in range(r[2]) if not a.only or r[0] in a.only]

    def client(i):
        rnd = random.Random(a.seed + i)
        with httpx.Client(base_url=a.base, timeout=120) as c:
            while time.monotonic() < stop:
                kind, path, _ = rnd.choice(pool)
                t0 = time.monotonic()
                try:
                    r = c.get(path)
                    body = r.content
                except Exception as e:
                    with lock:
                        problems.append(f"{path}: {type(e).__name__}: {e}")
                    continue
                dt = time.monotonic() - t0
                note = None
                if r.status_code == 200 and kind == "export":
                    lines = body.count(b"\n") - 1
                    want = int(r.headers.get("X-Export-Rows", -1))
                    if lines != want or r.headers.get("X-Export-Complete") != "true":
                        note = f"corrupt export {path}: {lines} rows vs header {want}"
                if r.status_code == 200 and kind not in VARIABLE:
                    h = hashlib.sha256(body).hexdigest()
                    with lock:
                        if first_hash.setdefault(path, h) != h and kind != "page":
                            note = f"different body for identical request {path}"
                with lock:
                    lat.setdefault(kind, []).append(dt)
                    status.setdefault(kind, {}).setdefault(r.status_code, 0)
                    status[kind][r.status_code] += 1
                    if r.status_code >= 500 and r.status_code != 503:
                        problems.append(f"{r.status_code} {path}")
                    if note:
                        problems.append(note)

    def sampler():
        while time.monotonic() < stop:
            try:
                out = subprocess.run(["ps", "-o", "rss=", "-p", str(a.pid)], capture_output=True, text=True)
                rss.append(int(out.stdout.strip()) / 1024)
            except Exception:
                pass
            time.sleep(1)

    threads = [threading.Thread(target=client, args=(i,)) for i in range(a.clients)]
    if a.pid:
        threads.append(threading.Thread(target=sampler))
    t_start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    def pct(xs, p):
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, int(p / 100 * len(xs)))], 3) if xs else None

    report = {
        "base": a.base, "clients": a.clients, "duration_s": a.duration,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t_start)),
        "requests": sum(len(v) for v in lat.values()),
        "latency_s": {k: {"n": len(v), "p50": pct(v, 50), "p95": pct(v, 95), "max": round(max(v), 3),
                          "mean": round(statistics.mean(v), 3)} for k, v in sorted(lat.items())},
        "status": status,
        "explicit_limits": {k: {s: n for s, n in v.items() if s in (413, 429, 503)} for k, v in status.items()},
        "rss_mib": {"peak": round(max(rss), 1), "last": round(rss[-1], 1), "samples": len(rss)} if rss else None,
        "problems": problems[:50], "problem_count": len(problems),
    }
    text = json.dumps(report, indent=1)
    print(text)
    if a.out:
        open(a.out, "w").write(text + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
