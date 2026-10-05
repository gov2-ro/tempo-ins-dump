# Profiling & Analysis Scripts — Audit

_Last updated: 2026-03-10_

## Two eras of tooling

The project has accumulated two distinct layers of analysis/profiling code that coexist without fully replacing each other.

**Pre-DuckDB era** (`profiling/` folder, `build-dataset-metadata.py`): built when data lived as raw CSVs in `data/4-datasets/ro/`. Uses pandas, regex rules, and flat JSON output files. The profiler validates download quality (correct column structure, uniform UM, temporal format detection) and emits per-file profiles. These tools operate before or independently of the DuckDB pipeline and are primarily useful for **input QA** — catching broken downloads, irregular structures, or data that will cause problems downstream.

**DuckDB era** (`10-classify-dimensions.py`, `11-coverage-profiler.py`, `detect_trends.py`, agent pipeline): operates on parquet files and the `tempo_metadata.duckdb` database. Produces queryable, enriched metadata tables (`dimension_options_parsed`, `matrix_profiles`, `dataset_coverage`, `dataset_trends`, `dataset_tags`, etc.) used directly by the FastAPI backend and v2 UI. This is the **analysis layer** — not validation, but profiling, classification, and discovery.

The two layers are not in conflict. The pre-DuckDB profiler is still the right tool for raw CSV QA; the DuckDB layer is the right tool for everything that happens after compaction and import.

---

## Script status

| Script | Era | Status | Notes |
|--------|-----|--------|-------|
| `profiling/data_profiler.py` | Pre-DuckDB | **Keep (different purpose)** | Validates raw CSV structure; emits `n-*`/`d-*` flags, UM uniformity, column type detection. Not superseded — serves input QA, not analysis. Output goes to `data/profiling/`. Candidate for `--write-to-duckdb` flag |
| `profiling/variable_classifier.py` | Pre-DuckDB | **Partially superseded** | Rule-based label classification from external CSV ruleset. Label classification is now done more thoroughly in `10-classify-dimensions.py` and `split_rules.py`. Harder to maintain than code-based classifiers. Archive unless a specific pre-import use case is identified |
| `profiling/unit_classifier.py` | Pre-DuckDB | **Partially superseded** | Semantic UM label classifier. Unit classification now lives in `10-classify-dimensions.py` UNIT_MAP. Still useful for pre-import spot checks; note that UNIT_MAP has ~69 missing labels |
| `profiling/validation_rules.py` | Pre-DuckDB | **Keep for input QA** | Modular validation framework. Structural checks (column presence, format). Not superseded |
| `profiling/ins_validation_rules.py` | Pre-DuckDB | **Keep for input QA** | INS-specific rules — produces `n-*` (column name) and `d-*` (column data) flags. Not superseded |
| `profiling/build_indexes.py` | Pre-DuckDB | **Superseded** | Builds keyword/theme indexes from datasets → `data/indexes/`. The `dataset_tags` table (agent 2A, 92K rows, bilingual) is richer and queryable. Can be archived |
| `profiling/tool-list-headers.py` | Pre-DuckDB | **Keep as-is** | Extracts CSV headers → `data/2-csv-cols/ro/`. Useful for spot-checking raw downloads |
| `profiling/tool-sample-csvs.py` | Pre-DuckDB | **Keep as-is** | Creates sampled CSVs (first/mid/last 5 rows). Useful for manual inspection |
| `profiling/tool-word-frequency.py` | Pre-DuckDB | **Keep as-is** | Word frequency on dataset titles. Useful for taxonomy work |
| `build-dataset-metadata.py` | Pre-DuckDB | **Superseded** | Built `ui/data/dataset-metadata.json` for the old static UI. The FastAPI backend now serves metadata directly from DuckDB. File is stale — verify nothing still reads `ui/data/dataset-metadata.json` before archiving |
| `10-classify-dimensions.py` | DuckDB | **Keep, has gaps** | Core classifier → `dimension_options_parsed` (18K unique IDs) + `matrix_profiles` (1,888 rows). Well-documented in `docs/classify-dimensions.md`. Two known gaps: 69 unknown unit labels, 410 foreign country geo labels |
| `11-coverage-profiler.py` | DuckDB | **Keep, current** | → `dataset_coverage` (1,889 rows): time range, fill rate, freshness, geo county count. Used by v2 UI |
| `detect_trends.py` | DuckDB | **Keep, current** | → `dataset_trends` (1,886 rows): trend direction, YoY growth, breakpoints, seasonality. Used by v2 UI |

