"""Place profile service — resolves places and aggregates KPI/dataset data."""
import json
import unicodedata
import re
from functools import lru_cache
from pathlib import Path
from app.db import get_conn
from app.config import PARQUET_DIR
from app.services import aggregation_policy as agg

import duckdb as _duckdb

_KPI_CONFIG_PATH = Path(__file__).parent.parent / "static" / "data" / "place_kpi_config.json"
_kpi_config: dict | None = None

# Display cap: the most recent N periods are kept (then returned ascending).
SERIES_CAP = 30

# Stable mapping: county geo_name_clean → development region slug
COUNTY_REGION = {
    "Alba": "centru", "Brasov": "centru", "Covasna": "centru",
    "Harghita": "centru", "Mures": "centru", "Sibiu": "centru",
    "Bacau": "nord-est", "Botosani": "nord-est", "Iasi": "nord-est",
    "Neamt": "nord-est", "Suceava": "nord-est", "Vaslui": "nord-est",
    "Braila": "sud-est", "Buzau": "sud-est", "Constanta": "sud-est",
    "Galati": "sud-est", "Tulcea": "sud-est", "Vrancea": "sud-est",
    "Arges": "sud-muntenia", "Calarasi": "sud-muntenia", "Dambovita": "sud-muntenia",
    "Giurgiu": "sud-muntenia", "Ialomita": "sud-muntenia", "Prahova": "sud-muntenia",
    "Teleorman": "sud-muntenia",
    "Dolj": "sud-vest-oltenia", "Gorj": "sud-vest-oltenia", "Mehedinti": "sud-vest-oltenia",
    "Olt": "sud-vest-oltenia", "Valcea": "sud-vest-oltenia",
    "Arad": "vest", "Caras-Severin": "vest", "Hunedoara": "vest", "Timis": "vest",
    "Bihor": "nord-vest", "Bistrita-Nasaud": "nord-vest", "Cluj": "nord-vest",
    "Maramures": "nord-vest", "Satu Mare": "nord-vest", "Salaj": "nord-vest",
    "Ilfov": "bucuresti-ilfov", "Municipiul Bucuresti": "bucuresti-ilfov",
}

# Canonical region display names keyed by slug
REGION_NAMES = {
    "nord-vest": "Nord-Vest", "centru": "Centru", "nord-est": "Nord-Est",
    "sud-est": "Sud-Est", "sud-muntenia": "Sud-Muntenia",
    "sud-vest-oltenia": "Sud-Vest Oltenia", "vest": "Vest",
    "bucuresti-ilfov": "București-Ilfov",
}


def slugify(name: str) -> str:
    """Normalize a place name to a URL slug."""
    s = re.sub(r'^(Regiunea|REGIUNEA)\s+', '', name.strip(), flags=re.IGNORECASE)
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def _load_kpi_config() -> dict:
    global _kpi_config
    if _kpi_config is None:
        _kpi_config = json.loads(_KPI_CONFIG_PATH.read_text(encoding="utf-8"))
    return _kpi_config


def resolve_place(place_type: str, slug: str, *, conn=None) -> dict | None:
    """Resolve a (type, slug) pair to canonical place info.

    Returns:
        {name, type, slug, ref_area_values: [str, ...], parent_slug: str|None, parent_name: str|None}
        or None if not found.
    """
    if conn is None:
        conn = get_conn()

    rows = conn.execute("""
        SELECT DISTINCT p.geo_name_clean
        FROM dimension_options_parsed p
        WHERE p.dim_type = 'geo' AND p.geo_level = ?
    """, [place_type]).fetchall()

    matches = []
    for (name,) in rows:
        if name and slugify(name) == slug:
            matches.append(name)

    if not matches:
        return None

    # Pick shortest name as canonical (avoids "Regiunea NORD-VEST" prefix variants)
    canonical = min(matches, key=len)

    parent_slug = None
    if place_type == "county":
        parent_slug = COUNTY_REGION.get(canonical)

    return {
        "name": canonical,
        "type": place_type,
        "slug": slug,
        "ref_area_values": matches,
        "parent_slug": parent_slug,
        "parent_name": REGION_NAMES.get(parent_slug) if parent_slug else None,
    }


