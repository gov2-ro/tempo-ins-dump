"""Usage: python scripts/utils/meta-sweep.py OUT_DIR data/corpus/metadata.duckdb

Read-only sweep: fetch every INS matrix meta into OUT/metas, then list codes whose
ultimaActualizare is newer than the corpus DB, plus codes INS lists that the DB lacks."""
import sys, json, time, random, csv, datetime as dt
from pathlib import Path
import requests, duckdb
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tempo_http import decode_body
OUT = Path(sys.argv[1]); DB = sys.argv[2]
(OUT / "metas").mkdir(parents=True, exist_ok=True)
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
     "Referer": "http://statistici.insse.ro:8077/tempo-online/"}
B = "http://statistici.insse.ro:8077/tempo-ins/matrix/"
c = duckdb.connect(DB, read_only=True)
db = {r[0]: r[1] for r in c.execute("select matrix_code, ultima_actualizare from matrices where coalesce(is_split,false)=false").fetchall()}
lst = json.loads(decode_body(requests.get(B + "matrices?lang=ro", headers=H, timeout=60).content))
ins_codes = [i["code"] for i in lst]
(OUT / "ins-matrices.json").write_text(json.dumps(lst, ensure_ascii=False))
codes = sorted(set(ins_codes) | set(db))
print(f"INS lists {len(ins_codes)}, DB has {len(db)}, sweeping {len(codes)}", flush=True)
fails = []
for i, code in enumerate(codes, 1):
    p = OUT / "metas" / f"{code}.json"
    if not p.exists():
        for attempt in range(3):
            try:
                r = requests.get(f"{B}{code}?lang=ro", headers=H, timeout=30); r.raise_for_status()
                t = decode_body(r.content); json.loads(t); p.write_text(t, encoding="utf-8"); break
            except Exception as e:
                err = str(e); time.sleep(3 * (attempt + 1))
        else:
            fails.append((code, err))
        time.sleep(random.uniform(0.3, 0.8))
    if i % 100 == 0: print(i, flush=True)
rows = []
for code in codes:
    p = OUT / "metas" / f"{code}.json"
    if not p.exists(): continue
    u = json.loads(p.read_text()).get("ultimaActualizare")
    try: ud = dt.datetime.strptime(u, "%d-%m-%Y").date()
    except Exception: ud = None
    old = db.get(code)
    if code not in db: rows.append((code, "new_in_ins", u, None))
    elif code not in ins_codes: rows.append((code, "not_listed_by_ins", u, str(old)))
    elif ud and (old is None or ud > old): rows.append((code, "updated", u, str(old)))
with open(OUT / "changes.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["code", "kind", "ins_update", "db_update"]); w.writerows(rows)
json.dump(fails, open(OUT / "fails.json", "w"))
from collections import Counter
print("DONE", Counter(r[1] for r in rows), "fails", len(fails), flush=True)
