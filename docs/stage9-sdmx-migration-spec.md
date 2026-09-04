# Spec: stage 9 emits SDMX directly; retire stage 12

**Status:** approved 2026-09-04, not started
**Audience:** the implementing model (Sonnet). Read the whole document before writing
code — §4 (repo traps) and §7 (when to escalate) especially.
**Background:** `docs/activity-history.md`, entries 2026-09-04 and 2026-09-04b.

---

## 1. Context

`data/corpus/parquet/` has two writers, and one of them destroys the other's work.

| script | reads | writes | state of its output |
|---|---|---|---|
| `9-csv-to-parquet.py` | `data/4-datasets/ro/*.csv` (original labels) | `data/corpus/parquet/` | **complete and current** |
| `12-parquet-to-sdmx.py` | `data/parquet-v2/ro/` | `data/corpus/parquet/` | **lossy, from Feb 2026** |

`data/parquet-v2/` is 98% a Feb–Apr 2026 snapshot produced by `7-data-compactor.py`,
which is commented out of `update-pipeline.py` (line 385). That compactor matched CSV
labels to metadata labels literally. INS publishes comma-delimited CSVs and rewrites
commas inside values as double spaces, so `De calatori, de cale normala` arrives as
`De calatori  de cale normala` and never matched. **Every comma-bearing label became
NULL.**

Measured damage:

- 1,108 of 3,769 canonical parquets carry NULL dimension values (3.6M of 87.5M rows).
- 51 files where *every* row has a NULL dimension.
- Of the 482 with an original CSV to compare against, a random sample of 60 was
  **60/60 losing dimension values**.
- `TUR104C`: 3 of 6 tourist destinations gone; 188 of 380 rows NULL. All three missing
  labels contain a comma.

`app/services/query_builder.py` adds `"col" IS NOT NULL` to every grouped query, so
those rows vanish from charts, headlines and rankings with no indication to the user.

**The data is recoverable.** The original CSVs are intact. Re-running stage 9 on
`TRN113A` reproduced all 7 wagon types and matched a known-good backup exactly.

**Goal:** `9-csv-to-parquet.py` writes SDMX-canonical parquet directly from the CSVs.
`12-parquet-to-sdmx.py` leaves the pipeline. One writer, one format, one place a fault
of this kind can enter.

---

## 2. Target design

Stage 9 gains the transformation stage 12 does today, but starts from **labels** instead
of the compactor's integer IDs.

```
data/4-datasets/ro/{code}.csv        (text labels, commas mangled to double spaces)
        │
        │  1. read CSV                     (existing code, unchanged)
        │  2. map each dimension value:
        │       time dims  -> parse_time_period(label)
        │       other dims -> normalised label lookup -> sdmx_codes.sdmx_value
        │       no match   -> keep cleaned original text + record it
        │  3. rename columns via sdmx_column_map (value -> OBS_VALUE)
        │  4. write to a temp file, then atomic rename
        ▼
data/corpus/parquet/{code}.parquet   (SDMX column names, SDMX values, OBS_VALUE)
```

### 2.1 Label normalisation

This one function is the heart of the fix. Apply it to **both sides** of every lookup.

```python
def norm_label(s: str) -> str:
    """Normalise a dimension label for matching.

    INS emits comma-delimited CSVs and replaces commas inside values with
    spaces, so 'De calatori, de cale normala' arrives as
    'De calatori  de cale normala'. Metadata labels also carry leading
    indentation that encodes hierarchy depth. Neither survives a literal
    comparison.
    """
    return re.sub(r"\s+", " ", str(s or "").replace(",", " ")).strip().lower()
```

**Validated:** against 120 matrices / 4,550,344 cells this matches **99.91%**. The
residual is almost entirely time periods newer than the metadata (`Luna februarie 2026`),
which §2.2 removes as a class.

### 2.2 Time dimensions are parsed, never looked up