_COLLAPSE_NAMES = {
    "SEX": ("sexe", "sexes"),
    "RESIDENCE": ("medii de rezidență", "residence areas"),
    "AGE": ("grupe de vârstă", "age groups"),
    "REF_AREA": ("unități teritoriale", "areas"),
}
_DIM_TYPES = {"SEX": "gender", "RESIDENCE": "residence", "AGE": "age",
              "UNIT_MEASURE": "unit", "REF_AREA": "geo", "TIME_PERIOD": "time"}
# Per-kind display unit of a *change* (compute_change unit: percent | points)
_CHANGE_UNIT = {
    "count": ("percent", "percent"),
    "currency": ("percent", "percent"),
    "percent_rate": ("points", "percentage_points"),
    "per_mille_rate": ("points", "per_mille_points"),
}


def _norm_ref(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s).strip().lower()


def find_kpi_spec(place_type: str, ref: str) -> tuple[dict | None, bool]:
    """Resolve a KPI by key, label (RO/EN) or legacy alias.

    Returns (spec, via_alias). Old bookmarked labels such as the pre-FIX-06
    "Rata șomajului BIM" keep working and resolve to the renamed KPI.
    """
    want = _norm_ref(ref)
    for spec in _kpi_specs(place_type):
        if want in (_norm_ref(spec["key"]), _norm_ref(spec["label"]),
                    _norm_ref(spec.get("label_en", ""))):
            return spec, False
    for spec in _kpi_specs(place_type):
        if want in {_norm_ref(a) for a in spec.get("aliases", [])}:
            return spec, True
    return None, False


def _kpi_specs(place_type: str) -> list[dict]:
    return [s for s in _load_kpi_config().get(place_type, [])
            if isinstance(s, dict) and "parquet" in s]


def _sql_list(values) -> str:
    return ",".join("'" + str(v).replace("'", "''") + "'" for v in values)


@lru_cache(maxsize=256)
def _parquet_info(path: str, mtime: float) -> dict:
    """Columns, distinct dimension values and last period of a place parquet."""
    con = _duckdb.connect()
    try:
        cols = [r[0] for r in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [path]).fetchall()]
        values = {}
        for c in cols:
            if c in ("OBS_VALUE", "TIME_PERIOD", "REF_AREA"):
                continue
            values[c] = [r[0] for r in con.execute(
                f'SELECT DISTINCT "{c}" FROM read_parquet(?) ORDER BY 1', [path]).fetchall()]
        last = con.execute(
            "SELECT MAX(LEFT(CAST(TIME_PERIOD AS VARCHAR),4)) FROM read_parquet(?) "
            "WHERE OBS_VALUE IS NOT NULL", [path]).fetchone()[0]
        areas = [r[0] for r in con.execute(
            "SELECT DISTINCT REF_AREA FROM read_parquet(?)", [path]).fetchall()]
    except Exception:
        return {"cols": [], "values": {}, "last": None, "areas": []}
    finally:
        con.close()
    return {"cols": cols, "values": values, "last": last, "areas": areas}


def _info(path: Path) -> dict:
    return _parquet_info(str(path), path.stat().st_mtime)


