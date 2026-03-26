# Plan: Expose INS TEMPO data for SDMX Dashboard Generator

## Context
The SDMX Dashboard Generator (https://bis-med-it.github.io/SDMX-dashboard-generator/) is a Plotly/Python tool that renders dashboards from YAML configs. It fetches data exclusively from **live SDMX 2.1 REST API endpoints** — no local file support. It uses the `sdmxthon` library to parse responses.

The INS TEMPO project already has all the raw material ready:
- **parquet-v3** files with SDMX-native column names (`REF_AREA`, `TIME_PERIOD`, `UNIT_MEASURE`, `OBS_VALUE`) and human-readable string values
- **`sdmx_codes`** table (18,203 rows): nomItemId → sdmx_value mappings
- **`sdmx_column_map`** table (10,683 rows): old column → SDMX concept name per dataset
- **`tempo_metadata.duckdb`**: full structural metadata (dimensions, codelists, contexts)
- **FastAPI app** at `app/main.py` already serving data from parquet-v3

The gap: no SDMX 2.1 REST API layer. Goal: add minimal SDMX endpoints to the existing FastAPI app so YAML configs can point to `http://localhost:8080/sdmx/...`.

---

## What the Dashboard Generator Needs

### YAML config structure (per dataset/chart):
```yaml
DashID: INS_ACC102B
Rows:
  - Row: 0
    chartType: LINES
    Title: Accidents at work
    DATA: http://localhost:8080/sdmx/2.1/data/INS,ACC102B/..?lastNObservations=10
    dsdLink: http://localhost:8080/sdmx/2.1/datastructure/INS/ACC102B/1.0
    metadataLink: http://localhost:8080/sdmx/2.1/dataflow/INS/ACC102B/1.0
    xAxisConcept: TIME_PERIOD
    yAxisConcept: OBS_VALUE
    legendConcept: REF_AREA
```

### 3 required endpoint types:
| Endpoint | Returns | Format |
|---|---|---|
| `/sdmx/2.1/data/{agency},{flow}/{key}` | Observations | SDMX-JSON 2.0 |
| `/sdmx/2.1/datastructure/INS/{flow}/1.0` | DSD (dimensions + codelists) | SDMX-ML 2.1 XML |
| `/sdmx/2.1/dataflow/INS/{flow}/1.0` | Dataflow definition | SDMX-ML 2.1 XML |

---

## Implementation Plan

### Step 1 — New router `app/routers/sdmx.py`

**Data endpoint** `GET /sdmx/2.1/data/INS,{flow}/{key}`
- Parse `key` as dot-separated dimension filters (SDMX key syntax, `.` = wildcard)
- Query `data/parquet-v3/ro/{flow}.parquet` via DuckDB
- Apply `lastNObservations` / `startPeriod` / `endPeriod` query params
- Return **SDMX-JSON 2.0** format — a JSON structure `sdmxthon` can parse:
  ```json
  {
    "meta": {...},
    "data": {
      "dataSets": [{ "observations": { "0:0:0": [value] } }],
      "structure": { "dimensions": { "series": [...], "observation": [...] } }
    }
  }
  ```

**DSD endpoint** `GET /sdmx/2.1/datastructure/INS/{flow}/1.0`
- Pull dimensions from DuckDB `dimensions` table for `flow`
- Build minimal SDMX-ML 2.1 XML with `DataStructure` + `DimensionList` + `AttributeList`
- Include codelists built from `sdmx_codes` per dimension

**Dataflow endpoint** `GET /sdmx/2.1/dataflow/INS/{flow}/1.0`
- Return minimal SDMX-ML XML with dataflow name from `matrices` table
- Reference the DSD

### Step 2 — Register router in `app/main.py`
```python
from app.routers import sdmx
app.include_router(sdmx.router, prefix="/sdmx", tags=["sdmx"])
```

### Step 3 — YAML generator script `generate_sdmx_yaml.py`
- For each dataset in `matrices` (or a specified list), emit a YAML file to `sdmx-dashboards/`
- Auto-select `legendConcept` from `sdmx_column_map` (prefer REF_AREA, then DIM_1)
- Auto-select `chartType` based on dataset archetype (`geo_time` → MAP/BAR, time series → LINES)
- Set `DATA` URL pointing to localhost

### Step 4 — Test with Dashboard Generator
```bash
# Start FastAPI
uvicorn app.main:app --reload --port 8080

# Run dashboard generator pointing at a generated YAML
python -m streamlit run app.py -- --path sdmx-dashboards/ACC102B.yaml
```

---

## Critical Files
- **Modify**: `app/main.py` — register new sdmx router
- **Create**: `app/routers/sdmx.py` — 3 endpoints (~150 lines)
- **Create**: `generate_sdmx_yaml.py` — YAML generator script
- **Reference**: `app/db.py` — reuse `get_conn()` cursor pattern
- **Reference**: `app/routers/dataset_data.py` — reuse parquet query patterns
- **Data**: `data/parquet-v3/ro/` — source parquet files
- **Data**: `data/tempo_metadata.duckdb` — dimensions, sdmx_codes, sdmx_column_map, matrices

## Verification
1. `curl http://localhost:8080/sdmx/2.1/data/INS,ACC102B/.` — should return SDMX-JSON
2. `curl http://localhost:8080/sdmx/2.1/datastructure/INS/ACC102B/1.0` — should return XML
3. Run dashboard generator with a generated YAML — chart should render
4. Test with `lastNObservations=5` param — should return last 5 time periods only
