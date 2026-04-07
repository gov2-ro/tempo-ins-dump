# Plan: Geo Hierarchy Split (Pattern F)

## Context
405 datasets use the dimension `"Macroregiuni, regiuni de dezvoltare si judete"` which packs 3 geographic entity levels into a single flat column. This prevents choropleth maps and region-level charts from being used cleanly — the chart layer needs a homogeneous set of entities (all counties, or all regions). The `charting notes.md` doc explicitly calls for "3 maps: judete, regiuni, macroregiuni" for datasets like POP107B.

The split infrastructure (12-split-datasets.py, split_rules.py, dataset_splits table) already exists with 5 patterns (A–E). This adds **Pattern F: geo_hierarchy**.

**English version note:** The same split will eventually need to be applied to the `eng` parquet files. Since rows are in the same order and the numeric `nom_item_id` values are shared across languages, the split IDs detected from `ro` can be reused directly — defer to a later task.

---

## Scope of Mixed Geo Dimensions Found
| Dimension Label | Datasets | Split target |
|---|---|---|
| `Macroregiuni, regiuni de dezvoltare si judete` | 405 | **Pattern F** (this plan) |
| `Macroregiuni si regiuni de dezvoltare` | 60 | Pattern F (subset — only 2 levels) |
| `Municipii si orase` | 4 | Separate future task |
| `Judete` (contains Municipiul Bucuresti) | 275 | Quirk only, no split needed |
| `Localitati` | 176 | Already handled by Pattern D |

---

## Implementation Plan

### 1. Add Pattern F detection to `split_rules.py`

Add function `detect_geo_hierarchy(conn) -> list[SplitRule]` that:

```sql
-- Find all datasets whose dimension label matches geo hierarchy patterns
SELECT d.matrix_code, d.dimension_id, d.dim_column_name, d.dim_label
FROM dimensions d
WHERE LOWER(d.dim_label) LIKE '%macroregiuni%'
  AND (LOWER(d.dim_label) LIKE '%judete%' OR LOWER(d.dim_label) LIKE '%regiuni%')
```

For each matched dataset, query `dimension_options_parsed` to get the `geo_level` values and their `nom_item_id`s:
```sql
SELECT dop.nom_item_id, dop.geo_level
FROM dimension_options_parsed dop
WHERE dop.dimension_id = ?
  AND dop.geo_level IN ('county', 'region', 'macroregion', 'national')
```

Emit **3 SplitRule entries** per dataset (or 2 for the shorter `macroregiuni si regiuni` variant):
- `_judete` — where geo_level = 'county' (42–43 values)
- `_regiuni` — where geo_level = 'region' (8 values)
- `_macroregiuni` — where geo_level = 'macroregion' (4 values)

(Skip `_macroregiuni` if only 2-level dimension; only emit `_regiuni` for `macroregiuni si regiuni de dezvoltare`)

Register pattern name: `"geo_hierarchy"`

### 2. Add splitting logic to `12-split-datasets.py`

Add handler `_split_geo_hierarchy(conn, src, dst, rule, group)`:
- Read source parquet (from `parquet-v2/ro/`)
- Filter rows where `{dim_column_name} IN ({nom_item_ids for this level})`
- Write filtered parquet to `parquet-v3/ro/{SUB_CODE}.parquet`
- Register in `dataset_splits` with `split_pattern='geo_hierarchy'`
- Copy dimension metadata (excluding the geo hierarchy dim, replacing with a narrowed version)

Sub-dataset naming: `{PARENT_CODE}_judete`, `{PARENT_CODE}_regiuni`, `{PARENT_CODE}_macroregiuni`

Display name: `"{original name} [județe]"` etc.

### 3. Wire pattern F into the main loop

In `12-split-datasets.py` main execution, add `detect_geo_hierarchy` to the list of detection functions alongside the existing 5 patterns.

Support `--pattern geo_hierarchy` CLI flag for targeted runs.

---

## Files to Modify
- [split_rules.py](split_rules.py) — add `detect_geo_hierarchy()` function
- [12-split-datasets.py](12-split-datasets.py) — add `_split_geo_hierarchy()` handler + wire into main loop

---

## Task Backlog Note
No dedicated task/backlog file exists in the repo. The closest is `docs/TODO_COMPACTION.md` (scoped to compaction only). **Recommendation:** Create `docs/BACKLOG.md` with future tasks, including:
- [ ] Replicate geo_hierarchy split for English (`eng`) parquet files
- [ ] Handle `Municipii si orase` (4 datasets) — city/town split
- [ ] Explore `Macroregiuni si regiuni de dezvoltare` (60 datasets) — 2-level variant

---

## Verification
```bash
source ~/devbox/envs/240826/bin/activate

# Dry run to see what would be detected
python 12-split-datasets.py --pattern geo_hierarchy --dry-run

# Run on a single dataset first
python 12-split-datasets.py --matrix POP107B --pattern geo_hierarchy

# Verify output
ls -la data/parquet-v3/ro/POP107B_*.parquet
python -c "
import duckdb
conn = duckdb.connect('data/tempo_metadata.duckdb')
print(conn.execute(\"SELECT * FROM dataset_splits WHERE parent_matrix_code='POP107B'\").fetchall())
"

# Full run
python 12-split-datasets.py --pattern geo_hierarchy
```
