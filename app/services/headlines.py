"""
Headline indicators for the landing page.
Queries specific parquet files to extract latest values for curated KPI cards.
Results are cached in memory with a configurable TTL.

headline_config.json describes each card as a *slice and a method*, not as SQL:

    code          parquet / matrix code
    measure       additive | average | index | rate  (non-additive = the last 3)
    method        aggregate_row | single_row | sum_partition  (what is expected)
    slice         {column: [exact data values]} pins
    aggregates    columns whose pinned value is a curator-declared aggregate row
    sum_over      columns summed over a curator-declared complete disjoint
                  partition (additive measures only)
    transform     optional, "minus_100" (index with previous period = 100)
    comparison    optional, "previous_period" to force the previous point
    verification  how the card was checked against source rows
    omitted       reason string: the card is intentionally not shown

SQL is generated here, after aggregation_policy.decide() has approved the slice.
Every other dimension must be a singleton in the data; anything else is
unavailable rather than silently summed. Cards carry the shared `provenance`
block (see aggregation_policy) plus a structured `change` object; the legacy
fields (value, prev_value, change_pct, ...) are unchanged in meaning except that
the comparison now uses the same period last year for monthly/quarterly series.
"""
import json
import os
import time
import logging

from app.services import aggregation_policy as ap

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load configuration from JSON
# ---------------------------------------------------------------------------
_config_path = os.path.join(os.path.dirname(__file__), "headline_config.json")
with open(_config_path, "r", encoding="utf-8") as _f:
    HEADLINE_CONFIG = json.load(_f)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_cache = {"data": None, "ts": 0}
CACHE_TTL = 3600  # 1 hour

TIME_COL = "TIME_PERIOD"


def _dim_type(col: str) -> str:
    if col == "UNIT_MEASURE":
        return "unit"
    if col == "SEX":
        return "gender"
    if col == "RESIDENCE":
        return "residence"
    if col.startswith("REF_AREA"):
        return "geo"
    return "indicator"


