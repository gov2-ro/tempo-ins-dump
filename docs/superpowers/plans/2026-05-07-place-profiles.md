# Place Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add place profile pages (`/place/county/bihor`, etc.) showing KPI heroes, an indicator grid, and a cross-place comparison chart for all Romanian geographic levels.

**Architecture:** New FastAPI router + service (`app/routers/places.py`, `app/services/place_service.py`) with direct DuckDB + parquet queries; two new vanilla JS pages (`places.html` directory, `place.html` profile) reusing existing ECharts infrastructure.

**Tech Stack:** FastAPI, DuckDB, Parquet (DuckDB SQL), Vanilla JS ES6+, ECharts 5

---

## Environment

Always activate before running Python: `source ~/devbox/envs/240826/bin/activate`

Dev server: `uvicorn app.main:app --reload --port 8080`

---

## Data Findings (read before coding)

- **REF_AREA parquet values** match `geo_name_clean` in `dimension_options_parsed` (e.g., "Bihor", "Municipiul Bucuresti"). Use these string values directly as filter values.
- **Split parquets** are the right ones for county-level KPIs: `SOM103A_judete.parquet`, `POP202B.parquet`, etc. Full parquet filenames (not just matrix codes) go in the config.
- **No "Total" SEX row** in many split parquets — use `AVG(OBS_VALUE) GROUP BY TIME_PERIOD` to average male+female as a proxy for rates.
- **Population**: use `POP105A_judete_grupe.parquet` (5-year age groups × sex), `SUM GROUP BY TIME_PERIOD, REF_AREA`. Verified: Bihor 2025 → 556,606 ✓
- **Region names** in `geo_name_clean` are inconsistent (24 variants for 8 regions). The slug must normalize "Regiunea NORD-VEST", "Regiunea Nord-Vest", etc. all to "nord-vest".
- **`PARQUET_DIR`** resolves to `/Users/pax/devbox/gov2/tempo-ins-dump/data/corpus/parquet` (from `app/config.py`).
- **County→region mapping** has no explicit DB table — hardcode the 42-county mapping in `place_service.py` (stable Romanian administrative data).

---

## File Map

| Action | Path | Role |
|--------|------|------|
| Create | `app/routers/places.py` | 4 routes: directory HTML, profile HTML, list API, profile API |
| Create | `app/services/place_service.py` | All aggregation logic (resolve, kpis, datasets, peers, baselines) |
| Create | `app/static/data/place_kpi_config.json` | Curated KPI spec per geo level |
| Create | `app/static/places.html` | Directory page shell |
| Create | `app/static/place.html` | Profile page shell |
| Create | `app/static/js/places-page.js` | Directory page controller |
| Create | `app/static/js/place-page.js` | Profile page controller (PlaceProfileApp) |
| Create | `tests/test_place_service.py` | Backend service tests |
| Modify | `app/main.py` | Include new router |
| Modify | `app/static/index.html` | Add "Locuri" nav link |
| Modify | `docs/BACKLOG.md` | Add deferred items |

---

## Task 1: KPI Config JSON

Discover and verify real parquet filenames for each KPI, then write the config.

**Files:**
- Create: `app/static/data/app_data/place_kpi_config.json`

- [ ] **Step 1.1: Verify parquet filenames for county KPIs**

Run this discovery script (no edits, read-only):
```bash
source ~/devbox/envs/240826/bin/activate && python -c "
from app.config import PARQUET_DIR
import os, duckdb
con = duckdb.connect()

kpis = [
    ('Population',       'POP105A_judete_grupe.parquet',  {'agg': 'SUM'}),
    ('Unemployment rate','SOM103A_judete.parquet',         {'agg': 'AVG'}),
    ('Avg net wage',     'FOM106A_judete.parquet',         {'agg': 'AVG'}),
    ('Birth rate',       'POP202B.parquet',                {'extra': {'RESIDENCE': 'Total '}}),
    ('Death rate',       'POP207A.parquet',                {'extra': {'RESIDENCE': 'Total '}}),
    ('Live births',      'POP201A.parquet',                {'agg': 'SUM'}),
]
for label, fname, opts in kpis:
    path = PARQUET_DIR / fname
    exists = path.exists()
    if exists:
        cols = [r[0] for r in con.execute('SELECT * FROM read_parquet(?) LIMIT 0', [str(path)]).description]
        print(f'OK  {fname}: {cols}')
    else:
        # Try to find alternatives
        matches = [f for f in os.listdir(PARQUET_DIR) if fname.split('.')[0].split('_')[0] in f]
        print(f'MISSING {fname} — alternatives: {matches[:4]}')
"
```

- [ ] **Step 1.2: Check FOM106A split for counties**

```bash
source ~/devbox/envs/240826/bin/activate && python -c "
from app.config import PARQUET_DIR
import os, duckdb
con = duckdb.connect()
fom = [f for f in os.listdir(PARQUET_DIR) if 'FOM106' in f]
print('FOM106 files:', fom)
for f in fom:
    if 'judet' in f.lower():
        p = str(PARQUET_DIR / f)
        cols = [r[0] for r in con.execute('SELECT * FROM read_parquet(?) LIMIT 0', [p]).description]
        sample = con.execute('SELECT DISTINCT ECON_ACTIVITY FROM read_parquet(?) LIMIT 3', [p]).fetchall() if 'ECON_ACTIVITY' in cols else []
        print(f'{f}: {cols}')
        print('  ECON_ACTIVITY sample:', sample)
"
```

- [ ] **Step 1.3: Create `app/static/data/` directory and write config**

```bash
mkdir -p app/static/data
```

Write `app/static/data/place_kpi_config.json` using the verified parquet filenames from Steps 1.1–1.2. Use this structure, substituting any corrected filenames:

```json
{
  "county": [
    {
      "label": "Populație rezidentă",
      "parquet": "POP105A_judete_grupe.parquet",
      "ref_area_col": "REF_AREA",
      "extra_filters": {},
      "agg_func": "SUM",
      "unit": "pers.",
      "category": "Populație"
    },
    {
      "label": "Rata șomajului",
      "parquet": "SOM103A_judete.parquet",
      "ref_area_col": "REF_AREA",
      "extra_filters": {},
      "agg_func": "AVG",
      "unit": "%",
      "category": "Economie"
    },
    {
      "label": "Câștig salarial net mediu",
      "parquet": "FOM106A_judete.parquet",
      "ref_area_col": "REF_AREA",
      "extra_filters": {"ECON_ACTIVITY": "Total"},
      "agg_func": "AVG",
      "unit": "lei",
      "category": "Economie"
    },
    {
      "label": "Rata natalității",
      "parquet": "POP202B.parquet",
      "ref_area_col": "REF_AREA",
      "extra_filters": {"RESIDENCE": "Total "},
      "agg_func": "AVG",
      "unit": "‰",
      "category": "Populație"
    },
    {
      "label": "Rata mortalității",
      "parquet": "POP207A.parquet",
      "ref_area_col": "REF_AREA",
      "extra_filters": {"RESIDENCE": "Total "},
      "agg_func": "AVG",
      "unit": "‰",
      "category": "Populație"
    },
    {
      "label": "Născuți vii",
      "parquet": "POP201A.parquet",
      "ref_area_col": "REF_AREA",
      "extra_filters": {},
      "agg_func": "SUM",
      "unit": "pers.",
      "category": "Populație"
    }
  ],
  "region": [
    {
      "label": "Populație rezidentă",
      "parquet": "POP105A_regiuni_grupe.parquet",
      "ref_area_col": "REF_AREA",
      "extra_filters": {},
      "agg_func": "SUM",
      "unit": "pers.",
      "category": "Populație"
    },
    {
      "label": "Rata șomajului",
      "parquet": "SOM103A_regiuni.parquet",
      "ref_area_col": "REF_AREA",
      "extra_filters": {},
      "agg_func": "AVG",
      "unit": "%",
      "category": "Economie"
    },
    {
      "label": "Câștig salarial net mediu",
      "parquet": "FOM106A_regiuni.parquet",
      "ref_area_col": "REF_AREA",
      "extra_filters": {"ECON_ACTIVITY": "Total"},
      "agg_func": "AVG",
      "unit": "lei",
      "category": "Economie"
    }
  ],
  "macroregion": [
    {
      "label": "Populație rezidentă",
      "parquet": "POP105A_macroregiuni_grupe.parquet",
      "ref_area_col": "REF_AREA",
      "extra_filters": {},
      "agg_func": "SUM",
      "unit": "pers.",
      "category": "Populație"
    },
    {
      "label": "Rata șomajului",
      "parquet": "SOM103A_macroregiuni.parquet",
      "ref_area_col": "REF_AREA",
      "extra_filters": {},
      "agg_func": "AVG",
      "unit": "%",
      "category": "Economie"
    }
  ],
  "locality": []
}
```

- [ ] **Step 1.4: Verify at least one KPI query works end-to-end**

```bash
source ~/devbox/envs/240826/bin/activate && python -c "
from app.config import PARQUET_DIR
import duckdb
con = duckdb.connect()
p = str(PARQUET_DIR / 'SOM103A_judete.parquet')
rows = con.execute('''
SELECT TIME_PERIOD, AVG(OBS_VALUE) as value
FROM read_parquet(?) WHERE REF_AREA = ?
GROUP BY TIME_PERIOD ORDER BY TIME_PERIOD DESC LIMIT 5
''', [p, 'Bihor']).fetchall()
print('Bihor unemployment rate (last 5 years):')
for r in rows: print(r)
"
```

Expected: rows like `('2023', 2.7)`, `('2022', 2.9)`, etc.

- [ ] **Step 1.5: Commit**

```bash
git add app/static/data/place_kpi_config.json
git commit -m "feat(places): add place KPI config with verified parquet sources"
```

---

## Task 2: Place Service — Core (resolve + slugify + dataset list)

**Files:**
- Create: `app/services/place_service.py`
- Create: `tests/test_place_service.py`

- [ ] **Step 2.1: Write the failing tests**

Create `tests/test_place_service.py`:

```python
"""Tests for place_service.py — place resolution, slugify, dataset list."""
import sys
sys.path.insert(0, '.')
import pytest
from app.services.place_service import slugify, resolve_place, get_place_datasets


def test_slugify_county():
    assert slugify("Bihor") == "bihor"

def test_slugify_with_hyphen():
    assert slugify("Bistrita-Nasaud") == "bistrita-nasaud"

def test_slugify_region_strip_prefix():
    # All region name variants normalize to the same slug
    assert slugify("Regiunea NORD-VEST") == "nord-vest"
    assert slugify("Regiunea Nord-Vest") == "nord-vest"
    assert slugify("REGIUNEA NORD-VEST") == "nord-vest"

def test_slugify_spaces_to_hyphens():
    assert slugify("Satu Mare") == "satu-mare"

def test_slugify_diacritics():
    assert slugify("Mureș") == "mures"
    assert slugify("Brăila") == "braila"


def test_resolve_county_returns_geo_names():
    result = resolve_place("county", "bihor")
    assert result is not None
    assert result["name"] == "Bihor"
    assert result["type"] == "county"
    assert isinstance(result["ref_area_values"], list)
    assert "Bihor" in result["ref_area_values"]


def test_resolve_region_returns_multiple_names():
    result = resolve_place("region", "nord-vest")
    assert result is not None
    assert result["type"] == "region"
    # Region has multiple raw names in DB — all normalized to same slug
    assert len(result["ref_area_values"]) >= 1


def test_resolve_unknown_returns_none():
    result = resolve_place("county", "notaplace99")
    assert result is None


def test_get_place_datasets_returns_list():
    datasets = get_place_datasets("county", "bihor")
    assert isinstance(datasets, list)
    assert len(datasets) > 50  # Bihor has 443 datasets
    # Each entry has required fields
    for d in datasets[:5]:
        assert "code" in d
        assert "title" in d
        assert "has_data" in d
        assert d["has_data"] is True


def test_get_place_datasets_unknown_returns_empty():
    datasets = get_place_datasets("county", "notaplace99")
    assert datasets == []
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```bash
source ~/devbox/envs/240826/bin/activate && python -m pytest tests/test_place_service.py -v 2>&1 | head -30
```

Expected: ImportError or similar — `place_service` does not exist yet.

- [ ] **Step 2.3: Write `place_service.py` — slugify + resolve_place + get_place_datasets**

Create `app/services/place_service.py`:

```python
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
    """Normalize a place name to a URL slug.

    Strips 'Regiunea'/'REGIUNEA' prefix, lowercases, removes diacritics,
    collapses whitespace/special chars to hyphens.
    """
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
        {name, type, slug, ref_area_values: [str, ...], parent_slug: str|None}
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
    """Return all datasets that have data for this place.

    Each entry: {code, title, category, context_code, has_data: True}
    """
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
```

- [ ] **Step 2.4: Run tests**

```bash
source ~/devbox/envs/240826/bin/activate && python -m pytest tests/test_place_service.py -v -k "slugify or resolve or datasets"
```

Expected: all slugify and resolve tests pass; datasets test passes (443+ results for Bihor).

- [ ] **Step 2.5: Commit**

```bash
git add app/services/place_service.py app/static/data/place_kpi_config.json tests/test_place_service.py
git commit -m "feat(places): place resolution service + dataset list + slugify"
```

---

## Task 3: Place Service — KPI Data

**Files:**
- Modify: `app/services/place_service.py`
- Modify: `tests/test_place_service.py`

- [ ] **Step 3.1: Add failing KPI tests**

Append to `tests/test_place_service.py`:

```python
from app.services.place_service import get_place_kpis


