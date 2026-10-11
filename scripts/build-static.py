#!/usr/bin/env python3
"""Build the static site's data layer (static-first deployment, S1).

Read-only on the generation selected with TEMPO_DATA_DIR. For every requested
served dataset it writes, under --out:

  data/{code}.bin.gz          TCOL1 binary table (see `tcol`): dictionary-encoded
                              dims as int16/int32 codes, unrounded OBS_VALUE
  data/{code}.index.json      only for datasets above --partition-rows: partition
                              files by REF_AREA and by TIME_PERIOD, plus the
                              distinct values of every column
  data/{code}/{area|time}/{n}.bin.gz   the partitions
  policy/{code}.json.gz       everything the browser engine needs to reproduce
                              data_query.run_query exactly: recorded dimensions,
                              allowed column names, time column, the aggregation
                              context decide_grouped uses (with the composer's
                              data-grounded `effective` options pre-resolved), the
                              source-total check row and the grain status
  build.json                  generation, commit, counts
  rec/, search/, the site     recorded API answers, search inputs, app/static and
                              view profiles with a static-mode js/config.js
                              (scripts/static_api.py; skipped with --no-record)

The browser never re-derives any of these: Python stays the specification and
tools/static-engine/parity.mjs proves the JS engine reproduces run_query.

  TEMPO_DATA_DIR=<gen>/data python scripts/build-static.py --out _static [--codes A,B] [--limit N]
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import static_api  # noqa: E402
from static_api import gz_json  # noqa: E402

PARTITION_ROWS = 200_000
# Most a single query may download (compressed). Above it the browser refuses
# with reason `browser_budget` instead of fetching (a deliberate divergence from
# the server, which would answer): filter a county or fewer periods instead.
MAX_QUERY_BYTES = 12_000_000
SCHEMA = 1


def _json_dump(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    path.write_text(data, encoding="utf-8")
    return len(data)


def served_codes(conn) -> list[str]:
    from app.config import PARQUET_DIR
    rows = conn.execute("SELECT matrix_code FROM matrices WHERE is_canonical ORDER BY 1").fetchall()
    return [r[0] for r in rows if (PARQUET_DIR / f"{r[0]}.parquet").exists()]


# ------------------------------------------------------------------ data
#
# TCOL1 binary table (gzip-compressed on disk as .bin.gz):
#   b"TCOL1\n" | uint32 LE header length | header JSON (utf-8) | pad to 8 |
#   per dimension column: int16 or int32 LE codes (-1 = NULL) | pad to 8 |
#   values: int32 LE (INT_NULL = NULL) when every value is integral and fits,
#           else float64 LE (NaN = NULL)
# header = {rows, columns, dicts: {col: [values]}, code_types: {col: "i16"|"i32"},
#           value_type: "i32"|"f64"}
# About the size of zstd parquet once gzipped, decoded with typed arrays only.

INT_NULL = -2**31
MAGIC = b"TCOL1\n"


def _pad(buf: bytearray):
    buf.extend(b"\0" * (-len(buf) % 8))


def tcol(conn, path: str, where: str = "", params=()) -> bytes:
    import gzip
    import numpy as np
    rel = conn.execute(f"SELECT * FROM read_parquet(?) {where}", [path, *params])
    cols = [d[0] for d in rel.description]
    df = rel.df()
    dims = [c for c in cols if c != "OBS_VALUE"]
    header = {"rows": len(df), "columns": dims + ["OBS_VALUE"], "dicts": {}, "code_types": {}}
    blocks = []
    for c in dims:
        codes, uniques = (df[c].factorize(use_na_sentinel=True) if len(df) else (np.array([], dtype=np.int64), []))
        header["dicts"][c] = [str(u) for u in uniques]
        t = "i16" if len(uniques) < 32767 else "i32"
        header["code_types"][c] = t
        blocks.append(np.asarray(codes).astype("<i2" if t == "i16" else "<i4").tobytes())
    v = df["OBS_VALUE"].to_numpy(dtype="float64") if len(df) else np.array([], dtype="float64")
    finite = v[~np.isnan(v)]
    integral = bool(np.all(finite == np.round(finite))) and (not finite.size or float(np.max(np.abs(finite))) < 2**31 - 1)
    if integral:
        header["value_type"] = "i32"
        blocks.append(np.where(np.isnan(v), INT_NULL, v).astype("<i4").tobytes())
    else:
        header["value_type"] = "f64"
        blocks.append(v.astype("<f8").tobytes())
    hj = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    buf = bytearray(MAGIC)
    buf.extend(len(hj).to_bytes(4, "little"))
    buf.extend(hj)
    _pad(buf)
    for blk in blocks:
        buf.extend(blk)
        _pad(buf)
    return gzip.compress(bytes(buf), 6, mtime=0)


def _write(path: Path, data: bytes) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)


def export_data(conn, code: str, out: Path, partition_rows: int) -> dict:
    from app.config import PARQUET_DIR
    path = str(PARQUET_DIR / f"{code}.parquet")
    n = conn.execute("SELECT count(*) FROM read_parquet(?)", [path]).fetchone()[0]
    cols = [r[0] for r in conn.execute("DESCRIBE SELECT * FROM read_parquet(?)", [path]).fetchall()]
    if n <= partition_rows:
        size = _write(out / "data" / f"{code}.bin.gz", tcol(conn, path))
        return {"rows": n, "bytes": size, "partitioned": False}
    # Partitioned: by area (county) and by time; the engine loads only what the
    # effective filters need. Distinct values cover the whole file.
    index = {"code": code, "rows": n, "columns": [c for c in cols if c != "OBS_VALUE"],
             "distinct": {}, "partitions": {}}
    for c in index["columns"]:
        index["distinct"][c] = [r[0] for r in conn.execute(
            f'SELECT DISTINCT "{c}" FROM read_parquet(?) WHERE "{c}" IS NOT NULL ORDER BY 1',
            [path]).fetchall()]
    total = 0
    for key, col in (("area", "REF_AREA"), ("time", "TIME_PERIOD")):
        if col not in cols:
            continue
        files, counts, sizes = {}, {}, {}
        rows_by = dict(conn.execute(f'SELECT "{col}", count(*) FROM read_parquet(?) GROUP BY 1',
                                    [path]).fetchall())
        for i, v in enumerate(index["distinct"][col]):
            name = f"{i:04d}.bin.gz"
            size = _write(out / "data" / code / key / name,
                          tcol(conn, path, f'WHERE "{col}" = ?', [v]))
            total += size
            files[v] = f"{code}/{key}/{name}"
            counts[v] = rows_by.get(v, 0)
            sizes[v] = size
        index["partitions"][key] = {"column": col, "files": files, "rows": counts, "bytes": sizes}
        nulls = conn.execute(f'SELECT count(*) FROM read_parquet(?) WHERE "{col}" IS NULL',
                             [path]).fetchone()[0]
        if nulls:          # rows with a NULL partition value must not be lost
            total += _write(out / "data" / code / key / "null.bin.gz",
                            tcol(conn, path, f'WHERE "{col}" IS NULL'))
            index["partitions"][key]["null"] = f"{code}/{key}/null.bin.gz"
    _json_dump(index, out / "data" / f"{code}.index.json")
    return {"rows": n, "bytes": total, "partitioned": True}


# ------------------------------------------------------------------ policy

def _opt(o: dict) -> dict:
    p = o.get("parsed") or {}
    return {"label": o.get("label"), "sdmx_value": o.get("sdmx_value"),
            "parsed": {k: p.get(k) for k in ("geo_level", "age_min", "age_max") if p.get(k) is not None}}


def export_policy(conn, code: str) -> dict:
    """The inputs of data_query.run_query for one dataset, nothing derived."""
    from app.services import data_query as dq, grain_guard, generation
    from app.services.dashboard_composer import _effective
    from app.services.concept_search import dataset_facts
    from app.services.dataset_meta import get_aggregation_context
    from app.services.query_builder import resolve_parquet_schema
    row_count = conn.execute("SELECT row_count FROM matrices WHERE matrix_code = ?",
                             [code]).fetchone()[0] or 0
    dims = [{"dim_code": d[0], "dim_label": d[1], "dim_column_name": d[2], "option_count": d[3] or 1}
            for d in conn.execute("""SELECT dim_code, dim_label, dim_column_name, option_count
                                      FROM dimensions WHERE matrix_code = ? ORDER BY dim_code""",
                                  [code]).fetchall()]
    schema = resolve_parquet_schema(conn, code)
    if schema["is_legacy"]:
        raise SystemExit(f"{code}: legacy parquet schema is not supported by the static engine")
    allowed = sorted(dq._allowed_columns(dims, schema))
    from app.services.query_builder import to_sdmx_name, adapt_to_parquet
    rename = {c: to_sdmx_name(schema, c) for c in allowed if to_sdmx_name(schema, c) != c}
    file_dims, _, _ = adapt_to_parquet(schema, dims, None, {})
    time_col = dq._resolve_time_column(conn, file_dims, schema, code)

    ctx = get_aggregation_context(conn, code)
    pctx = None
    if ctx is not None:
        pdims, effective = [], {}
        for d in ctx["dimensions"]:
            opts = d.get("options") or []
            pdims.append({"dim_column_name": d["dim_column_name"], "dim_type": d.get("dim_type"),
                          "options": [_opt(o) for o in opts]})
            ids = {id(o): i for i, o in enumerate(opts)}
            effective[d["dim_column_name"]] = [[ids[id(o)], dv]
                                               for o, dv in _effective(d, ctx["actual_values"])]
        pctx = {"dimensions": pdims, "effective": effective, "struct": ctx["struct"] or {},
                "measure": ctx["measure"], "light": bool(ctx.get("light"))}
    try:
        cur = conn.execute("SELECT * FROM kpi_total_checks WHERE matrix_code = ?", [code])
        r = cur.fetchone()
        kpi = dict(zip([d[0] for d in cur.description], r)) if r else {}
        kpi = {k: kpi.get(k) for k in ("status", "reason", "period", "ins", "rel")}
        kpi_table = True
    except Exception:
        kpi, kpi_table = {}, False
    return {
        "schema": SCHEMA, "code": code, "row_count": row_count, "dimensions": dims,
        "file_dimensions": file_dims, "allowed": allowed, "rename": rename, "time_col": time_col,
        "schema_mismatch": dq.schema_mismatch(schema, dims),
        "to_file": schema.get("to_file") or {}, "to_sdmx": schema.get("to_sdmx") or {},
        "file_columns": schema.get("columns") or [], "value_column": schema.get("value_column"),
        "value_type": _value_type(conn, code, schema.get("value_column")),
        "en_labels": _en_labels(conn, code, file_dims),
        "facts": {lang: dataset_facts(conn, code, lang) for lang in ("ro", "en")},
        "evidence_dims": [r[0] for r in conn.execute(
            "SELECT DISTINCT dim_column_name FROM dimensions WHERE matrix_code = ? ORDER BY 1",
            [code]).fetchall()],
        "context": pctx, "kpi_check": kpi, "kpi_table": kpi_table,
        "grain_file_status": grain_guard.file_status(code),
        "grain_check_max_rows": grain_guard.GRAIN_CHECK_MAX_ROWS,
        "generation": generation.summary(), "contract": dq.CONTRACT,
        "period_bounds": _period_bounds(conn, code, rename.get(time_col, time_col) if time_col else None),
    }


def _value_type(conn, code, column):
    """DuckDB type of the value column: CSV exports print DOUBLE as Python floats."""
    from app.config import PARQUET_DIR
    for name, typ, *_ in conn.execute("DESCRIBE SELECT * FROM read_parquet(?)",
                                      [str(PARQUET_DIR / f"{code}.parquet")]).fetchall():
        if name == column:
            return typ
    return None


def _en_labels(conn, code, file_dims):
    """The RO -> EN label maps CSV/XLSX exports apply for lang=en (differences only)."""
    from app.services.export import load_value_maps
    maps = load_value_maps(conn, code, file_dims)
    return {c: {ro: en for ro, en in m.items() if en != ro} for c, m in maps.items()
            if any(en != ro for ro, en in m.items())}


def _period_bounds(conn, code, column):
    """/options' period_bounds for the time column (first/last period with data)."""
    if not column:
        return None
    from app.services.data_query import QueryError, dimension_values
    try:
        return dimension_values(conn, code, column, limit=1).get("period_bounds")
    except QueryError:
        return None