def _decide_for(spec: dict, info: dict, areas: list[str], geo_level: str,
                collapse_areas: bool):
    """FIX-02 decision for combining the rows a KPI needs into one number."""
    dims = []
    for col, vals in info["values"].items():
        dims.append({
            "dim_column_name": col, "dim_type": _DIM_TYPES.get(col),
            "options": [{"label": str(v), "sdmx_value": str(v), "parsed": {}} for v in vals],
        })
    dims.append({
        "dim_column_name": "REF_AREA", "dim_type": "geo",
        "options": [{"label": a, "sdmx_value": a, "parsed": {"geo_level": geo_level}}
                    for a in areas],
    })
    dims.append({"dim_column_name": "TIME_PERIOD", "dim_type": "time", "options": []})
    weights = None
    w = spec.get("weights")
    if w and (PARQUET_DIR / w["parquet"]).exists():
        weights = agg.WeightSpec(source_code=w["source_code"], aligned=True,
                                 note=w.get("note", ""))
    return agg.decide(
        dimensions=dims, effective={}, group_by=() if collapse_areas else ("REF_AREA",),
        filters={k: [v] for k, v in (spec.get("filters") or {}).items()},
        measure=spec.get("measure", "additive"),
        weights=weights, allow_approximation=bool(spec.get("allow_approximation")),
        # Curated partitions only make sense for additive measures; rates rely on
        # the sex/residence metadata verdict and weights/approximation below.
        declared_partitions=(spec.get("partitions", [])
                             if spec.get("measure", "additive") == "additive" else []))


def _series_query(spec: dict, parquet: Path, areas: list[str] | None,
                  decision) -> list[tuple]:
    """Rows (year, value, n_obs, n_weighted) for the decided combination.

    The newest SERIES_CAP years are selected first, in *descending* order, so a
    long history never hides the latest observation; callers reverse to ascending.
    """
    where = ["OBS_VALUE IS NOT NULL",
             "TRY_CAST(LEFT(CAST(TIME_PERIOD AS VARCHAR), 4) AS INTEGER) IS NOT NULL"]
    if areas is not None:
        where.append(f"REF_AREA IN ({_sql_list(areas)})")
    for col, vals in decision.effective_filters.items():
        if col == "REF_AREA":
            continue
        where.append(f'"{col}" IN ({_sql_list(vals)})')
    where_sql = " AND ".join(where)
    year = "LEFT(CAST(v.TIME_PERIOD AS VARCHAR), 4)"
    params: list = [str(parquet)]
    if decision.agg_func == "WEIGHTED_AVG":
        w = spec["weights"]
        join = ", ".join(f'"{c}"' for c in ["REF_AREA", "TIME_PERIOD"] + w["join"])
        params.append(str(PARQUET_DIR / w["parquet"]))
        sql = f"""
            WITH v AS (SELECT * FROM read_parquet(?) WHERE {where_sql}),
                 w AS (SELECT {join}, SUM(OBS_VALUE) AS wt
                       FROM read_parquet(?) WHERE OBS_VALUE IS NOT NULL GROUP BY {join})
            SELECT {year} AS year,
                   SUM(v.OBS_VALUE * w.wt) / NULLIF(SUM(w.wt), 0) AS value,
                   COUNT(v.OBS_VALUE) AS n_obs, COUNT(w.wt) AS n_w
            FROM v LEFT JOIN w USING ({join})
            GROUP BY 1 ORDER BY 1 DESC LIMIT {SERIES_CAP * 2}"""
    else:
        fn = "AVG" if decision.agg_func == "AVG" else "SUM"
        sql = f"""
            SELECT {year} AS year, {fn}(v.OBS_VALUE) AS value,
                   COUNT(v.OBS_VALUE) AS n_obs, COUNT(v.OBS_VALUE) AS n_w
            FROM read_parquet(?) v WHERE {where_sql}
            GROUP BY 1 ORDER BY 1 DESC LIMIT {SERIES_CAP * 2}"""
    con = _duckdb.connect()
    try:
        return con.execute(sql, params).fetchall()
    except Exception:
        return []
    finally:
        con.close()


def _complete_series(rows: list[tuple]) -> list[dict]:
    """Keep only periods whose coverage matches the fullest period, newest
    SERIES_CAP of them, ascending. A period with a missing group (a sex, an
    urban/rural row, a county, or weights) is *absent*, never summed as if the
    missing part were zero."""
    if not rows:
        return []
    expected = max(r[2] for r in rows)
    ok = [r for r in rows if r[1] is not None and r[2] == expected and r[3] == r[2]]
    ok.sort(key=lambda r: r[0], reverse=True)          # newest first ...
    ok = ok[:SERIES_CAP]
    return [{"year": r[0], "value": r[1]} for r in reversed(ok)]   # ... returned ascending