def test_get_place_kpis_county_returns_list():
    kpis = get_place_kpis("county", "bihor")
    assert isinstance(kpis, list)
    assert len(kpis) > 0
    kpi = kpis[0]
    assert "label" in kpi
    assert "unit" in kpi
    # value may be None if data missing, but sparkline must be a list
    assert isinstance(kpi["sparkline"], list)


def test_get_place_kpis_has_unemployment():
    kpis = get_place_kpis("county", "bihor")
    labels = [k["label"] for k in kpis]
    assert any("șomaj" in l.lower() or "somaj" in l.lower() for l in labels)


def test_get_place_kpis_sparkline_ordered():
    kpis = get_place_kpis("county", "bihor")
    pop_kpi = next((k for k in kpis if "opulat" in k["label"]), None)
    if pop_kpi and len(pop_kpi["sparkline"]) >= 2:
        years = [entry["year"] for entry in pop_kpi["sparkline"]]
        assert years == sorted(years)  # ascending


def test_get_place_kpis_missing_locality_returns_partial():
    # Localities may have 0 KPIs — must not error
    kpis = get_place_kpis("locality", "oradea")
    assert isinstance(kpis, list)  # empty list OK
```

- [ ] **Step 3.2: Run to confirm failure**

```bash
source ~/devbox/envs/240826/bin/activate && python -m pytest tests/test_place_service.py::test_get_place_kpis_county_returns_list -v
```

Expected: ImportError on `get_place_kpis`.

- [ ] **Step 3.3: Implement `get_place_kpis`**

Add to `app/services/place_service.py` (after `get_place_datasets`):

```python
def _query_kpi_series(parquet_path: Path, ref_area_values: list[str],
                       extra_filters: dict, agg_func: str) -> list[dict]:
    """Query a parquet for a place's annual time series.

    Returns list of {year: str, value: float} sorted ascending by year.
    Averages over any non-REF_AREA, non-TIME_PERIOD, non-UNIT_MEASURE dims.
    """
    if not parquet_path.exists():
        return []

    con = _duckdb.connect()
    where_parts = [
        "REF_AREA IN ({})".format(",".join(f"'{v}'" for v in ref_area_values))
    ]
    for col, val in extra_filters.items():
        safe_val = val.replace("'", "''")
        where_parts.append(f"{col} = '{safe_val}'")

    # For monthly/quarterly data, truncate to year
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

    For localities, returns an empty list (graceful degradation).
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
            # Absolute delta for rates/‰, percentage change for counts
            if spec["unit"] in ("%", "‰"):
                yoy = round(curr - prev, 2)
            else:
                yoy = round((curr - prev) / prev * 100, 1) if prev else None

        results.append({
            "label": spec["label"],
            "unit": spec["unit"],
            "category": spec["category"],
            "value": round(latest, 1) if latest is not None else None,
            "change_yoy": yoy,
            "sparkline": series,
        })

    return results
```

- [ ] **Step 3.4: Run KPI tests**

```bash
source ~/devbox/envs/240826/bin/activate && python -m pytest tests/test_place_service.py -v -k "kpi"
```

Expected: all 4 KPI tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add app/services/place_service.py tests/test_place_service.py
git commit -m "feat(places): KPI data fetching with sparklines + YoY delta"
```

---

## Task 4: Place Service — Peers + Baselines

**Files:**
- Modify: `app/services/place_service.py`
- Modify: `tests/test_place_service.py`

- [ ] **Step 4.1: Add failing peer tests**

Append to `tests/test_place_service.py`:

```python
from app.services.place_service import get_place_peers, get_kpi_baselines


def test_get_place_peers_county_has_same_region():
    peers = get_place_peers("county", "bihor")
    assert "same_region" in peers
    assert isinstance(peers["same_region"], list)
    slugs = [p["slug"] for p in peers["same_region"]]
    assert "cluj" in slugs  # Cluj is also Nord-Vest


def test_get_place_peers_county_has_similar_size():
    peers = get_place_peers("county", "bihor")
    assert "similar_size" in peers
    assert len(peers["similar_size"]) <= 3


def test_get_place_peers_self_excluded():
    peers = get_place_peers("county", "bihor")
    all_peer_slugs = (
        [p["slug"] for p in peers.get("same_region", [])] +
        [p["slug"] for p in peers.get("similar_size", [])]
    )
    assert "bihor" not in all_peer_slugs


def test_get_kpi_baselines_returns_national():
    baselines = get_kpi_baselines("county", "bihor", "Rata șomajului")
    assert "national" in baselines
    assert isinstance(baselines["national"], list)
    assert len(baselines["national"]) > 0


def test_get_kpi_baselines_returns_region():
    baselines = get_kpi_baselines("county", "bihor", "Rata șomajului")
    assert "region" in baselines
    assert isinstance(baselines["region"], list)
```

- [ ] **Step 4.2: Confirm failure**

```bash
source ~/devbox/envs/240826/bin/activate && python -m pytest tests/test_place_service.py::test_get_place_peers_county_has_same_region -v
```

Expected: ImportError.

- [ ] **Step 4.3: Implement `get_place_peers` and `get_kpi_baselines`**

Append to `app/services/place_service.py`:

```python
def _get_county_population(county_name: str) -> float | None:
    """Get latest total population for a county from KPI parquet."""
    parquet_path = PARQUET_DIR / "POP105A_judete_grupe.parquet"
    if not parquet_path.exists():
        return None
    con = _duckdb.connect()
    rows = con.execute("""
        SELECT SUM(OBS_VALUE) as pop
        FROM read_parquet(?)
        WHERE REF_AREA = ?
        GROUP BY TIME_PERIOD
        ORDER BY TIME_PERIOD DESC
        LIMIT 1
    """, [str(parquet_path), county_name]).fetchall()
    return rows[0][0] if rows else None


def get_place_peers(place_type: str, slug: str, *, conn=None) -> dict:
    """Return peer groups for comparison.

    Returns:
        {
          same_region: [{slug, name, type}, ...],   # up to 5 siblings
          similar_size: [{slug, name, type}, ...]    # up to 3 by population proximity
        }
    Only implemented for county type; returns empty groups for others.
    """
    if conn is None:
        conn = get_conn()

    place = resolve_place(place_type, slug, conn=conn)
    if not place:
        return {"same_region": [], "similar_size": []}

    if place_type != "county":
        # For regions/macroregions, return siblings only
        all_places = conn.execute("""
            SELECT DISTINCT geo_name_clean FROM dimension_options_parsed
            WHERE dim_type = 'geo' AND geo_level = ?
        """, [place_type]).fetchall()
        siblings = [
            {"slug": slugify(r[0]), "name": r[0], "type": place_type}
            for (r[0],) in all_places
            if slugify(r[0]) != slug and r[0]
        ][:5]
        return {"same_region": siblings, "similar_size": []}

    # County-level peers
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

    # Similar size by population
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


def get_kpi_baselines(place_type: str, slug: str, kpi_label: str) -> dict:
    """Get national and region baselines for a named KPI.

    Returns:
        {
          national: [{year, value}, ...],
          region:   [{year, value}, ...]   # empty for non-county types
        }
    """
    config = _load_kpi_config()
    specs = config.get(place_type, [])
    spec = next((s for s in specs if s["label"] == kpi_label), None)
    if not spec:
        return {"national": [], "region": []}

    parquet_path = PARQUET_DIR / spec["parquet"]
    agg_func = spec.get("agg_func", "AVG")
    extra = spec.get("extra_filters", {})

    # National: aggregate all REF_AREA values in the parquet (no REF_AREA filter)
    national: list = []
    if parquet_path.exists():
        con = _duckdb.connect()
        where_parts = []
        for col, val in extra.items():
            safe_val = val.replace("'", "''")
            where_parts.append(f"{col} = '{safe_val}'")
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        try:
            rows = con.execute(f"""
                SELECT LEFT(CAST(TIME_PERIOD AS VARCHAR), 4) AS year,
                       {agg_func}(OBS_VALUE) AS value
                FROM read_parquet('{parquet_path}')
                {where_clause}
                  {'AND' if where_clause else 'WHERE'} TRY_CAST(LEFT(CAST(TIME_PERIOD AS VARCHAR), 4) AS INTEGER) IS NOT NULL
                GROUP BY 1 ORDER BY 1 ASC LIMIT 30
            """).fetchall()
            national = [{"year": r[0], "value": r[1]} for r in rows if r[1] is not None]
        except Exception:
            national = []

    # Region: counties in the same region only
    region_series: list = []
    if place_type == "county":
        place = resolve_place(place_type, slug)
        if place and place["parent_slug"]:
            region_slug = place["parent_slug"]
            region_counties = [
                name for name, reg in COUNTY_REGION.items() if reg == region_slug
            ]
            region_series = _query_kpi_series(
                parquet_path, region_counties, extra, agg_func
            )

    return {"national": national, "region": region_series}
```