# ------------------------------------------------------------------ site

def assemble_site(out: Path, build: dict) -> dict:
    """The page assets next to the data: app/static, view profiles, and a
    config.js that switches the frontend to static mode."""
    import shutil
    from app.config import CORPUS_DIR
    static = REPO / "app" / "static"
    n = 0
    for src in static.rglob("*"):
        if src.is_file() and "_obsolete" not in src.parts and src.name != ".DS_Store":
            dst = out / src.relative_to(static)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    vp = CORPUS_DIR / "view-profiles"
    if vp.exists():
        shutil.copytree(vp, out / "view-profiles", dirs_exist_ok=True)
    gen = (build.get("generation") or {}).get("id")
    (out / "js" / "config.js").write_text(
        "// generated by scripts/build-static.py\n"
        "window.TEMPO_CONFIG = " + json.dumps({"mode": "static", "generation": gen,
                                               "commit": build.get("commit")}) + ";\n",
        encoding="utf-8")
    return {"assets": n}


# ------------------------------------------------------------------ main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--codes", help="comma-separated dataset codes (default: every served dataset)")
    ap.add_argument("--limit", type=int, help="first N served datasets (debug)")
    ap.add_argument("--partition-rows", type=int, default=PARTITION_ROWS)
    ap.add_argument("--max-query-bytes", type=int, default=MAX_QUERY_BYTES)
    ap.add_argument("--no-record", action="store_true",
                    help="data and policies only (parity tests): no recorded API, search or site")
    ap.add_argument("--base-url", default="", help="public origin, e.g. https://ins.gov2.ro")
    a = ap.parse_args(argv)
    from app.config import MAX_DATA_ROWS, LARGE_DATASET_THRESHOLD, EXPORT_MAX_ROWS
    from app.services.export import xlsx_row_limit
    from app.db import get_conn
    from app.services import generation
    out = Path(a.out)
    if "corpus" in out.resolve().parts:
        ap.error("--out must not be inside a corpus directory")
    conn = get_conn()
    codes = a.codes.split(",") if a.codes else served_codes(conn)
    if a.limit:
        codes = codes[:a.limit]
    t0 = time.time()
    stats = {"datasets": 0, "rows": 0, "data_bytes": 0, "partitioned": []}
    for i, code in enumerate(codes, 1):
        d = export_data(conn, code, out, a.partition_rows)
        gz_json(export_policy(conn, code), out / "policy" / f"{code}.json.gz")
        stats["datasets"] += 1
        stats["rows"] += d["rows"]
        stats["data_bytes"] += d["bytes"]
        if d["partitioned"]:
            stats["partitioned"].append(code)
        if i % 200 == 0:
            print(f"  {i}/{len(codes)} ({time.time() - t0:.0f}s)", flush=True)
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                                text=True).stdout.strip() or None
    except Exception:
        commit = None
    build = {"schema": SCHEMA, "generation": generation.summary(), "commit": commit,
             "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "max_data_rows": MAX_DATA_ROWS, "large_dataset_threshold": LARGE_DATASET_THRESHOLD,
             "partition_rows": a.partition_rows, "max_query_bytes": a.max_query_bytes,
             "xlsx_row_limit": xlsx_row_limit(), "export_row_limit": EXPORT_MAX_ROWS or None, **stats}
    if not a.no_record:
        rec = static_api.record(conn, out, codes, all_datasets=not (a.codes or a.limit),
                                base_url=a.base_url)
        srch = static_api.export_search(conn, out)
        site = assemble_site(out, build)
        build.update(recorded=rec, search=srch, site=site)
    _json_dump(build, out / "build.json")
    print(json.dumps({k: v for k, v in build.items() if k != "partitioned"}
                     | {"partitioned": len(stats["partitioned"])}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