def _method_info(spec: dict, decision) -> dict:
    cols = [d["column"] for d in decision.dimensions
            if d.get("treatment") in ("partition", "level", "explicit_set")]
    ro = ", ".join(_COLLAPSE_NAMES.get(c, (c, c))[0] for c in cols)
    en = ", ".join(_COLLAPSE_NAMES.get(c, (c, c))[1] for c in cols)
    m = decision.method
    src = spec.get("weights", {}).get("source_code") if decision.weights_source else None
    if decision.outcome == agg.UNAVAILABLE:
        note_ro = note_en = None
    elif m == "weighted_mean":
        note_ro = (f"Medie ponderată pe {ro} cu populația rezidentă la 1 ianuarie ({src}), "
                   f"folosită ca aproximare a populației de la 1 iulie; pe an.")
        note_en = (f"Mean over {en} weighted by the 1 January resident population ({src}), "
                   f"used as a proxy for the 1 July population; per year.")
    elif m == "unweighted_mean":
        note_ro = (f"APROXIMARE: medie simplă a valorilor pe {ro}; nu sunt disponibile "
                   f"ponderi, deci nu este rata oficială pentru total.")
        note_en = (f"APPROXIMATION: unweighted mean of the {en} values; no weights are "
                   f"available, so this is not the official rate for the total.")
    elif m == "sum_partition":
        note_ro = f"Sumă pe {ro}." if ro else "Sumă."
        note_en = f"Sum over {en}." if en else "Sum."
    else:
        note_ro = note_en = "Valoare publicată." if m != "none" else None
        if note_ro:
            note_en = "Published value."
    return {"code": m, "approximation": decision.approximation,
            "outcome": decision.outcome, "reason": decision.reason,
            "weights_source": src, "note": note_ro, "note_en": note_en}


def _change_for(kind: str, series: list[dict]) -> dict:
    unit, display = _CHANGE_UNIT.get(kind, ("percent", "percent"))
    ch = agg.compute_change([(r["year"], r["value"]) for r in series], unit=unit)
    ch["display_unit"] = display
    return ch


def _kpi_identity(spec: dict) -> dict:
    return {
        "key": spec["key"],
        "label": spec["label"], "label_en": spec.get("label_en", spec["label"]),
        "category": spec.get("category", ""),
        "unit": spec.get("unit", ""), "unit_en": spec.get("unit_en", spec.get("unit", "")),
        "unit_kind": spec.get("unit_kind", "count"),
        "source": {"code": spec.get("source_code"), "dataset": Path(spec["parquet"]).stem,
                   "title": spec.get("source_title"), "title_en": spec.get("source_title_en")},
        "definition": spec.get("definition"), "definition_en": spec.get("definition_en"),
    }


def _resolve_series(spec: dict, areas: list[str] | None, geo_level: str, *,
                    collapse: bool):
    """Run the decided query. `areas=None` means every area in the parquet."""
    parquet = PARQUET_DIR / spec["parquet"]
    if not parquet.exists():
        return [], None, None
    info = _info(parquet)
    present = info["areas"] if areas is None else [a for a in areas if a in info["areas"]]
    if not collapse and len(present) > 1:
        present = [min(present, key=len)]
    if not present:
        return [], None, info["last"]
    decision = _decide_for(spec, info, present, geo_level, collapse)
    if not decision.available:
        return [], decision, info["last"]
    rows = _series_query(spec, parquet, present, decision)
    return _complete_series(rows), decision, info["last"]