- [ ] **Step 4.4: Run all service tests**

```bash
source ~/devbox/envs/240826/bin/activate && python -m pytest tests/test_place_service.py -v
```

Expected: all tests pass (the `similar_size` computation may be slow — under 10s is fine).

- [ ] **Step 4.5: Commit**

```bash
git add app/services/place_service.py tests/test_place_service.py
git commit -m "feat(places): peer groups + national/region KPI baselines"
```

---

## Task 5: Router + App Wiring

**Files:**
- Create: `app/routers/places.py`
- Modify: `app/main.py`

- [ ] **Step 5.1: Write failing route test**

Append to `tests/test_place_service.py`:

```python
from fastapi.testclient import TestClient
from app.main import app

_client = TestClient(app)


def test_api_places_list():
    resp = _client.get("/api/places")
    assert resp.status_code == 200
    data = resp.json()
    assert "places" in data
    county_slugs = [p["slug"] for p in data["places"] if p["type"] == "county"]
    assert "bihor" in county_slugs
    assert "cluj" in county_slugs


def test_api_place_profile_county():
    resp = _client.get("/api/places/county/bihor")
    assert resp.status_code == 200
    data = resp.json()
    assert data["place"]["name"] == "Bihor"
    assert data["place"]["type"] == "county"
    assert isinstance(data["kpis"], list)
    assert isinstance(data["datasets"], list)
    assert "same_region" in data["peers"]


def test_api_place_profile_not_found():
    resp = _client.get("/api/places/county/notaplace")
    assert resp.status_code == 404


def test_place_html_page_serves():
    resp = _client.get("/place/county/bihor")
    assert resp.status_code == 200
    assert b"<!DOCTYPE html>" in resp.content or b"place.html" in resp.content


def test_places_html_serves():
    resp = _client.get("/places")
    assert resp.status_code == 200
```

- [ ] **Step 5.2: Confirm failure**

```bash
source ~/devbox/envs/240826/bin/activate && python -m pytest tests/test_place_service.py::test_api_places_list -v
```

Expected: 404 or AttributeError — routes don't exist yet.

- [ ] **Step 5.3: Create `app/routers/places.py`**

```python
"""Place profile routes — directory listing and individual place profiles."""
import json
import unicodedata
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.db import get_conn
from app.services.place_service import (
    resolve_place, get_place_datasets, get_place_kpis,
    get_place_peers, get_kpi_baselines, slugify,
    COUNTY_REGION, REGION_NAMES,
)

router = APIRouter()

_STATIC = Path(__file__).parent.parent / "static"

GEO_LEVELS = ["county", "region", "macroregion", "locality"]


@router.get("/places", include_in_schema=False)
def places_directory_html():
    return FileResponse(_STATIC / "places.html")


@router.get("/place/{place_type}/{slug}", include_in_schema=False)
def place_profile_html(place_type: str, slug: str):
    if place_type not in GEO_LEVELS:
        raise HTTPException(404, "Unknown place type")
    return FileResponse(_STATIC / "place.html")


@router.get("/api/places")
def list_places():
    """List all known places grouped by type."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT geo_level, geo_name_clean
        FROM dimension_options_parsed
        WHERE dim_type = 'geo'
          AND geo_level IN ('county', 'region', 'macroregion')
          AND geo_name_clean IS NOT NULL
        ORDER BY geo_level, geo_name_clean
    """).fetchall()

    seen: set = set()
    places = []
    for geo_level, name in rows:
        sl = slugify(name)
        key = (geo_level, sl)
        if key in seen:
            continue
        seen.add(key)
        places.append({"type": geo_level, "slug": sl, "name": name})

    return {"places": places, "total": len(places)}


@router.get("/api/places/{place_type}/{slug}")
def get_place_profile(place_type: str, slug: str):
    """Full place profile: KPIs, dataset list, peers."""
    if place_type not in GEO_LEVELS:
        raise HTTPException(404, "Unknown place type")

    conn = get_conn()
    place = resolve_place(place_type, slug, conn=conn)
    if not place:
        raise HTTPException(404, f"Place not found: {place_type}/{slug}")

    parent = None
    if place.get("parent_slug"):
        parent = {
            "type": "region",
            "slug": place["parent_slug"],
            "name": place.get("parent_name", place["parent_slug"]),
        }

    kpis = get_place_kpis(place_type, slug, conn=conn)
    datasets = get_place_datasets(place_type, slug, conn=conn)
    peers = get_place_peers(place_type, slug, conn=conn)

    return {
        "place": {
            "name": place["name"],
            "type": place_type,
            "slug": slug,
            "parent": parent,
        },
        "kpis": kpis,
        "datasets": datasets,
        "peers": peers,
        "dataset_count": len(datasets),
    }


@router.get("/api/places/{place_type}/{slug}/baselines/{kpi_label}")
def get_place_baselines(place_type: str, slug: str, kpi_label: str):
    """National + region baseline series for a single KPI."""
    return get_kpi_baselines(place_type, slug, kpi_label)
```

- [ ] **Step 5.4: Update `app/main.py`**