---

## Known gaps & TODO

### Easy (~30 min each)

- [ ] **Add 69 missing unit labels to `UNIT_MAP`** in `10-classify-dimensions.py`
  Run `python 10-classify-dimensions.py --debug 2>&1 | grep 'unit.*unknown'` to list them.
  See `docs/classify-dimensions.md` §Known Gaps for examples (`kilograme`, `litri`, `bucati`, `mii pasageri`, etc.).
  Re-run `10-classify-dimensions.py` after adding to refresh `dimension_options_parsed`.

- [ ] **Archive `profiling/build_indexes.py`**
  Add deprecation comment at top pointing to `dataset_tags` table in DuckDB.
  No deletion needed — just document the replacement.

### Medium (~1–4 hours each)

- [ ] **Add foreign country name lookup to `parse_geo()` in `10-classify-dimensions.py`** (~1–2h)
  410 option labels are foreign country names (`Franta`, `Germania`, `Italia`, `Austria`, etc.) from international trade and emigration datasets. Currently assigned `geo_level = unknown`.
  Fix: add a lookup dict of ~60 Romanian-language country names → ISO 3166-1 alpha-2 codes and return `geo_level = 'country'`.

- [ ] **Add `--write-to-duckdb` flag to `profiling/data_profiler.py`** (~2–4h)
  Currently validation flags (`n-*`/`d-*`) live only in flat JSON files (`data/profiling/combined/`), not queryable.
  Add an optional flag that upserts per-dataset validation results into a new `dataset_qa` table in `tempo_metadata.duckdb`.
  Schema suggestion: `(matrix_code, um_uniform BOOLEAN, column_flags JSON, file_checked_at TIMESTAMP)`.

### Low priority (maintenance / housekeeping)

- [ ] **Consolidate unit classification** between `profiling/unit_classifier.py` and `10-classify-dimensions.py` UNIT_MAP
  Currently maintained separately — divergence risk. Options: (a) have `profiling/unit_classifier.py` import from `10-classify-dimensions.py`, or (b) extract a shared `unit_labels.py` module.

- [x] **Archive `build-dataset-metadata.py`** — 2026-10-05: `ui/` no longer exists and nothing reads `dataset-metadata.json`; moved to gitignored `_obsolete/`.

- [ ] **Mark `profiling/variable_classifier.py` as reference-only**
  Add comment noting that `10-classify-dimensions.py` and `split_rules.py` supersede its label classification logic for the DuckDB pipeline.

---

## Updated pipeline order

```
6-fetch-csv.py
  → [optional] profiling/data_profiler.py   # raw CSV structure QA (n-*/d-* flags)
7-data-compactor.py
8-setup-duckdb-schema.py
9-csv-to-parquet.py
10-import-metadata.py
10-classify-dimensions.py                   # → dimension_options_parsed, matrix_profiles
11-coverage-profiler.py                     # → dataset_coverage
detect_trends.py                            # → dataset_trends
12-split-datasets.py                        # → parquet-v3/, dataset_splits  [NEW]
  [agent pipeline]
  1A value-profiler      → dataset_value_profiles
  1B coverage-profiler   → (superseded by 11-coverage-profiler.py if already run)
  1C trend-detector      → (superseded by detect_trends.py if already run)
  2A topic-tagger        → dataset_tags
  2B dim-overlap         → dataset_relationships
  2C chart-recommender   → dataset_chart_recs
```

---

## Reference docs

| Doc | Status | Notes |
|-----|--------|-------|
| `docs/data analysis.md` | Framework still valid | Written pre-DuckDB; the approach is correct, the implementation references are outdated |
| `docs/classify-dimensions.md` | Current | Matches `10-classify-dimensions.py`; includes Known Gaps section with actionable TODOs |
| `docs/PROFILING_AND_EXPLORER.md` | Current for its scope | Describes pre-DuckDB profiler and static Explorer UI accurately |
| `docs/agents/README.md` + `pipeline.md` | Current | Modern 7-agent enrichment pipeline; production-ready |
