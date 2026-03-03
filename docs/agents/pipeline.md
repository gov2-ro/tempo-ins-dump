# Sub-Agent Pipeline — Orchestration Guide

## Overview

7 agents in 3 phases. Phase 1 agents are independent and can run in parallel (but DuckDB write lock prevents true parallel writes — use fallback DBs or run sequentially). Phase 2 agents depend on Phase 1 outputs. Phase 3 depends on everything.

```
Phase 1 (data profiling — independent):
  1A: Value Profiler      → dataset_value_profiles
  1B: Coverage Profiler   → dataset_coverage
  1C: Trend Detector      → dataset_trends

Phase 2 (classification — needs Phase 1):
  2A: Topic Tagger        → dataset_tags
  2B: Dimension Overlap   → dataset_relationships
  2C: Chart Recommender   → dataset_chart_recs   (needs 1A, 1B, 1C)

Phase 3 (design — needs everything):
  3A: IA Designer         → docs/app-spec-v2.md
```

## Pre-Flight Checklist

Before launching any agent:

```bash
# 1. Activate your Python environment
source ~/devbox/envs/240826/bin/activate

# 2. Stop the dev server (releases DuckDB write lock)
lsof -ti :8080 | xargs kill 2>/dev/null

# 3. Verify DB is unlocked
python3 -c "import duckdb; c = duckdb.connect('data/tempo_metadata.duckdb'); print('OK'); c.close()"

# 4. Check parquet files exist
ls data/parquet-v2/ro/*.parquet | wc -l  # should be ~1886
```

## Step-by-Step Execution

### Step 1: Run Phase 1 agents

Each writes to the main DB if unlocked, or to a fallback `.duckdb` if locked.

**Option A — Sequential (safe):**
```
Launch 1A → wait → Launch 1B → wait → Launch 1C → wait
```

**Option B — Parallel with fallbacks (faster):**
```
Launch 1A, 1B, 1C as background agents simultaneously.
Each will write to a fallback DB if locked.
After all complete, run the merge script (see below).
```

### Step 2: Merge fallback DBs (if needed)

After Phase 1, any tables that ended up in fallback files need to be merged:

```python
import duckdb, os

conn = duckdb.connect('data/tempo_metadata.duckdb')

fallbacks = {
    'dataset_value_profiles': 'data/value_profiles.duckdb',
    'dataset_coverage':       'data/dataset_coverage.duckdb',
    'dataset_trends':         'data/dataset_trends.duckdb',
}

for table, fallback_path in fallbacks.items():
    if not os.path.exists(fallback_path):
        continue
    # Check if table already in main DB
    existing = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if existing > 0:
        print(f"  {table}: already in main DB ({existing} rows)")
        continue
    print(f"  Merging {table} from {fallback_path}...")
    conn.execute(f"ATTACH '{fallback_path}' AS fb")
    conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(f"CREATE TABLE {table} AS SELECT * FROM fb.{table}")
    cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"  Done: {cnt} rows")
    conn.execute("DETACH fb")

conn.close()
```

### Step 3: Verify Phase 1

```python
import duckdb
conn = duckdb.connect('data/tempo_metadata.duckdb', read_only=True)
for t in ['dataset_value_profiles', 'dataset_coverage', 'dataset_trends']:
    cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {cnt} rows")
conn.close()
# Expected: ~1886 rows each
```

### Step 4: Run Phase 2 agents

2A and 2B are independent. 2C needs all Phase 1 tables.

```
Launch 2A → wait
Launch 2B → wait (or parallel with 2A, but DuckDB lock applies)
Launch 2C → wait (after 1A, 1B, 1C all confirmed)
```

### Step 5: Verify Phase 2

```python
import duckdb
conn = duckdb.connect('data/tempo_metadata.duckdb', read_only=True)
for t in ['dataset_tags', 'dataset_relationships', 'dataset_chart_recs']:
    cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {cnt} rows")
# Expected: ~92K tags, ~18K relationships, ~5K recs
```

### Step 6: Run Phase 3

Phase 3 reads all enriched tables and writes a spec document. It's a `general-purpose` agent (not `Bash`).

```
Launch 3A → wait → review docs/app-spec-v2.md
```

## Adapting for a New NSI Project

The following parameters vary per project. Update them at the top of each agent prompt:

| Parameter | INS TEMPO value | What it is |
|---|---|---|
| `DB_PATH` | `data/tempo_metadata.duckdb` | Main DuckDB database path |
| `PARQUET_DIR` | `data/parquet-v2/ro/` | Directory of dataset parquet files |
| `EN_MATRICES_CSV` | `data/1-indexes/en/matrices.csv` | English dataset name translations |
| `EN_CONTEXT_CSV` | `data/1-indexes/en/context.csv` | English category hierarchy |
| `GEO_UNIT_COUNT` | 42 | Total number of sub-national geo units (counties, provinces, etc.) |
| `CURRENT_YEAR` | 2026 | For freshness calculation |
| `COUNTRY_GEOJSON` | `app/static/geo/romania-counties.geojson` | GeoJSON for choropleth maps |

## Time & Cost Estimates (INS TEMPO, 1,886 datasets)

| Agent | Wall time | Tool calls | Notes |
|---|---|---|---|
| 1A Value Profiler | ~7s | 5 | Fast — pure DuckDB aggregates |
| 1B Coverage Profiler | ~7s | 25 | Reads parquet per dataset |
| 1C Trend Detector | ~5s | 14 | Reads parquet per dataset |
| 2A Topic Tagger | ~2min | 5 | CSV reads + text processing |
| 2B Dimension Overlap | ~30s | 9 | Group-based pairwise comparison |
| 2C Chart Recommender | ~2min | 7 | Reads Phase 1 tables + rules |
| 3A IA Designer | ~9min | 33 | Research + writing spec |

Total: ~15 minutes end-to-end for 1,886 datasets.