def resolve_indicator(conn, parquet_dir: str, ind: dict, lang: str = "ro"):
    """Resolve one config entry to (card | None, status).

    status is 'ok', 'omitted', 'missing_parquet' or an unavailable reason code
    from aggregation_policy.
    """
    if ind.get("omitted"):
        return None, "omitted"
    path = os.path.join(parquet_dir, f"{ind['code']}.parquet")
    if not os.path.exists(path):
        return None, "missing_parquet"

    cols = [r[0] for r in conn.execute(
        "DESCRIBE SELECT * FROM read_parquet(?)", [path]).fetchall()]
    value_col = "OBS_VALUE" if "OBS_VALUE" in cols else "value"
    if TIME_COL not in cols or value_col not in cols:
        return None, "unverified_structure"
    dim_cols = [c for c in cols if c not in (TIME_COL, value_col)]

    slice_ = ind.get("slice") or {}
    sum_over = list(ind.get("sum_over") or [])
    unknown = [c for c in list(slice_) + sum_over if c not in dim_cols]
    if unknown:
        return None, "unverified_structure"

    # Data-grounded options per dimension
    options, effective = {}, {}
    dimensions = []
    for c in dim_cols:
        vals = [r[0] for r in conn.execute(
            f'SELECT DISTINCT "{c}" FROM read_parquet(?) WHERE "{c}" IS NOT NULL',
            [path]).fetchall()]
        opts = [{"label": str(v), "sdmx_value": str(v), "parsed": {}} for v in vals]
        dimensions.append({"dim_column_name": c, "dim_type": _dim_type(c),
                           "options": opts})
        effective[c] = [(o, o["label"]) for o in opts]
        # Any dimension the card neither pins nor declares must be a singleton.
        if (c not in slice_ and c not in sum_over and len(vals) > 1
                and _dim_type(c) != "unit"):
            return None, "unverified_structure"

    measure = "additive" if ind.get("measure", "additive") == "additive" else "non_additive"
    decision = ap.decide(
        dimensions=[{"dim_column_name": TIME_COL, "dim_type": "time", "options": []}]
        + dimensions,
        effective=effective, group_by=[TIME_COL], filters=slice_,
        measure=measure, declared_partitions=sum_over,
        declared_aggregates=ind.get("aggregates"))
    if not decision.available:
        return None, decision.reason

    # SQL is built only from an approved decision.
    where, params = [], [path]
    for c, vals in decision.effective_filters.items():
        where.append(f'"{c}" IN ({",".join("?" * len(vals))})')
        params.extend(vals)
    sql = (f'SELECT "{TIME_COL}", {decision.agg_func}("{value_col}") AS val, '
           f'COUNT("{value_col}") AS n FROM read_parquet(?) '
           + (("WHERE " + " AND ".join(where) + " ") if where else "")
           + f'GROUP BY "{TIME_COL}" ORDER BY "{TIME_COL}" DESC')
    rows = [(r[0], float(r[1]), r[2])
            for r in conn.execute(sql, params).fetchall() if r[1] is not None]
    if not rows:
        return None, "no_data"
    if decision.method in ("aggregate_row", "single_row"):
        if rows[0][2] != 1:
            return None, "ambiguous_slice"
        rows = [r for r in rows if r[2] == 1]

    if ind.get("transform") == "minus_100":
        rows = [(p, round(v - 100, 6), n) for p, v, n in rows]

    chrono = [(str(p), v) for p, v, _ in reversed(rows)]
    latest_period, latest_value = chrono[-1]
    change_unit = "points" if ind.get("measure") == "rate" else "percent"
    change = ap.compute_change(
        chrono, unit=change_unit,
        prefer_yoy=ind.get("comparison") != "previous_period")
    prev_value = None
    if change["from_period"] is not None:
        prev_value = next(v for p, v in chrono if p == change["from_period"])

    unit = ind.get(f"unit_{lang}", "")
    return {
        "code": ind["code"],
        "label": ind.get(f"label_{lang}", ind["code"]),
        "period": latest_period,
        "value": latest_value,
        "prev_value": prev_value,
        "change_pct": (change["value"] if change["unit"] == "percent"
                       and change["status"] == "ok" else None),
        "change": change,
        "unit": unit,
        "format": ind.get("format", "number"),
        "sparkline": [v for _, v in chrono[-12:]],
        "provenance": ap.provenance(
            decision, source_code=ind["code"], period=latest_period, unit=unit,
            comparison=ap.comparison_of(change)),
    }, "ok"


def compute_headlines(conn, parquet_dir: str, lang: str = "ro") -> list:
    """Compute headline indicator values from parquet files.

    Returns a list of theme dicts, each containing resolved indicator values.
    Results are cached for CACHE_TTL seconds.
    """
    now = time.time()
    cache_key = f"{lang}_{parquet_dir}"

    # Check cache
    if _cache.get(cache_key) and now - _cache.get(f"{cache_key}_ts", 0) < CACHE_TTL:
        return _cache[cache_key]

    results = []
    theme_key = f"theme_{lang}"

    for theme_cfg in HEADLINE_CONFIG:
        theme = {
            "theme": theme_cfg["theme"],
            "theme_label": theme_cfg.get(theme_key, theme_cfg["theme"]),
            "context_code": theme_cfg.get("context_code"),
            "icon": theme_cfg.get("icon"),
            "indicators": [],
        }

        for ind in theme_cfg["indicators"]:
            try:
                card, status = resolve_indicator(conn, parquet_dir, ind, lang)
            except Exception as e:
                log.warning("Headline query failed for %s: %s", ind["code"], e)
                continue
            if card is None:
                log.info("Headline %s not shown: %s", ind["code"], status)
                continue
            theme["indicators"].append(card)

        if theme["indicators"]:
            results.append(theme)

    # Store in cache
    _cache[cache_key] = results
    _cache[f"{cache_key}_ts"] = now

    return results
