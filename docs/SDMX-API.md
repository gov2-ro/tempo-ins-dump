# SDMX 2.1 REST API

> Status (FIX-01 phase 2): the DSD, data and key parsing share one code registry
> (`app/services/sdmx_registry.py`) and XML is built with an XML serializer. The
> 50,000-observation limit remains and exports are not complete; see
> [FIX-04](fixes/04-complete-exports.md). Structural validity is tested with a
> hand-written SDMX 2.1 structure checker, not the official XSDs.

The FastAPI app (`app/`) exposes a minimal SDMX 2.1 REST API that makes INS TEMPO datasets consumable by SDMX-aware tools — in particular the [SDMX Dashboard Generator](https://bis-med-it.github.io/SDMX-dashboard-generator/).

---

## Endpoints

All endpoints are mounted under `/sdmx` on the same FastAPI app (port 8080).

### Data — `GET /sdmx/2.1/data/{agency},{flow}/{key}`

Returns observations in **SDMX-ML 2.1 GenericData XML** format (flat `AllDimensions` mode), sourced from `data/parquet-v3/ro/{flow}.parquet`.

> `sdmxthon` (used by the Dashboard Generator) only parses XML — SDMX-JSON is not supported by that library.

| Parameter | Type | Description |
|---|---|---|
| `agency` | path | Must be `INS` |
| `flow` | path | Dataset code (e.g. `ACC102B`) |
| `key` | path | Dot-separated dimension filter (SDMX key syntax). Use `.` or omit for wildcard. |
| `lastNObservations` | query | Return only the last N distinct TIME_PERIOD values (integer 1..10000) |
| `startPeriod` | query | Lower period bound: `YYYY`, `YYYY-Q1`..`YYYY-Q4` or `YYYY-MM` |
| `endPeriod` | query | Upper period bound, same formats |

**Period bounds.** Only the three formats above are accepted (month `01`..`12`,
quarter `Q1`..`Q4`). Each period is a span of months: `startPeriod` means the first
month it covers, `endPeriod` the last. A row is returned when its own period lies
wholly inside `[startPeriod, endPeriod]`. Granularities may be mixed:
`startPeriod=2020` on monthly data starts at 2020-01 and `endPeriod=2020` ends at
2020-12; an annual row is *not* returned for `startPeriod=2020-Q2` (it starts before
the bound). Rows whose TIME_PERIOD is not in one of the three formats (legacy labels
such as `Anul 2020`) never match a bound, but are returned when no bound is given.
All user values are bound SQL parameters.

**Error responses** (`{"detail": "..."}`):

| Status | Cause |
|---|---|
| 400 | malformed `startPeriod`/`endPeriod`; `startPeriod` later than `endPeriod`; key with more non-empty segments than the dataset has dimensions; ambiguous key segment; period parameters on a dataset without TIME_PERIOD |
| 404 | unknown dataset, or a flow code that is not `[A-Za-z0-9_]{1,64}` |
| 422 | `lastNObservations` not an integer >= 1 |
| 500 | internal query failure — body is only `{"detail": "Query failed"}`; details are in the server log |

**Key syntax:** dots separate dimensions in declaration order (the `position` attribute
of the DSD). An empty segment means "all values". `+` is an OR separator within a segment.

**Codes and keys (canonical vs legacy).** Prefer *canonical* keys: the code IDs published in
the DSD codelists. A stored value that is already a valid SDMX ID (`[A-Za-z0-9_@$-]+`, up to
64 characters; e.g. `Total`) is its own code; any other value (spaces, punctuation, accents,
quotes) gets `<ascii slug>_<12 hex of sha1(full value)>`. IDs never depend on truncated
labels, are stable across rebuilds and are collision-free. Labels are separate (`common:Name`,
`xml:lang="ro"`, plus `en` when available). *Legacy* keys, the raw stored value (what the API
accepted before), still work when unambiguous. A segment that matches two different values (one
by code ID, another verbatim) is rejected with 400 `Ambiguous key segment ...`; use the code ID.
A segment that matches nothing returns no observations. Raw values that contain `.`, `+` or `/`
can only be addressed by code ID.

**TIME_PERIOD** is a `TimeDimension` (no codelist, `ObservationalTimePeriod`). Emitted periods are
normalized (`2004-03`, `2020-Q2`, `2020`; INS labels such as `Luna martie 2004` are parsed).
In a key, a period segment matches either the normalized or the stored form. Period parameters
apply to the stored values (legacy labels never match a bound).

```bash
# All data
curl 'http://localhost:8080/sdmx/2.1/data/INS,ACC102B'

# Filter first dimension to "Mortale", all others wildcard, last 5 time periods
curl 'http://localhost:8080/sdmx/2.1/data/INS,ACC102B/Mortale..?lastNObservations=5'

# Time range
curl 'http://localhost:8080/sdmx/2.1/data/INS,ACC102B?startPeriod=2015&endPeriod=2022'
```

### DSD — `GET /sdmx/2.1/datastructure/INS/{flow}/1.0`

Returns an **SDMX-ML 2.1 XML** `Structure` message (with `Header`) containing:
- one `Codelist` (`CL_{dimension}`) per enumerated dimension with **all** codes: metadata options
  plus every value present in the data (no size cutoff), so every value emitted by the data
  endpoint is declared
- a `ConceptScheme` (`{flow}_CS`) for dimensions and `OBS_VALUE`
- the `DataStructure`: `Dimension` elements (codelist-enumerated), `TimeDimension` TIME_PERIOD, primary measure `OBS_VALUE`

Dimension IDs are the canonical names (stale `*_nom_id` metadata names are mapped through
`sdmx_column_map` / `resolve_parquet_schema`).

```bash
curl 'http://localhost:8080/sdmx/2.1/datastructure/INS/ACC102B/1.0'
```

### Dataflow — `GET /sdmx/2.1/dataflow/INS/{flow}/1.0`

Unknown datasets return 404. A `version` that is not a valid SDMX version is answered as `1.0`. Returns an **SDMX-ML 2.1 XML** Dataflow definition with the dataset name and a reference to its DSD.

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

Each YAML has two rows: `Row: 0` is a `TITLE` entry (required by the Dashboard Generator schema), `Row: 1` is the actual chart. `Unit: null` is a required field.

Chart type is auto-selected from the dataset archetype:

Supported chart types: `VALUE`, `PIE`, `BAR`, `LINE` (anything else also renders as line/time-series).

| Archetype | Chart type |
|---|---|
| `geo_time` | `BAR` |
| `time_series` | `LINE` |
| `demographic` | `BAR` |
| `time_residence` | `LINE` |
| (fallback, has TIME_PERIOD) | `LINE` |
| (fallback, no TIME_PERIOD) | `BAR` |

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