def get_place_kpi_report(place_type: str, slug: str, *, conn=None) -> dict:
    """KPI cards for a place plus the indicators deliberately left out.

    {kpis: [...], omitted: [{key, label, label_en, reason, note}]}
    Each KPI carries identity (key/label/source/definition), the observation
    `period`, `unit`, the combination `method`, an explicit `change` object and
    the FIX-02 `provenance` payload.
    """
    specs = _kpi_specs(place_type)
    if not specs:
        return {"kpis": [], "omitted": []}
    place = resolve_place(place_type, slug, conn=conn)
    if not place:
        return {"kpis": [], "omitted": []}

    kpis, omitted = [], []
    for spec in specs:
        ident = _kpi_identity(spec)
        if spec.get("suppress"):
            omitted.append({"key": spec["key"], "label": spec["label"],
                            "label_en": spec.get("label_en"), "reason": spec["suppress"],
                            "note": spec.get("suppress_note")})
            continue
        series, decision, last = _resolve_series(
            spec, place["ref_area_values"], place_type, collapse=False)
        if not series:
            reason = decision.reason if decision is not None and not decision.available \
                else "no_data"
            omitted.append({"key": spec["key"], "label": spec["label"],
                            "label_en": spec.get("label_en"), "reason": reason, "note": None})
            continue

        latest = series[-1]
        change = _change_for(ident["unit_kind"], series)
        method = _method_info(spec, decision)
        prov = agg.provenance(decision, source_code=spec.get("source_code"),
                              period=latest["year"], unit=spec.get("unit"),
                              comparison=agg.comparison_of(change))
        value = latest["value"]
        kpis.append({
            **ident,
            "value": round(value, 1) if value is not None else None,
            "period": latest["year"],
            "source_latest_period": last,
            "stale": bool(last and latest["year"] < last),
            # back-compat numeric delta; its unit/basis is in `change`
            "change_yoy": change["value"] if change["status"] == "ok" else None,
            "change": change,
            "method": method,
            "provenance": prov,
            "sparkline": series,
        })
    return {"kpis": kpis, "omitted": omitted}


def get_place_kpis(place_type: str, slug: str, *, conn=None) -> list[dict]:
    """Curated KPI cards for a place (see get_place_kpi_report). Localities
    have no config and return []; indicators without defensible data are
    omitted from this list (and named in the report's `omitted`)."""
    return get_place_kpi_report(place_type, slug, conn=conn)["kpis"]


def _get_county_population(county_name: str) -> float | None:
    """Get latest total population for a county from POP105A_judete_grupe parquet."""
    parquet_path = PARQUET_DIR / "POP105A_judete_grupe.parquet"
    if not parquet_path.exists():
        return None
    con = _duckdb.connect()
    rows: list = []
    try:
        rows = con.execute("""
            SELECT SUM(OBS_VALUE) as pop
            FROM read_parquet(?)
            WHERE REF_AREA = ?
            GROUP BY TIME_PERIOD
            ORDER BY TIME_PERIOD DESC
            LIMIT 1
        """, [str(parquet_path), county_name]).fetchall()
    finally:
        con.close()
    return rows[0][0] if rows else None


def get_place_peers(place_type: str, slug: str, *, conn=None) -> dict:
    """Return peer groups for comparison.

    Returns:
        {
          same_region: [{slug, name, type}, ...],
          similar_size: [{slug, name, type}, ...]
        }
    """
    if conn is None:
        conn = get_conn()

    place = resolve_place(place_type, slug, conn=conn)
    if not place:
        return {"same_region": [], "similar_size": []}

    if place_type != "county":
        all_places = conn.execute("""
            SELECT DISTINCT geo_name_clean FROM dimension_options_parsed
            WHERE dim_type = 'geo' AND geo_level = ?
        """, [place_type]).fetchall()
        siblings = [
            {"slug": slugify(name), "name": name, "type": place_type}
            for (name,) in all_places
            if name and slugify(name) != slug
        ][:5]
        return {"same_region": siblings, "similar_size": []}

    region_slug = place["parent_slug"]
    same_region = []
    if region_slug:
        region_counties = [
            name for name, reg in COUNTY_REGION.items() if reg == region_slug
        ]
        same_region = [
            {"slug": slugify(name), "name": name, "type": "county"}
            for name in region_counties
            if slugify(name) != slug
        ][:5]

    canonical = place["name"]
    this_pop = _get_county_population(canonical)
    similar_size = []
    if this_pop:
        all_counties = conn.execute("""
            SELECT DISTINCT geo_name_clean FROM dimension_options_parsed
            WHERE dim_type = 'geo' AND geo_level = 'county'
        """).fetchall()
        pop_list = []
        for (name,) in all_counties:
            if not name or name == canonical:
                continue
            p = _get_county_population(name)
            if p:
                pop_list.append((abs(p - this_pop), name))
        pop_list.sort()
        similar_size = [
            {"slug": slugify(name), "name": name, "type": "county"}
            for _, name in pop_list[:3]
        ]

    return {"same_region": same_region, "similar_size": similar_size}


