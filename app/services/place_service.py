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