`sdmx_codes` only contains periods that existed when metadata was last refreshed, so a
new month is guaranteed to miss. Reuse the existing parser instead:

```python
# 11-build-sdmx-codes.py:61
parse_time_period(label) -> str | None     # 'Anul 2020'          -> '2020'
                                           # 'Trimestrul IV 2024' -> '2024-Q4'
                                           # 'Luna februarie 2026'-> '2026-02'
```

A dimension is a time dimension when `sdmx_column_map.sdmx_column_name == 'TIME_PERIOD'`
for that matrix and column. If `parse_time_period` returns `None`, fall back to the
normalised lookup, then to §2.3.

Do **not** copy this parser. Move it, with `ROMANIAN_MONTHS` / `ROMANIAN_ORDINALS` and
`_TIME_PATTERNS`, into a shared module (suggested: `sdmx_labels.py` at the repo root
alongside `duckdb_config.py`) and import it from both scripts. A second copy will drift.

### 2.3 Unmatched labels: keep the text, record it, warn

**Never write NULL.** That is the bug this whole exercise exists to remove.

1. Write the cleaned original label as the value.
2. Append a row to a new DuckDB table `unmapped_labels`:
   `(matrix_code, dim_column_name, raw_label, row_count, seen_at)`.
   Replace that matrix's rows on each run — do not accumulate duplicates.
3. Log one summary line per dataset: `CODE: N unmatched of M cells (P%)`.
4. **Exit non-zero only if a dataset is more than 50% unmatched.** That threshold means
   something structural broke, not that a few new options appeared.

```
ART123A:   7 unmatched of 4,412 cells  (0.2%)   -> OK, logged
TUR104C: 188 unmatched of   380 cells (49.5%)   -> OK, loud warning
XXX999A: 900 unmatched of 1,000 cells (90.0%)   -> exit 1
```

### 2.4 Column renaming

`sdmx_column_map` is already built and already keyed the right way:

```sql
SELECT old_column_name, sdmx_column_name FROM sdmx_column_map WHERE matrix_code = ?
```

`old_column_name` is exactly `duckdb_config.sanitize_column_name(dim_label)` — the name
stage 9 already generates. **Verified: 440 of 447 columns across 150 sampled matrices
match.** The 7 misses are all `ani_nom_id`, a second time-like dimension the map skipped
as a truncation collision.

For split children, look the map up under the parent (`matrices.parent_matrix_code`) —
`app/services/query_builder.py:resolve_parquet_schema()` already does this; copy that
lookup, do not reinvent it.

An unmapped column must **not** silently keep its old name (that is what stage 12 does
today via `rename.get(col, col)`, and it is why "canonical" parquets can still contain an
`ani_nom_id` column). Record it in `unmapped_labels` with `raw_label = '<column>'` and
warn.

### 2.5 Writing

Write to `{target}.parquet.tmp`, then `os.replace()` onto the final path. Stage 9's
output directory is also its own read path in some flows; a partial write must never
leave a truncated corpus file.

---

## 3. What already exists — reuse, do not rewrite

| what | where |
|---|---|
| `parse_time_period()`, `_TIME_PATTERNS`, month/ordinal maps | `11-build-sdmx-codes.py:46,61` |
| `sanitize_column_name()` | `duckdb_config.py:62` |
| Path constants | `duckdb_config.py:20-38` |
| Parent lookup for split children | `app/services/query_builder.py:resolve_parquet_schema()` |
| Transformation semantics to mirror (id→value, rename, strip-totals) | `12-parquet-to-sdmx.py:94-200` |
| `sdmx_codes` (nom_item_id → sdmx_value), `sdmx_column_map` | `data/corpus/metadata.duckdb` |
| Label → nom_item_id per matrix/dim | `dimensions` ⋈ `dimension_options` |

Build the per-matrix lookup once per run, not per file:

