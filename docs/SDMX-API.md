# SDMX 2.1 REST API

The FastAPI app (`app/`) exposes a minimal SDMX 2.1 REST API that makes INS TEMPO datasets consumable by SDMX-aware tools — in particular the [SDMX Dashboard Generator](https://bis-med-it.github.io/SDMX-dashboard-generator/).

---

## Endpoints

All endpoints are mounted under `/sdmx` on the same FastAPI app (port 8080).

### Data — `GET /sdmx/2.1/data/{agency},{flow}/{key}`

Returns observations in **SDMX-JSON 2.0** format, sourced from `data/parquet-v3/ro/{flow}.parquet`.

| Parameter | Type | Description |
|---|---|---|
| `agency` | path | Must be `INS` |
| `flow` | path | Dataset code (e.g. `ACC102B`) |
| `key` | path | Dot-separated dimension filter (SDMX key syntax). Use `.` or omit for wildcard. |
| `lastNObservations` | query | Return only the last N distinct TIME_PERIOD values |
| `startPeriod` | query | Filter TIME_PERIOD ≥ value (e.g. `2010`) |
| `endPeriod` | query | Filter TIME_PERIOD ≤ value |

**Key syntax:** dots separate dimensions in declaration order. An empty segment means "all values". `+` is an OR separator within a segment.

```bash
# All data
curl 'http://localhost:8080/sdmx/2.1/data/INS,ACC102B/.'

# Filter first dimension to "Mortale", all others wildcard, last 5 time periods
curl 'http://localhost:8080/sdmx/2.1/data/INS,ACC102B/Mortale..?lastNObservations=5'

# Time range
curl 'http://localhost:8080/sdmx/2.1/data/INS,ACC102B/.?startPeriod=2015&endPeriod=2022'
```

### DSD — `GET /sdmx/2.1/datastructure/INS/{flow}/1.0`

Returns an **SDMX-ML 2.1 XML** DataStructure Definition with:
- All dimensions + their codelists (values from `dimension_options`)
- Primary measure `OBS_VALUE`

```bash
curl 'http://localhost:8080/sdmx/2.1/datastructure/INS/ACC102B/1.0'
```

### Dataflow — `GET /sdmx/2.1/dataflow/INS/{flow}/1.0`

Returns an **SDMX-ML 2.1 XML** Dataflow definition with the dataset name and a reference to its DSD.

```bash
curl 'http://localhost:8080/sdmx/2.1/dataflow/INS/ACC102B/1.0'
```

---

## YAML Generator

`generate_sdmx_yaml.py` auto-generates dashboard YAML configs for the SDMX Dashboard Generator. Output goes to `data/sdmx-dashboards/`.

```bash
source ~/devbox/envs/240826/bin/activate

# Specific datasets
python generate_sdmx_yaml.py ACC102B POP105A

# First 20 datasets (useful for testing)
python generate_sdmx_yaml.py --limit 20

# All ~3,700 datasets
python generate_sdmx_yaml.py

# Against a deployed instance
python generate_sdmx_yaml.py --base-url https://ins.gov2.ro

# Skip split sub-datasets (show only parent/standalone)
python generate_sdmx_yaml.py --skip-splits

# Control how many time periods to fetch (default: 10)
python generate_sdmx_yaml.py --last-n 5
```

Chart type is auto-selected from the dataset archetype:

| Archetype | Chart type |
|---|---|
| `geo_time` | `MAP` |
| `time_series` | `LINES` |
| `demographic` | `BARS` |
| `time_residence` | `LINES` |
| (fallback, has REF_AREA) | `MAP` |
| (fallback, has TIME_PERIOD) | `LINES` |

`legendConcept` defaults to `REF_AREA` if present, then first non-time/non-unit dimension.

---

## Using with SDMX Dashboard Generator

The Dashboard Generator lives at `/Users/pax/devbox/gov2/sdmx-fun/SDMX-dashboard-generator/`.
It reads YAML configs from its local `yaml/` directory and fetches data live from SDMX REST endpoints.

### Step 1 — Start the INS API

```bash
cd /Users/pax/devbox/gov2/tempo-ins-dump
source ~/devbox/envs/240826/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### Step 2 — Generate YAML configs

```bash
python generate_sdmx_yaml.py ACC102B   # or --limit 20, or no args for all
```

### Step 3 — Copy YAMLs to Dashboard Generator

```bash
cp data/sdmx-dashboards/*.yaml \
   /Users/pax/devbox/gov2/sdmx-fun/SDMX-dashboard-generator/yaml/
```

### Step 4 — Run the Dashboard Generator

```bash
cd /Users/pax/devbox/gov2/sdmx-fun/SDMX-dashboard-generator
source venv/bin/activate
python app.py
# → http://127.0.0.1:8050
```

In the UI: use the YAML selector to pick a config. The app fetches live data from the FastAPI on port 8080.

> Both servers must be running simultaneously: FastAPI on `8080`, Dash on `8050`.

---

## Implementation Notes

- **Source data**: `data/parquet-v3/ro/` — SDMX-native column names (`REF_AREA`, `TIME_PERIOD`, `UNIT_MEASURE`, `OBS_VALUE`), human-readable string values
- **Metadata**: `data/tempo_metadata.duckdb` — `dimensions`, `dimension_options`, `matrices` tables
- **Router**: `app/routers/sdmx.py`, mounted at `/sdmx` in `app/main.py`
- **Max rows**: 50,000 per data request (same as the regular API)
- **v2 fallback**: If no parquet-v3 file exists for a dataset, the data endpoint falls back to parquet-v2 (numeric IDs — labels will be raw codes in that case)