def _baseline_meta(spec: dict, decision, series: list[dict], scope: str,
                   n_areas: int | None) -> dict:
    method = _method_info(spec, decision) if decision is not None else None
    return {
        "scope": scope, "areas": n_areas,
        "period": series[-1]["year"] if series else None,
        "unit": spec.get("unit"),
        "available": bool(series),
        "reason": None if series else (decision.reason if decision is not None else "no_data"),
        "method": method,
        "approximation": bool(decision.approximation) if decision is not None else False,
    }


def get_kpi_baselines(place_type: str, slug: str, kpi_label: str) -> dict:
    """National and region baseline series for one KPI.

    `kpi_label` may be the key, the RO/EN label or a legacy alias (e.g. the old
    "Rata șomajului BIM"). Returns
      {national: [{year, value}, ...], region: [...], kpi: {...},
       national_meta, region_meta}
    Series are the newest SERIES_CAP periods, ascending; the baselines use the
    same decision/weights policy as the place series, so an approximation or
    weighted mean is declared in `*_meta.method`.
    """
    spec, via_alias = find_kpi_spec(place_type, kpi_label)
    if not spec or spec.get("suppress"):
        return {"national": [], "region": [], "kpi": None,
                "national_meta": None, "region_meta": None}

    national, n_dec, _ = _resolve_series(spec, None, place_type, collapse=True)
    parquet = PARQUET_DIR / spec["parquet"]
    n_areas = len(_info(parquet)["areas"]) if parquet.exists() else None

    region_series, r_dec, r_count = [], None, None
    if place_type == "county":
        place = resolve_place(place_type, slug)
        if place and place["parent_slug"]:
            region_counties = [name for name, reg in COUNTY_REGION.items()
                               if reg == place["parent_slug"]]
            region_series, r_dec, _ = _resolve_series(
                spec, region_counties, "county", collapse=True)
            r_count = len(region_counties)

    return {
        "national": national,
        "region": region_series,
        "kpi": {"key": spec["key"], "label": spec["label"], "label_en": spec.get("label_en"),
                "unit": spec.get("unit"), "unit_kind": spec.get("unit_kind"),
                "matched_legacy_alias": via_alias},
        "national_meta": _baseline_meta(spec, n_dec, national, "national", n_areas),
        "region_meta": _baseline_meta(spec, r_dec, region_series, "region", r_count)
        if place_type == "county" else None,
    }


def get_place_datasets(place_type: str, slug: str, *, conn=None) -> list[dict]:
    """Return all datasets that have data for this place."""
    if conn is None:
        conn = get_conn()

    place = resolve_place(place_type, slug, conn=conn)
    if not place:
        return []

    rows = conn.execute("""
        SELECT DISTINCT m.matrix_code, m.matrix_name, m.context_code, c.context_name
        FROM dimension_options o
        JOIN dimension_options_parsed p ON o.nom_item_id = p.nom_item_id
        JOIN dimensions d ON o.dimension_id = d.dimension_id
        JOIN matrices m ON d.matrix_code = m.matrix_code
        LEFT JOIN contexts c ON m.context_code = c.context_code
        WHERE p.dim_type = 'geo'
          AND p.geo_level = ?
          AND p.geo_name_clean IN ({})
        ORDER BY m.context_code, m.matrix_name
    """.format(",".join("?" * len(place["ref_area_values"]))),
        [place_type] + place["ref_area_values"]
    ).fetchall()

    return [
        {
            "code": r[0],
            "title": r[1],
            "context_code": r[2],
            "category": r[3] or "Altele",
            "has_data": True,
        }
        for r in rows
    ]