```sql
SELECT d.matrix_code, d.dim_code, d.dim_column_name, o.option_label, s.sdmx_value
FROM dimensions d
JOIN dimension_options o ON o.dimension_id = d.dimension_id
LEFT JOIN sdmx_codes  s ON s.nom_item_id  = o.nom_item_id
```

CSV column order matches `dimensions.dim_code` order. Verify this per matrix against
`dimensionsMap` in `data/2-metas/ro/{code}.json` rather than assuming it.

---

## 4. Repo traps

Read these before you touch anything.

1. **`duckdb_config.PARQUET_DIR` is `CORPUS_PARQUET_DIR`.** Despite the module name,
   stage 9 already writes straight into the live corpus. Running
   `9-csv-to-parquet.py --matrix X --force` overwrites `data/corpus/parquet/X.parquet`
   immediately. This caught me on 2026-09-04. **During development, override the output
   path to a shadow directory — never let a test run touch the corpus.**
2. **DuckDB allows one writer.** Stop the dev server (`lsof -ti:8099 | xargs kill`) before
   any script that writes to the DB. Open read-only where you only read.
3. **`12-split-datasets.py` also reads `PARQUET_V2_DIR`** (line 147-169) and writes split
   children back there when the source is v2. It must be repointed before
   `data/parquet-v2/` can be deleted. Do not delete that directory in this task.
4. **Some matrices declare several dimensions with the same column name** (INT109C has
   four `ECON_ACTIVITY`). Handle duplicates explicitly; do not let a dict silently collapse
   them.
5. **The app's legacy adapter must stay** (`resolve_parquet_schema` / `adapt_to_parquet`
   in `app/services/query_builder.py`). Remove it only once zero legacy parquets remain,
   and as a separate change.
6. **Do not run `12-parquet-to-sdmx.py`** on any matrix during this work. It will
   overwrite good stage-9 output with the February version.

---

## 5. Implementation phases

Commit at the end of each phase. Do not start the next phase with the previous one failing.

### Phase A — shared label module, no behaviour change
- Create `sdmx_labels.py`: `norm_label()`, and `parse_time_period()` moved out of
  `11-build-sdmx-codes.py` with its patterns and month/ordinal maps.
- `11-build-sdmx-codes.py` imports from it. Its output must be byte-identical: run it
  with `--dry-run` and diff the reported counts against a run on `git stash`.
- Unit tests for `norm_label()` covering the comma case, indentation, and repeated spaces.

### Phase B — mapping layer with a shadow output
- Add `--out-dir` to `9-csv-to-parquet.py`, defaulting to `CORPUS_PARQUET_DIR`.
  Every development and verification run passes an explicit shadow directory.
