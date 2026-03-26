# Plan: SDMX-CSV 2.0 ETL Export Pipeline

## Context
INS TEMPO datasets use a proprietary format: Romanian-language dimension labels, non-standard time period strings ("Anul 1992", "Trimestrul I 1996"), and a flat CSV structure with no SDMX metadata columns. This plan adds `10-sdmx-export.py` to the numbered pipeline, converting all 1,891 datasets to SDMX-CSV 2.0 compliant output. This enables interoperability with Eurostat tooling, pandaSDMX consumers, and standard statistical data exchange.

---

## Output Format (SDMX-CSV 2.0)

```
STRUCTURE,STRUCTURE_ID,ACTION,<DIM_1>,...,<DIM_N>,TIME_PERIOD,UNIT_MEASURE,OBS_VALUE[,OBS_STATUS]
ACC101B,ACC101B,A,21295,1992,NUM,6
ACC101B,ACC101B,A,112,1993,NUM,8
```

- `STRUCTURE` / `STRUCTURE_ID`: matrix code (e.g. `ACC101B`)
- `ACTION`: always `A`
- Dimension columns: `nomItemId` integers (from compacted CSV), named by semantic classifier
- `TIME_PERIOD`: ISO 8601 string
- `UNIT_MEASURE`: `nomItemId` of the UM option
- `OBS_VALUE`: numeric or empty string
- `OBS_STATUS`: only present if confidential/suppressed values exist (`C` for 'c', `S` for 'x')

---

## Critical Files

| File | Role |
|------|------|
| `data/5-compact-datasets/ro/{id}.csv` | **Input**: dimension values already as nomItemIds |
| `data/2-metas/ro/{id}.json` | Dimension definitions, periodicitati, option labels |
| `data/1-indexes/ro/matrices.csv` | Matrix code list for batch iteration |
| `data/6-sdmx-csv/ro/{id}.csv` | **Output**: SDMX-CSV 2.0 files (new dir) |
| `data/6-sdmx-csv/validation_report.csv` | Per-dataset compliance check results |
| `10-sdmx-export.py` | New script (root of project) |

---

## Implementation Plan

### 1. Config Section

```python
CONFIG = {
    "metas_dir": "data/2-metas/ro",
    "compact_csv_dir": "data/5-compact-datasets/ro",
    "output_dir": "data/6-sdmx-csv/ro",
    "matrices_csv": "data/1-indexes/ro/matrices.csv",
    "validation_report": "data/6-sdmx-csv/validation_report.csv",
    "debug": False,
    "skip_existing": True,
}
```

CLI args: `--matrix ACC101B` (single dataset), `--debug`, `--force` (re-process existing).

---

### 2. Time Period Parser

```python
def parse_time_period(label: str) -> str | None
```

**Mapping rules**:

| Input pattern | Output | Example |
|---|---|---|
| `Anul YYYY` | `YYYY` | `Anul 1992` → `1992` |
| `Trimestrul I YYYY` | `YYYY-Q1` | `Trimestrul I 1996` → `1996-Q1` |
| `Trimestrul II YYYY` | `YYYY-Q2` | |
| `Trimestrul III YYYY` | `YYYY-Q3` | |
| `Trimestrul IV YYYY` | `YYYY-Q4` | |
| `Luna N YYYY` | `YYYY-MM` (zero-padded) | `Luna 3 2020` → `2020-03` |
| `Cincinal YYYY-YYYY` | `YYYY-P5Y` (SDMX duration) | `Cincinal 1990-1994` → `1990-P5Y` |
| `La 2 ani YYYY` | `YYYY` (fallback, note in log) | |

Romanian ordinal map: `{"I": 1, "II": 2, "III": 3, "IV": 4}`.

Returns `None` on parse failure — triggers validation warning.

---

### 3. Dimension Classifier

```python
def classify_dimensions(dimensions_map: list) -> dict
```

Given `dimensionsMap` from metadata JSON, returns:
```python
{
  dim_code: {           # 1-based, matches CSV column position
    "sdmx_name": "GEO",   # SDMX column header
    "role": "geo" | "time" | "unit" | "semantic" | "generic"
  }, ...
}
```

**Classification priority** (first match wins):

