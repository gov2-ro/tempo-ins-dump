"""Place profile service — resolves places and aggregates KPI/dataset data."""
import json
import unicodedata
import re
from pathlib import Path
from app.db import get_conn
from app.config import PARQUET_DIR

import duckdb as _duckdb

_KPI_CONFIG_PATH = Path(__file__).parent.parent / "static" / "data" / "place_kpi_config.json"
_kpi_config: dict | None = None

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


def _query_kpi_series(parquet_path: Path, ref_area_values: list[str],
                      extra_filters: dict, agg_func: str) -> list[dict]:
    """Query a parquet for a place's annual time series.

    Returns list of {year: str, value: float} sorted ascending by year.
    Averages/sums over any non-REF_AREA, non-TIME_PERIOD dims.
    Extra filter values of None mean IS NULL.
    """
    if not parquet_path.exists():
        return []

    con = _duckdb.connect()
    where_parts = [
        "REF_AREA IN ({})".format(",".join(f"'{v}'" for v in ref_area_values))
    ]
    for col, val in extra_filters.items():
        if val is None:
            where_parts.append(f"{col} IS NULL")
        else:
            safe_val = str(val).replace("'", "''")
            where_parts.append(f"{col} = '{safe_val}'")

    query = f"""
        SELECT
            LEFT(CAST(TIME_PERIOD AS VARCHAR), 4) AS year,
            {agg_func}(OBS_VALUE) AS value
        FROM read_parquet('{parquet_path}')
        WHERE {" AND ".join(where_parts)}
          AND TRY_CAST(LEFT(CAST(TIME_PERIOD AS VARCHAR), 4) AS INTEGER) IS NOT NULL
        GROUP BY 1
        ORDER BY 1 ASC
        LIMIT 30
    """
    try:
        rows = con.execute(query).fetchall()
    except Exception:
        return []

    return [{"year": r[0], "value": r[1]} for r in rows if r[1] is not None]


def get_place_kpis(place_type: str, slug: str, *, conn=None) -> list[dict]:
    """Return curated KPI series for a place.

    Each entry:
      {label, unit, category, value: float|None, change_yoy: float|None,
       sparkline: [{year, value}, ...]}

    For localities (empty config), returns [].
    Missing data for a KPI is omitted from the list.
    """
    config = _load_kpi_config()
    kpi_specs = config.get(place_type, [])
    if not kpi_specs:
        return []

    place = resolve_place(place_type, slug, conn=conn)
    if not place:
        return []

    results = []
    for spec in kpi_specs:
        # Skip _notes key if present
        if not isinstance(spec, dict) or "parquet" not in spec:
            continue
        parquet_path = PARQUET_DIR / spec["parquet"]
        series = _query_kpi_series(
            parquet_path,
            place["ref_area_values"],
            spec.get("extra_filters", {}),
            spec.get("agg_func", "AVG"),
        )
        if not series:
            continue

        latest = series[-1]["value"] if series else None
        yoy = None
        if len(series) >= 2 and series[-2]["value"] and series[-1]["value"]:
            prev = series[-2]["value"]
            curr = series[-1]["value"]
            if spec["unit"] in ("%", "‰"):
                yoy = round(curr - prev, 2)
            else:
                yoy = round((curr - prev) / prev * 100, 1) if prev else None

        results.append({
            "label": spec["label"],
            "unit": spec["unit"],
            "category": spec.get("category", ""),
            "value": round(latest, 1) if latest is not None else None,
            "change_yoy": yoy,
            "sparkline": series,
        })

    return results


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