- Implement §2.1–§2.5. Add the `unmapped_labels` table (create if not exists).
- Add `--matrix` support if absent, and make the script exit non-zero on failure
  (see `12-parquet-to-sdmx.py`'s 2026-09-02 fix for the pattern).
- Validate on these, which exercise every branch:

  | matrix | why |
  |---|---|
  | `TUR104C` | comma labels — 3 of 6 values currently lost |
  | `TRN113A` | comma labels — 5 of 7 values currently lost |
  | `FOM108D` | time periods newer than the metadata |
  | `INT109C` | four dimensions sharing one column name |
  | `POP107D` | large (21.6M rows) — check memory and runtime |
  | `ART101C` | known-good headline (8,105) that must not move |

### Phase C — full shadow regeneration + comparison report
- Regenerate **all** datasets into the shadow directory.
- Produce `docs/reports/stage9-sdmx-migration.md` with the gates in §6.
- **Stop here.** Do not swap. The user runs the swap.

### Phase D — pipeline wiring (code only, not executed)
- Remove step (e) `12-parquet-to-sdmx.py` from `update-pipeline.py` (line ~396).
- Mark `12-parquet-to-sdmx.py` deprecated in its docstring; do not delete it yet.
- Update `CLAUDE.md`'s pipeline table and `readme.md`.
- Add an entry to `docs/activity-history.md`.

---

## 6. Verification gates

All of these run against the **shadow** directory versus the current corpus. Report every
number; do not summarise a failure away.

| # | gate | pass condition |
|---|---|---|
| 1 | NULL dimension values in shadow output | **0** across all files |
| 2 | Row count per file vs its CSV row count | equal for every file |
| 3 | `SUM(OBS_VALUE)` vs current corpus | equal within 1e-9 relative, **or** the difference is explained by rows the current corpus dropped as NULL |
| 4 | Distinct values per dimension vs the CSV | shadow ≥ current for every dimension; never fewer |
| 5 | Column names | every file has `OBS_VALUE`; no `*_nom_id` columns remain |
| 6 | `unmapped_labels` | reported in full; no dataset above 50% |
| 7 | chart_selector eval gate | `primary_changed`, `top_set_changed`, `confidence_changed`, `score_drift` all **0** |
| 8 | Tile sweep | 0 non-200 across all composed tiles |
| 9 | Insights | headline **values** change only where gate 3 explains it; report every change with its cause |

Gates 7–9 need the app pointed at the shadow directory — set `TEMPO_DATA_DIR`, or copy
the shadow tree to a scratch corpus. Do not repoint the live corpus to run a test.

Reference numbers from 2026-09-04, for comparison:

```
insights over 1,986 datasets : 713 with a headline, 1,366 with sentences
tile sweep                    : 4,131 tiles / 1,452 datasets, 0 non-200
eval gate                     : 0 / 0 / 0 / 0
legacy parquets               : 94
canonical with NULL dims      : 1,108 of 3,769
```

Expected direction after the migration: NULL-carrying files **0**, legacy parquets **0**,
headline count **up** (recovered rows), eval gate **unchanged**.

---

## 7. When to stop and bring in Opus

Stop and ask rather than deciding, in any of these cases.

**Data safety**
- Anything would write to `data/corpus/parquet/` outside the shadow directory.
- Any step would delete or overwrite a file you cannot regenerate from the CSVs.
- You are about to run `12-parquet-to-sdmx.py` or `7-data-compactor.py` for any reason.

**Verification says something unexpected**
- Gate 7 moves at all. A chart-selector change means the meaning of the data shifted, not
  just its encoding.
- Gate 3 or 4 fails on a dataset that has **no** NULLs today — that is a new regression,
  not a recovery.
- A headline value changes and you cannot explain the cause in one sentence.
- The overall match rate is below 99.5%, or more than ~20 datasets exceed 10% unmatched.
  The measured baseline is 99.91%; a materially worse number means the normalisation is
  wrong, not that the data is bad.

**Design decisions this spec does not settle**
- CSV column order does not match `dimensions.dim_code` order for some matrix.
- A matrix has duplicate column names that `sdmx_column_map` cannot disambiguate.
- Split children need different handling from what §2.4 describes.
- You conclude the spec's approach is wrong. Say so with evidence — do not quietly
  substitute a different design.

**Scope**
- The change starts touching `12-split-datasets.py`, `13-dimension-structure.py`, view
  profiles, or the app beyond what Phase D lists.
- You want to delete `data/parquet-v2/` or the app's legacy adapter. Both are out of scope
  here and have their own prerequisites.

**How to escalate:** stop at a committed, working state. Write what you observed, the
numbers, and the two or three options you see. Do not pick one and proceed.

---

## 8. Out of scope

- Deleting `data/parquet-v2/` (blocked on `12-split-datasets.py`).
- Removing the app's legacy adapter (blocked on legacy count reaching 0).
- Exit-code discipline for `6-fetch-csv.py`, `12-split-datasets.py`,
  `13-dimension-structure.py`, `3-fetch-metas.py` — filed separately in `docs/BACKLOG.md`.
- The 47 matrices with no `sdmx_column_map` rows. This spec does not fix them; they will
  surface in `unmapped_labels` as whole-column misses. Report them, do not chase them.