| Condition | SDMX name | Role |
|---|---|---|
| label contains "Perioade" OR options match time patterns | `TIME_PERIOD` | `time` |
| label starts with "UM:" OR contains " UM" at end | `UNIT_MEASURE` | `unit` |
| label contains "judete" / "regiuni" / "localitati" / "macroregiuni" | `GEO` | `geo` |
| label == "Sexe" OR "Sex" | `SEX` | `semantic` |
| label contains "varsta" OR "grupe de varsta" | `AGE` | `semantic` |
| label contains "rezidenta" OR "mediu" | `RESIDENCE` | `semantic` |
| label contains "activitati economice" | `ECON_ACTIVITY` | `semantic` |
| label contains "nivel de educatie" / "nivel educational" | `EDU_LEVEL` | `semantic` |
| fallback | `DIM_{N}` where N = dimCode | `generic` |

**Note**: TIME_PERIOD and UNIT_MEASURE are extracted from the dimension list and placed at fixed positions in output. Remaining dims become the middle columns.

---

### 4. SDMX Row Builder

```python
def build_sdmx_rows(matrix_id, compact_csv_path, meta, classification) -> list[dict]
```

For each row in the compacted CSV (all values already nomItemIds):
1. Read `n` dimension columns + 1 value column
2. Look up time column → parse to ISO 8601
3. Detect confidential values in OBS_VALUE: `'c'` → `(None, 'C')`, `'x'` → `(None, 'S')`
4. Build output dict:
   ```python
   {
     "STRUCTURE": matrix_id,
     "STRUCTURE_ID": matrix_id,
     "ACTION": "A",
     # all non-time, non-unit dimensions by sdmx_name
     "TIME_PERIOD": parsed_time,
     "UNIT_MEASURE": unit_nomitemid,
     "OBS_VALUE": numeric_value_or_empty,
     # OBS_STATUS only if confidential
   }
   ```

---

### 5. Compliance Checks

```python
def validate_dataset(matrix_id, rows, classification, meta) -> dict
```

Returns a result dict written to `validation_report.csv`. Checks:

| Check | Severity | Description |
|---|---|---|
| `time_parse_ok` | ERROR | All TIME_PERIOD values parse successfully |
| `no_duplicate_keys` | WARNING | No duplicate (all dims + TIME_PERIOD) combos |
| `obs_value_numeric` | ERROR | OBS_VALUE is numeric or empty |
| `unit_dim_identified` | WARNING | UNIT_MEASURE column was found |
| `time_dim_identified` | ERROR | TIME_PERIOD column was found |
| `multi_unit` | INFO | Dataset has >1 unit type (needs UM filter in queries) |
| `row_count` | INFO | Number of output rows |
| `confidential_count` | INFO | Count of suppressed values |

---

### 6. Main Loop

```python
def process_matrix(matrix_id: str) -> dict  # returns validation result
def main():
    matrices = load_matrix_list()
    if args.matrix:
        matrices = [args.matrix]
    results = []
    for mid in tqdm(matrices):
        result = process_matrix(mid)
        results.append(result)
    write_validation_report(results)
```

Error handling: if a dataset fails (missing meta, parse error), log and continue — never abort the batch.

---

### 7. Processing Flow Per Dataset

```
load_meta(id)
  └─ classify_dimensions(meta.dimensionsMap)
       └─ load compact_csv(id)
            └─ build_sdmx_rows(...)
                 ├─ parse_time_period() per row
                 ├─ detect_confidential() per row
                 └─ write output CSV to data/6-sdmx-csv/ro/{id}.csv
validate_dataset(...)
  └─ append to validation_report.csv
```

---

## Verification

1. **Run single dataset** and inspect output:
   ```bash
   python 10-sdmx-export.py --matrix ACC101B --debug
   head -5 data/6-sdmx-csv/ro/ACC101B.csv
   ```
2. **Check validation report**:
   ```bash
   python -c "import pandas as pd; df=pd.read_csv('data/6-sdmx-csv/validation_report.csv'); print(df[df.time_dim_identified==False])"
   ```
3. **Run full batch** and check error rate:
   ```bash
   python 10-sdmx-export.py
   grep -c "ERROR" data/6-sdmx-csv/validation_report.csv
   ```
4. **Spot-check time parsing** on quarterly dataset (e.g., AMG101A):
   ```bash
   python 10-sdmx-export.py --matrix AMG101A --debug
   grep "Q" data/6-sdmx-csv/ro/AMG101A.csv | head -5
   ```
5. **Validate with pandaSDMX** (optional): attempt to load one output file and confirm column structure.