Line 9 of `app/main.py` currently reads:
```python
from app.routers import categories, datasets, dataset_data, sdmx, ask
```
Change to:
```python
from app.routers import categories, datasets, dataset_data, sdmx, ask, places
```

After line 26 (`app.include_router(ask.router, prefix="/api", tags=["ask"])`), insert:
```python
app.include_router(places.router, tags=["places"])
```

**Critical:** This include must appear BEFORE the `app.mount("/", StaticFiles(...))` line at the bottom of `main.py`. The static mount is a catch-all — any route registered after it will be unreachable.

- [ ] **Step 5.5: Run route tests**

```bash
source ~/devbox/envs/240826/bin/activate && python -m pytest tests/test_place_service.py::test_api_places_list tests/test_place_service.py::test_api_place_profile_county tests/test_place_service.py::test_api_place_profile_not_found -v
```

Expected: first two pass (HTML page tests will 404 until HTML files exist — that's OK).

- [ ] **Step 5.6: Commit**

```bash
git add app/routers/places.py app/main.py tests/test_place_service.py
git commit -m "feat(places): FastAPI router + API endpoints for place profiles"
```

---

## Task 6: Places Directory Page

**Files:**
- Create: `app/static/places.html`
- Create: `app/static/js/places-page.js`

- [ ] **Step 6.1: Create `app/static/places.html`**

```html
<!DOCTYPE html>
<html lang="ro">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Locuri — INS+</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/css/explore.css?v=37">
</head>
<body>
    <nav class="topbar">
        <div class="topbar-left">
            <a href="/" class="logo"><span class="logo-dot"></span>INS<span style="margin:-1ex 0 0 -1ex;">+</span></a>
        </div>
        <div class="topbar-right">
            <a href="/" class="toggle-btn" style="text-decoration:none;font-size:0.8rem;padding:0 10px;">Date</a>
        </div>
    </nav>

    <div class="main-content" style="max-width:900px;margin:0 auto;padding:2rem 1rem;">
        <h1 style="font-size:1.6rem;font-weight:700;margin-bottom:0.25rem;">Profiluri de locuri</h1>
        <p style="color:var(--text-muted);margin-bottom:2rem;">Județe, regiuni de dezvoltare și macroregiuni România</p>

        <div id="places-loading" style="color:var(--text-muted);">Se încarcă...</div>
        <div id="places-content" style="display:none;">
            <section id="section-county">
                <h2 style="font-size:1rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;color:var(--text-muted);margin:1.5rem 0 0.75rem;">Județe</h2>
                <div id="grid-county" class="places-grid"></div>
            </section>
            <section id="section-region">
                <h2 style="font-size:1rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;color:var(--text-muted);margin:1.5rem 0 0.75rem;">Regiuni de dezvoltare</h2>
                <div id="grid-region" class="places-grid"></div>
            </section>
            <section id="section-macroregion">
                <h2 style="font-size:1rem;font-weight:600;text-transform:uppercase;letter-spacing:0.05em;color:var(--text-muted);margin:1.5rem 0 0.75rem;">Macroregiuni</h2>
                <div id="grid-macroregion" class="places-grid"></div>
            </section>
        </div>
    </div>

    <style>
        .places-grid { display:flex;flex-wrap:wrap;gap:0.5rem; }
        .place-chip {
            display:inline-block;
            padding:0.4rem 0.9rem;
            background:var(--card-bg, #1e293b);
            border:1px solid var(--border, #334155);
            border-radius:6px;
            text-decoration:none;
            color:var(--text-primary, #f1f5f9);
            font-size:0.875rem;
            transition:border-color 0.15s,background 0.15s;
        }
        .place-chip:hover { border-color:var(--accent,#3b82f6);background:var(--card-hover,#1e3a5f); }
    </style>
    <script src="/js/places-page.js?v=1"></script>
</body>
</html>
```

- [ ] **Step 6.2: Create `app/static/js/places-page.js`**

```javascript
(async function () {
    const loading = document.getElementById('places-loading');
    const content = document.getElementById('places-content');

    try {
        const resp = await fetch('/api/places');
        if (!resp.ok) throw new Error('API error');
        const { places } = await resp.json();

        const byType = { county: [], region: [], macroregion: [] };
        for (const p of places) {
            if (byType[p.type]) byType[p.type].push(p);
        }

        for (const type of ['county', 'region', 'macroregion']) {
            const grid = document.getElementById(`grid-${type}`);
            const sorted = byType[type].sort((a, b) => a.name.localeCompare(b.name, 'ro'));
            grid.innerHTML = sorted.map(p =>
                `<a class="place-chip" href="/place/${p.type}/${p.slug}">${p.name}</a>`
            ).join('');
        }

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = 'Eroare la încărcare.';
    }
}());
```

- [ ] **Step 6.3: Start server and verify directory page**

```bash
source ~/devbox/envs/240826/bin/activate && uvicorn app.main:app --reload --port 8080
```

Open `http://localhost:8080/places` — should show three sections with county/region/macroregion chips. Click "Bihor" → should load `/place/county/bihor` (404 body is fine — HTML page doesn't exist yet).

- [ ] **Step 6.4: Commit**

```bash
git add app/static/places.html app/static/js/places-page.js
git commit -m "feat(places): directory listing page — counties, regions, macroregions"
```

---

## Task 7: Place Profile HTML + Section A (KPI Heroes)

**Files:**
- Create: `app/static/place.html`
- Create: `app/static/js/place-page.js`

- [ ] **Step 7.1: Create `app/static/place.html`**

```html
<!DOCTYPE html>
<html lang="ro">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Profil loc — INS+</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/css/explore.css?v=37">
    <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
    <style>
        .place-header { padding:1.5rem 0 1rem; border-bottom:1px solid var(--border,#334155); margin-bottom:1.5rem; }
        .breadcrumb { font-size:0.8rem; color:var(--text-muted); margin-bottom:0.5rem; }
        .breadcrumb a { color:var(--text-muted); text-decoration:none; }
        .breadcrumb a:hover { color:var(--text-primary); }
        .place-title { font-size:1.8rem; font-weight:700; display:flex; align-items:center; gap:0.75rem; }
        .geo-badge {
            font-size:0.7rem; font-weight:600; text-transform:uppercase; letter-spacing:0.06em;
            padding:0.2rem 0.6rem; border-radius:10px;
            background:var(--card-bg,#1e293b); color:var(--text-muted); border:1px solid var(--border);
        }
        .dataset-count { font-size:0.85rem; color:var(--text-muted); margin-top:0.4rem; }

        /* KPI Heroes */
        .kpi-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:0.75rem; margin-bottom:2rem; }
        .kpi-card {
            background:var(--card-bg,#1e293b); border:1px solid var(--border,#334155);
            border-radius:8px; padding:0.875rem; cursor:pointer; transition:border-color 0.15s;
        }
        .kpi-card:hover, .kpi-card.active { border-color:var(--accent,#3b82f6); }
        .kpi-label { font-size:0.75rem; color:var(--text-muted); margin-bottom:0.3rem; }
        .kpi-value { font-size:1.2rem; font-weight:700; color:var(--text-primary,#f1f5f9); }
        .kpi-unit { font-size:0.75rem; color:var(--text-muted); margin-left:0.2rem; }
        .kpi-delta { font-size:0.75rem; margin-top:0.15rem; }
        .kpi-delta.up { color:#4ade80; }
        .kpi-delta.down { color:#f87171; }
        .kpi-sparkline { height:32px; margin-top:0.4rem; }

        /* Indicator Grid */
        .section-title {
            font-size:0.875rem; font-weight:600; text-transform:uppercase;
            letter-spacing:0.05em; color:var(--text-muted); margin:1.5rem 0 0.75rem;
        }
        .category-chips { display:flex; flex-wrap:wrap; gap:0.4rem; margin-bottom:1rem; }
        .cat-chip {
            padding:0.3rem 0.75rem; border-radius:12px; font-size:0.8rem; cursor:pointer;
            background:var(--card-bg); border:1px solid var(--border); color:var(--text-muted);
            transition:all 0.15s;
        }
        .cat-chip.active { background:var(--accent,#3b82f6); color:#fff; border-color:var(--accent); }
        .indicator-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:0.6rem; }
        .ind-card {
            background:var(--card-bg); border:1px solid var(--border);
            border-radius:6px; padding:0.6rem 0.75rem; cursor:pointer;
            text-decoration:none; transition:border-color 0.15s;
        }
        .ind-card:hover { border-color:var(--accent); }
        .ind-card.no-data { opacity:0.45; cursor:default; pointer-events:none; }
        .ind-title { font-size:0.78rem; color:var(--text-primary); line-height:1.3; }
        .ind-sparkline { height:24px; margin-top:0.4rem; }
        .no-data-label { font-size:0.72rem; color:var(--text-muted); margin-top:0.4rem; }

        /* Comparison */
        .comparison-section { margin-top:2rem; }
        .always-chips { display:flex; flex-wrap:wrap; gap:0.4rem; margin-bottom:0.75rem; }
        .baseline-chip {
            padding:0.3rem 0.8rem; border-radius:12px; font-size:0.8rem;
            border:1px solid var(--border); color:var(--text-muted); background:var(--card-bg);
        }
        .peer-groups { display:flex; flex-direction:column; gap:0.5rem; margin-bottom:1rem; }
        .peer-group { display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap; }
        .peer-group-label { font-size:0.75rem; color:var(--text-muted); min-width:90px; }
        .peer-chip {
            padding:0.25rem 0.7rem; border-radius:10px; font-size:0.8rem; cursor:pointer;
            background:var(--card-bg); border:1px solid var(--border); color:var(--text-primary);
            transition:all 0.15s;
        }
        .peer-chip.active { background:var(--accent,#3b82f6); color:#fff; border-color:var(--accent); }
        #comparison-chart { width:100%; height:300px; }

        .page-container { max-width:960px; margin:0 auto; padding:0 1rem 3rem; }
        #place-loading { padding:2rem; color:var(--text-muted); }
    </style>
</head>
<body>
    <nav class="topbar">
        <div class="topbar-left">
            <a href="/" class="logo"><span class="logo-dot"></span>INS<span style="margin:-1ex 0 0 -1ex;">+</span></a>
        </div>
        <div class="topbar-right">
            <a href="/places" class="toggle-btn" style="text-decoration:none;font-size:0.8rem;padding:0 10px;">Locuri</a>
            <a href="/" class="toggle-btn" style="text-decoration:none;font-size:0.8rem;padding:0 10px;">Date</a>
        </div>
    </nav>

    <div class="page-container">
        <div id="place-loading">Se încarcă...</div>
        <div id="place-content" style="display:none;">
            <!-- Section A: Header + KPI heroes -->
            <div class="place-header">
                <div class="breadcrumb" id="breadcrumb"></div>
                <div class="place-title">
                    <span id="place-name"></span>
                    <span class="geo-badge" id="geo-badge"></span>
                </div>
                <div class="dataset-count" id="dataset-count"></div>
            </div>
            <div class="kpi-grid" id="kpi-grid"></div>

            <!-- Section B: Indicator Grid -->
            <div class="section-title">Indicatori disponibili</div>
            <div class="category-chips" id="category-chips"></div>
            <div class="indicator-grid" id="indicator-grid"></div>

            <!-- Section C: Comparison -->
            <div class="comparison-section">
                <div class="section-title">Comparație — <span id="comparison-kpi-label" style="color:var(--text-primary)"></span></div>
                <div class="always-chips" id="always-chips"></div>
                <div class="peer-groups" id="peer-groups"></div>
                <div id="comparison-chart"></div>
            </div>
        </div>
    </div>

    <script src="/js/place-page.js?v=1"></script>
</body>
</html>
```

- [ ] **Step 7.2: Create `app/static/js/place-page.js` — skeleton + section A**

```javascript
class PlaceProfileApp {
    constructor() {
        this.data = null;
        this.activeKpiIndex = 0;
        this.activePeers = new Set();
        this.activeCategory = 'all';
        this.comparisonChart = null;
        this.comparisonData = {};  // kpi_label → {series_name: [{year, value}]}
    }

    async init() {
        const parts = window.location.pathname.split('/').filter(Boolean);
        // /place/{type}/{slug}
        if (parts.length < 3) return;
        this.placeType = parts[1];
        this.placeSlug = parts[2];

        try {
            const resp = await fetch(`/api/places/${this.placeType}/${this.placeSlug}`);
            if (!resp.ok) {
                document.getElementById('place-loading').textContent = 'Locul nu a fost găsit.';
                return;
            }
            this.data = await resp.json();
        } catch (e) {
            document.getElementById('place-loading').textContent = 'Eroare la încărcare.';
            return;
        }

        this._renderHeader();
        this._renderKPIs();
        this._renderIndicatorGrid();
        this._renderComparison();

        document.getElementById('place-loading').style.display = 'none';
        document.getElementById('place-content').style.display = 'block';

        // Set page title
        document.title = `${this.data.place.name} — INS+`;
    }

    _renderHeader() {
        const { place, dataset_count } = this.data;
        const crumbs = ['<a href="/places">Locuri</a>'];
        if (place.parent) {
            crumbs.push(`<a href="/place/${place.parent.type}/${place.parent.slug}">${place.parent.name}</a>`);
        }
        crumbs.push(place.name);
        document.getElementById('breadcrumb').innerHTML = crumbs.join(' › ');
        document.getElementById('place-name').textContent = place.name;
        const typeLabels = { county: 'Județ', region: 'Regiune', macroregion: 'Macroregiune', locality: 'Localitate' };
        document.getElementById('geo-badge').textContent = typeLabels[place.type] || place.type;
        document.getElementById('dataset-count').textContent = `${dataset_count} seturi de date disponibile`;
    }

    _renderKPIs() {
        const grid = document.getElementById('kpi-grid');
        grid.innerHTML = this.data.kpis.map((kpi, i) => {
            const deltaHtml = kpi.change_yoy != null
                ? `<div class="kpi-delta ${kpi.change_yoy >= 0 ? 'up' : 'down'}">
                     ${kpi.change_yoy >= 0 ? '▲' : '▼'} ${Math.abs(kpi.change_yoy)} ${kpi.unit}
                   </div>`
                : '';
            return `
                <div class="kpi-card ${i === 0 ? 'active' : ''}"
                     data-kpi-index="${i}"
                     onclick="app._selectKpi(${i})">
                    <div class="kpi-label">${kpi.label}</div>
                    <div>
                        <span class="kpi-value">${kpi.value != null ? kpi.value.toLocaleString('ro-RO') : '—'}</span>
                        <span class="kpi-unit">${kpi.unit}</span>
                    </div>
                    ${deltaHtml}
                    <div class="kpi-sparkline" id="kpi-spark-${i}"></div>
                </div>`;
        }).join('');

        // Render sparklines after DOM insertion
        this.data.kpis.forEach((kpi, i) => {
            this._renderSparkline(`kpi-spark-${i}`, kpi.sparkline);
        });
    }

    _renderSparkline(containerId, series) {
        const el = document.getElementById(containerId);
        if (!el || !series || series.length < 2) return;
        const chart = echarts.init(el, null, { renderer: 'svg' });
        chart.setOption({
            animation: false,
            grid: { top: 2, right: 2, bottom: 2, left: 2 },
            xAxis: { type: 'category', show: false, data: series.map(r => r.year) },
            yAxis: { type: 'value', show: false },
            series: [{
                type: 'line',
                data: series.map(r => r.value),
                smooth: true,
                showSymbol: false,
                lineStyle: { color: '#3b82f6', width: 1.5 },
                areaStyle: { color: 'rgba(59,130,246,0.1)' },
            }],
        });
    }

    _selectKpi(index) {
        document.querySelectorAll('.kpi-card').forEach((el, i) => {
            el.classList.toggle('active', i === index);
        });
        this.activeKpiIndex = index;
        document.getElementById('comparison-kpi-label').textContent =
            this.data.kpis[index]?.label || '';
        this._refreshComparisonChart();
    }

    _renderIndicatorGrid() {
        const { datasets } = this.data;
        const categories = ['all', ...new Set(datasets.map(d => d.category))].sort((a, b) =>
            a === 'all' ? -1 : b === 'all' ? 1 : a.localeCompare(b, 'ro')
        );

        const chips = document.getElementById('category-chips');
        chips.innerHTML = categories.map(cat => {
            const label = cat === 'all' ? 'Toate' : cat;
            return `<div class="cat-chip ${cat === 'all' ? 'active' : ''}"
                        onclick="app._filterCategory('${cat}')">${label}</div>`;
        }).join('');

        this._renderDatasetCards(datasets);
    }

    _filterCategory(cat) {
        this.activeCategory = cat;
        document.querySelectorAll('.cat-chip').forEach(el => {
            el.classList.toggle('active', el.textContent === (cat === 'all' ? 'Toate' : cat));
        });
        const filtered = cat === 'all'
            ? this.data.datasets
            : this.data.datasets.filter(d => d.category === cat);
        this._renderDatasetCards(filtered);
    }

    _renderDatasetCards(datasets) {
        const grid = document.getElementById('indicator-grid');
        grid.innerHTML = datasets.map(d => {
            if (!d.has_data) {
                return `<div class="ind-card no-data">
                    <div class="ind-title">${d.title}</div>
                    <div class="no-data-label">fără date</div>
                </div>`;
            }
            return `<a class="ind-card"
                       href="/dataset/${d.code}?place=${encodeURIComponent(this.placeSlug)}"
                       title="${d.title}">
                <div class="ind-title">${d.title}</div>
            </a>`;
        }).join('');
    }

    _renderComparison() {
        const { place, peers, kpis } = this.data;

        // Always-on chips
        const alwaysChips = document.getElementById('always-chips');
        const baselines = [];
        if (place.parent) {
            baselines.push(`<span class="baseline-chip">🇷🇴 Medie națională</span>`);
            baselines.push(`<span class="baseline-chip">${place.parent.name} (regiune)</span>`);
        } else {
            baselines.push(`<span class="baseline-chip">🇷🇴 Medie națională</span>`);
        }
        alwaysChips.innerHTML = baselines.join('');

        // Peer group chips
        const peerGroupsEl = document.getElementById('peer-groups');
        const groups = [];
        if (peers.same_region?.length) {
            const chips = peers.same_region.map(p =>
                `<div class="peer-chip" data-slug="${p.slug}" data-type="${p.type}" data-name="${p.name}"
                      onclick="app._togglePeer(this)">${p.name}</div>`
            ).join('');
            groups.push(`<div class="peer-group">
                <span class="peer-group-label">Aceeași regiune:</span>${chips}
            </div>`);
        }
        if (peers.similar_size?.length) {
            const chips = peers.similar_size.map(p =>
                `<div class="peer-chip" data-slug="${p.slug}" data-type="${p.type}" data-name="${p.name}"
                      onclick="app._togglePeer(this)">${p.name}</div>`
            ).join('');
            groups.push(`<div class="peer-group">
                <span class="peer-group-label">Mărime similară:</span>${chips}
            </div>`);
        }
        peerGroupsEl.innerHTML = groups.join('');

        // Set initial comparison label
        document.getElementById('comparison-kpi-label').textContent = kpis[0]?.label || '';

        // Init comparison chart
        const chartEl = document.getElementById('comparison-chart');
        this.comparisonChart = echarts.init(chartEl, null, { renderer: 'svg' });

        // Load baselines then render
        this._loadBaselines().then(() => this._refreshComparisonChart());
    }

    async _loadBaselines() {
        const kpi = this.data.kpis[this.activeKpiIndex];
        if (!kpi) return;
        const label = encodeURIComponent(kpi.label);
        try {
            const resp = await fetch(
                `/api/places/${this.placeType}/${this.placeSlug}/baselines/${label}`
            );
            if (!resp.ok) return;
            const { national, region } = await resp.json();
            this.comparisonData['__national__'] = national;
            this.comparisonData['__region__'] = region;
        } catch (_) {}
    }

    async _togglePeer(el) {
        const slug = el.dataset.slug;
        const type = el.dataset.type;
        const name = el.dataset.name;

        if (this.activePeers.has(slug)) {
            this.activePeers.delete(slug);
            el.classList.remove('active');
            delete this.comparisonData[slug];
        } else {
            if (this.activePeers.size >= 3) return;  // max 3 optional peers
            this.activePeers.add(slug);
            el.classList.add('active');
            try {
                const resp = await fetch(`/api/places/${type}/${slug}`);
                if (resp.ok) {
                    const peer = await resp.json();
                    const kpiLabel = this.data.kpis[this.activeKpiIndex]?.label;
                    const kpi = peer.kpis.find(k => k.label === kpiLabel);
                    this.comparisonData[slug] = kpi ? kpi.sparkline : [];
                }
            } catch (_) {}
        }
        this._refreshComparisonChart();
    }

    _refreshComparisonChart() {
        if (!this.comparisonChart) return;
        const kpi = this.data.kpis[this.activeKpiIndex];
        if (!kpi) return;

        const series = [];
        const colors = ['#3b82f6', '#94a3b8', '#64748b', '#f59e0b', '#a78bfa', '#4ade80'];
        let colorIdx = 0;

        // Current place
        series.push({
            name: this.data.place.name,
            type: 'line',
            data: kpi.sparkline.map(r => [r.year, r.value]),
            lineStyle: { width: 2.5, color: colors[colorIdx++] },
            showSymbol: false, smooth: true,
        });

        // National baseline
        if (this.comparisonData['__national__']?.length) {
            series.push({
                name: 'Medie națională',
                type: 'line',
                data: this.comparisonData['__national__'].map(r => [r.year, r.value]),
                lineStyle: { width: 1.5, color: colors[colorIdx++], type: 'dashed' },
                showSymbol: false, smooth: true,
            });
        }

        // Region baseline
        if (this.comparisonData['__region__']?.length) {
            series.push({
                name: this.data.place.parent?.name || 'Regiune',
                type: 'line',
                data: this.comparisonData['__region__'].map(r => [r.year, r.value]),
                lineStyle: { width: 1.5, color: colors[colorIdx++], type: 'dashed' },
                showSymbol: false, smooth: true,
            });
        }

        // Active peers
        for (const slug of this.activePeers) {
            if (this.comparisonData[slug]?.length) {
                const peerName = [...document.querySelectorAll('.peer-chip')]
                    .find(el => el.dataset.slug === slug)?.dataset.name || slug;
                series.push({
                    name: peerName,
                    type: 'line',
                    data: this.comparisonData[slug].map(r => [r.year, r.value]),
                    lineStyle: { width: 1.5, color: colors[colorIdx++ % colors.length] },
                    showSymbol: false, smooth: true,
                });
            }
        }

        this.comparisonChart.setOption({
            animation: false,
            tooltip: { trigger: 'axis' },
            legend: { bottom: 0, textStyle: { color: '#94a3b8', fontSize: 11 } },
            grid: { top: 12, right: 16, bottom: 48, left: 48 },
            xAxis: { type: 'time', axisLabel: { color: '#64748b', fontSize: 11 } },
            yAxis: {
                type: 'value',
                axisLabel: { color: '#64748b', fontSize: 11,
                    formatter: v => `${v} ${kpi.unit}` },
                splitLine: { lineStyle: { color: '#1e293b' } },
            },
            series,
        }, true);
    }
}

const app = new PlaceProfileApp();
document.addEventListener('DOMContentLoaded', () => app.init());
```

- [ ] **Step 7.3: Test HTML pages load**

Run the route tests that check HTML:
```bash
source ~/devbox/envs/240826/bin/activate && python -m pytest tests/test_place_service.py::test_place_html_page_serves tests/test_place_service.py::test_places_html_serves -v
```

Expected: both pass (200 OK).

- [ ] **Step 7.4: Open in browser and verify sections A, B, C render**

```bash
source ~/devbox/envs/240826/bin/activate && uvicorn app.main:app --reload --port 8080
```

Open `http://localhost:8080/place/county/bihor`:
- Header shows "Bihor", "Județ" badge, dataset count
- KPI cards show unemployment rate, birth rate, etc. with sparklines
- Clicking a KPI card updates the comparison chart label
- Category chips filter the indicator grid
- Peer chips load overlay series on the comparison chart
- National/region baselines appear as dashed lines

Check browser console for errors. Fix any JS errors before proceeding.

- [ ] **Step 7.5: Commit**

```bash
git add app/static/place.html app/static/js/place-page.js
git commit -m "feat(places): place profile page — KPI heroes, indicator grid, comparison chart"
```

---

## Task 8: Navigation + Backlog

**Files:**
- Modify: `app/static/index.html`
- Modify: `docs/BACKLOG.md`

- [ ] **Step 8.1: Add "Locuri" nav link to `index.html`**

Find the topbar-right `<div>` section in `app/static/index.html`. Locate the Ask link:
```html
<a href="/ask.html" class="toggle-btn" ...>Ask</a>
```

Add the Places link immediately before it:
```html
<a href="/places" class="toggle-btn" style="text-decoration:none;font-size:0.8rem;padding:0 10px;display:flex;align-items:center;gap:5px;">Locuri</a>
```

- [ ] **Step 8.2: Add backlog items**

In `docs/BACKLOG.md`, add under an appropriate section:

```markdown
- [ ] **Place profiles: norm by population toggle** — On any absolute-count KPI/indicator chart in place profiles, add a "per 1,000 population" toggle. Requires population lookup for place + year. Spec: `docs/superpowers/specs/2026-05-07-place-profiles-design.md`.
- [ ] **Place profiles: choropleth click-through** — Clicking a county on any choropleth map should open its place profile (currently just filters the chart). Need to add click handler in `app/static/js/chart-geo.js`.
- [ ] **Place profiles: dataset page cross-link** — When a dataset is filtered to a single county (via query param `?place=bihor`), show a "View Bihor profile" link in the dataset page header (`app/static/js/dataset-page.js`).
```

- [ ] **Step 8.3: Verify nav link works**

Open `http://localhost:8080` → click "Locuri" in nav → should load `/places`.

- [ ] **Step 8.4: Run full test suite**

```bash
source ~/devbox/envs/240826/bin/activate && python -m pytest tests/test_place_service.py -v
```

Expected: all tests pass.

- [ ] **Step 8.5: Final commit**

```bash
git add app/static/index.html docs/BACKLOG.md
git commit -m "feat(places): add Places nav link + backlog items for deferred features"
```

---

## Verification Checklist

After all tasks are complete:

1. `GET /api/places` → returns list with 42+ counties, 8 regions, 4 macroregions
2. `GET /api/places/county/bihor` → full JSON with kpis, datasets (400+), peers
3. `GET /api/places/county/notaplace` → 404
4. `http://localhost:8080/places` → directory with all counties/regions/macroregions as clickable chips
5. `http://localhost:8080/place/county/bihor` → three sections render without console errors
6. Click a KPI card → comparison chart switches to that indicator
7. Click a peer chip (e.g. "Cluj") → its line overlaid on comparison chart
8. Click the same peer chip again → line removed (toggle)
9. `http://localhost:8080/place/locality/oradea` → if locality resolves, shows graceful partial data; if no locality data, 404
10. `python -m pytest tests/test_place_service.py -v` → all tests pass
11. `tempo_eval_chart_selector` MCP tool → no regressions vs baseline
