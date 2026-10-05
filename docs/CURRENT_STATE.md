# Current architecture and operating reference

Reviewed 2026-10-03. This file describes existing behavior, not the intended fixes.
[Remediation specs](fixes/README.md) define future changes; [BACKLOG.md](BACKLOG.md)
tracks completion and [activity-history.md](activity-history.md) preserves evidence.
Older application/schema/migration documents are historical unless marked current.

## Application and source of truth

FastAPI entry: `app/main.py`; DuckDB metadata plus file-per-dataset parquet; vanilla
JS/ECharts. v1 is `app/static/index.html` with `js/explore-app.js`; v2 is
`dataset-v2.html` with `js/dashboard-v2.js`. Both are served and maintained. Places
use `routers/places.py`, `services/place_service.py`, `place-page.js` and a curated
KPI config. `dataset-page.js`/`dataset-page-v2.js` are archived under _obsolete.

Shared services implement search, metadata/schema resolution, chart selection,
dashboard composition, dimension structure, insights and agent tools. Curated
home/place KPI queries still diverge from shared statistical rules. Verified
structure is not complete; absence currently permits unsafe fallback aggregation.
See FIX-02 before treating a derived number as a verified total.

## Actual storage paths

| Artifact | Current path | Purpose |
|---|---|---|
| Indexes | `data/1-indexes/{ro,en}/` | contexts/matrix catalogs |
| Source metadata | `data/2-metas/{ro,en}/` | TEMPO metadata JSON |
| Source CSVs | `data/4-datasets/{ro,en}/` | original labels and values |
| Main DB | `data/corpus/metadata.duckdb` | metadata, mappings, profiling/splits |
| Canonical-format files | `data/corpus/parquet/` | OBS_VALUE and SDMX concept columns |
| View profiles | `data/corpus/view-profiles/` | per-dataset JSON |
| Search index | `data/corpus/search.duckdb` | bilingual FTS sidecar |
| Historical intermediates | `data/parquet-v2/{ro,en}/`, `data/_obsolete/` | legacy fallback/history |
| Pipeline status | `data/logs/` | logs and last-pipeline-run.txt |
| Eval baselines | `data/eval/` | tracked chart/search regression fixtures |
| Deployment staging | `deploy-data/corpus/` | files Docker bakes into /app/data |

App paths honor TEMPO_DATA_DIR (`app/config.py`). Pipeline paths use
`duckdb_config.py`, whose DATA_DIR is repository-relative; TEMPO_DATA_DIR is **not**
a general pipeline sandbox. TEMPO_LANG changes pipeline input paths but shares
the canonical output directory. Use copied checkouts/configured shadow outputs
for pipeline repair; do not assume app environment overrides isolate writers.

The actual DB schema is authoritative: inspect DESCRIBE/information_schema.
`matrices` has one record per matrix code with bilingual name/definition fields;
the current core design is not a per-language composite-key corpus. Dimension
translations use labels/code mappings and optional EN metadata, not a dimensions
lang column. See [BILINGUAL.md](BILINGUAL.md) for remaining limitations.

## Dependency order, not numeric order

Fetch context/catalog/metadata/CSV as needed. Initialize schema only for a new
scratch corpus; do not force-recreate an existing database. Import metadata and
dimension options, classify dimensions, build SDMX mappings, then run stage 9
to write canonical parquet. Split/register children, compute structure/coverage/
value/trend profiles, generate view profiles and rebuild the search index.
Exact scopes and available flags differ by script; inspect --help/source.

The numbers are historical filenames. Stage **9 depends on stage 11 mappings**.
The compactor and `10-sdmx-export.py` are legacy/optional paths, not prerequisites
for the current raw-CSV-to-SDMX-parquet conversion. `12-parquet-to-sdmx.py` is
deprecated; do not run it against the corpus. September's migration was executed
and the remaining no-map cases were backfilled by September 8.

`update-pipeline.py` (FIX-03 phases 1 and 2a) runs per matrix: meta → CSV →
targeted import (`10-import-metadata --matrix`, which reconciles existing matrices
against `2-metas`, so new options and periods are imported) → targeted classify
and code maps (`--matrix`; canonical dimensions keep their `sdmx_column_map` rows)
→ stage 9 → stage 12 children as a set → stats import → stage 13 and view
profiles for parent and children → validate → checkpoint. New dimension ids are
MAX+1 (the DB sequences lag the data). Global-only steps (coverage, trends, value
profiles, search index) are recorded under `stale` and run with
`--global-profiles`. It records per-matrix/per-stage outcomes in
`data/logs/update-pipeline-state.json` (`--state-file`). Required stages are
metadata, CSV, import/classify/maps, conversion, registered split and validation.
A required failure exits 1, puts the matrix in a persisted retry set (merged into
the next run) and freezes the watermark. Optional profiling failures exit 0 but
are listed (`--strict` makes them fatal). The watermark is the newest feed date of
a fully successful run (inclusive), never today's date, and is not moved by
`--matrix` or partial runs. `last-pipeline-run.txt` mirrors it. `--lang en` and
`TEMPO_LANG=en` are rejected (exit 2) because canonical outputs are shared;
children always get `TEMPO_LANG=ro`. Stages 3, 6 (exit 3 = empty dataset, not
retried), 12 and 13 exit nonzero on handled errors; 1, 2 and 4 still always exit 0.
None of this has been run against the real DB yet: back up `metadata.duckdb` and
the parquet dir, stop the dev server, and dry-run one matrix first.

`scripts/audit-corpus.py --data-dir DIR [--json-out F] [--hashes]` is a
deterministic read-only audit: file categories (served canonical, noncanonical
parent, registered split, leftover, invalid), NULL dims, TIME_PERIOD validity,
grain uniqueness, mapping/profile coverage and registration.

Generation and repair tooling (FIX-03 phase 2b; nothing applied to the corpus):
`scripts/build-generation-manifest.py --out F` writes a deterministic manifest
(id = hash of DB, parquet digest, view-profile digest and search index; per-file
sha256/rows/category; table row counts; audit violations). `prepare-deploy-data.sh`
stages `corpus/generation-manifest.json` and `release-check.py` fails when it is
missing or inconsistent with the staged files (`--allow-missing-generation` to
bypass, `--require-clean-audit` to make audit violations fatal).
`scripts/repair-corpus.py` is a dry-run planner (quarantine, metadata-only,
time-shift and grain reports); `--apply --target-dir` works only on a copy and
only quarantines. Stage 13 honours `TEMPO_STRUCTURE_DB` /
`TEMPO_STRUCTURE_PARQUET_DIR` for profiling a copy. Summary of the 2026-10-05 plan:
`reports/fix03c/repair-plan.md`.

## Local app and checks

Maintainer environment: `source ~/devbox/envs/240826/bin/activate`. Then:

```bash
uvicorn app.main:app --reload --port 8080
python -m pytest tests -q
```

Dependencies: `requirements.txt` (runtime, pinned), `requirements-pipeline.txt`,
`requirements-dev.txt` (adds pytest/httpx). Tests marked `corpus` need
`data/corpus/metadata.duckdb` (or `TEMPO_DATA_DIR`) and are skipped, not passed,
on a clean checkout. Tracked CI (`.github/workflows/ci.yml`) runs the synthetic
suite only. Root `test_chart_selector.py` is a reporting script, not a substitute
for numerical regression tests.

The repo-local dev MCP exposes metadata/sample/query/lineage/profile and chart/
search eval tools; registration is local and .mcp.json is ignored. Check available
tools in the session rather than assuming another checkout has the same setup.

## Data/API contract and known limitations

- Catalog and detail: `/api/datasets`, `/api/datasets/{code}`.
- Data/insights/download: `/api/datasets/{code}/data`, `/insights`, `/download`.
- Home summary: `/api/corpus/summary`; places: `/places`, `/place/{type}/{slug}`.
- SDMX: `/sdmx/2.1/data/INS,{flow}`, `/datastructure/INS/{flow}/1.0`,
  `/dataflow/INS/{flow}/1.0`. Omitting the data key avoids HTTP dot-path
  normalization in clients. FIX-01: all values and parquet paths are bound
  parameters on a request-owned cursor. `startPeriod`/`endPeriod` accept only
  `YYYY`, `YYYY-Qn`, `YYYY-MM` and compare as month spans (annual `endPeriod=2020`
  includes 2020-12); malformed/reversed → 400. DSD, data and keys share one code
  registry (`app/services/sdmx_registry.py`): code ID = stored value when it is a
  valid SDMX ID, else `<slug>_<sha1[:12]>`; codelists cover all metadata options
  plus values present in the data, no cutoff; TIME_PERIOD is a TimeDimension;
  XML is built with ElementTree. Canonical code keys preferred; legacy raw-value
  keys work when unambiguous, otherwise 400. Details: `docs/SDMX-API.md`.
- Request validation (`app/services/request_validation.py`): limits ≥1 (422);
  `filters` must be an object of known column → array of scalars and `group_by`
  an array of known columns, else 400 (unknown columns are rejected, not ignored);
  unknown datasets 404; query failures return `{"detail":"Query failed"}`.
- Charts use MAX_DATA_ROWS (50,000 by default) with grouping/time-window behavior.
  Exports are separate (FIX-04): `/api/datasets/{code}/download` returns every raw
  observation matching the validated filters. CSV streams in batches (UTF-8, no
  BOM, ordered by all dimensions; formula-like labels get a `'` prefix unless
  `safe=0`). XLSX is a write-only temp file, rejected with 413 above 1,048,575 data
  rows. SDMX data streams the full selection or returns 413 above
  `TEMPO_SDMX_MAX_OBS` (250,000). Headers: `X-Export-Matching-Rows`,
  `X-Export-Rows`, `X-Export-Complete`; `preflight=1` returns the counts as JSON
  and takes no slot. At most `TEMPO_EXPORT_MAX_CONCURRENT` (2) exports run at once,
  XLSX limited to 1; otherwise 503 with `Retry-After`. Local POP107A (749,428
  rows): CSV 3 s / ~290 MB peak RSS, XLSX 41 s / 317 MB, full SDMX 14 s / 229 MB.
  Not yet measured under a real 512 MB cap.
- Places (FIX-06): each KPI has a stable key, RO/EN labels, source, definition,
  unit kind, period, `stale` flag, method and an explicit `change` object
  (relative % for counts, percentage points for % rates, per-mille points for ‰).
  Series take the newest 30 periods and return them ascending; periods with
  missing groups or weights are dropped, not zero-filled. SOM103A is "registered
  unemployment" (old BIM label kept only as an alias), shown as a named
  unweighted-mean approximation. Birth/death rates are weighted by POP105A
  residence population (1 January proxy, so from 2012). Net wage is omitted.
- Dataset pages (FIX-07): v1/v2 fit 320–1440px without body overflow; the topbar
  collapses to icons at ≤600px (`.tb-compact`, dataset pages only). Pills carry
  `aria-pressed`, icon buttons localized `aria-label`s, global focus ring. Value
  axes use compact numbers with full values in tooltips; charts follow their
  container via a ResizeObserver; chart type names are translated
  (`chartTypeLabel`). Browser checks: `tests/browser/audit_layout.py` and
  `audit_interactions.py` (`--base URL`, need Python Playwright and a running app).
- Aggregation (FIX-02 phases 1–2): one decision, `aggregation_policy.decide()`,
  serves composed tiles, insight KPIs, curated headlines, grouped `/data` queries
  and the Ask agent. Additivity comes from `dataset_measure()` (unit type,
  indicator name/definition, verified `dimension_structure.additive`);
  `AVG_UNIT_TYPES` is gone. A total row is preferred; otherwise one verified
  disjoint partition is summed; rates/indices/averages are never summed or
  averaged into a total. Every KPI and headline card carries `provenance`
  (source_code, period, unit, filters, levels, method, verification,
  approximation, outcome, reason, comparison, dimensions); headline cards are
  declared as slice + method in `headline_config.json`.
  Grouped `/data` responses include `aggregation`; Total rows are pinned and
  verified levels applied (also to multi-level axes). A refused collapse returns
  **HTTP 200** with `unavailable: true`, no rows and a reason code (chosen so
  existing clients don't hit error paths); `approximate=1` allows a labelled
  unweighted mean. Raw rows, exports and valid explicit slices are unaffected.
  v1/v2 show a translated reason (`aggReasonText` in `utils.js`) where a total or
  tile is withheld and use server-aggregated slices instead of client sums.
  Ask: `query_dataset_data` returns status/aggregation/reason;
  `app/services/answer_check.py` withholds answers that state figures without a
  valid query, flags numbers absent from tool results, and notes unqualified
  approximations. Known gaps: axes with only metadata-detected overlap warn rather
  than refuse; grouping without a time filter still sums periods (warning only).

## Deployment today

Fly app `tempo-ins-explorer`, live https://ins.gov2.ro/, shared-cpu-1x/512MB,
Amsterdam, one uvicorn worker. Main DuckDB connection is read-only with a 400MB
limit; get_conn returns a cursor per request. Other services open independent
connections, so this is not a global process memory cap.

`bash scripts/prepare-deploy-data.sh` stages metadata, `search.duckdb`, parquets
and view profiles: it builds in a temp dir, rejects source changes mid-copy,
validates, then swaps into `deploy-data/`, keeping the previous staging as
`deploy-data.prev`. It writes `MANIFEST.json` (sizes, sha256, source build times,
latest observation date; the generation block is a placeholder until FIX-03).
`scripts/release-check.py` validates manifest/hashes, FTS loading, index coverage
of canonical matrices, parquet coverage and pytest; `--docker` adds image build +
smoke, `--rollback` swaps staging back, and `--deploy` runs `fly deploy` only when
explicitly passed. The Dockerfile installs the DuckDB `fts` extension and refuses
to build without a staged manifest and search index. `GET /api/health` reports
FTS mode (`degraded` = name-matching fallback, also logged at ERROR). Search uses
per-request FTS cursors and `total` counts the full match set. The Docker smoke
has not been run yet. Oracle/HF templates live under `scripts/deploy/`.

Ask is disabled by default (`TEMPO_ASK_ENABLED`) and accepts BYOK. FIX-08: history
is validated before any provider call (user/assistant text only, 20 turns, 8k
chars per turn, 40k total). Providers/models come from an allowlist
(`ask-models.json` for BYOK; only `TEMPO_LLM_PROVIDER:TEMPO_LLM_MODEL` for
server-funded calls unless `TEMPO_ASK_SERVER_MODELS`). Independent budgets: 8 model
calls, 12 dispatched tools, 90 s; exhausting one returns a 200 partial result
with `stop_reason`. At most 2 concurrent Ask requests (else 503 + Retry-After).
Provider errors are stable and secret-free. Chat content logging is off by
default, including in `fly.toml`; `ASK_METRICS` lines carry no content. BYOK keys
stay per-tab unless the user opts in to "remember"; Clear wipes both scopes; keys
transit the server. `GET /api/ask/config` drives the disclosure banner.

## Dated inventory, not permanent constants

Local 2026-10-03: 4,274 parquets; 4,102 matrices; 2,183 split-table rows; 3,679
view profiles. 179 files lack metadata, 7 matrix rows lack files, 596 files lack
view profiles, 1 profile lacks a file. matrix_profiles covers 1,986 matrices and
dimension_structure covers 1,510 distinct matrices. All scanned files are readable
and have OBS_VALUE; canonical formatting does not establish valid grain or time.

The scan found 57 files with NULL dimensions (57,491 affected rows), and 162 with
>20% of distinct TIME_PERIOD values outside the supported annual/quarterly/monthly
pattern. Directory counts include leftovers/noncanonical parents. Classify before
publication or deletion. Live catalog count was 3,368; local file/metadata/canonical
counts measure different sets and should not be conflated.

Local 2026-10-05 audit (`scripts/audit-corpus.py`, read-only): served_canonical
1,178; noncanonical_parent 734; registered_split 2,183; leftover 164; invalid 15
(zero-row, unregistered). The 7 metadata-only matrices: ECC103B, EXP101F, EXP102F,
LMV101E, LMV102E, TNZ1211, TPG1346. All 57 NULL-dimension files are leftovers.
Of the 162 files with >20% invalid TIME_PERIOD, 149 are served. 241 files have
duplicate keys with conflicting values (160 served); 225 `matrices.row_count`
values differ from actual rows. The release check found `search.duckdb` covering
1,225 of 3,368 canonical matrices (built April 2026).

FIX-02 corpus sweep (2026-10-05, 3,368 canonical datasets): datasets with a
headline KPI went from 2,551 to 1,602 (963 lost, 14 gained); 91 lose all composed
tiles. Reasons: unverified_structure 885, overlapping_levels 58, mixed_units 27,
missing_weights 22, label_hierarchy 17. Most losses lack `dimension_structure`
rows (mainly split children); FIX-03 structure backfill should restore most.

Repair plan 2026-10-05 (dry run): the 7 metadata-only matrices are 2 empty at
source (EXP101F, EXP102F) and 5 never fetched (ECC103B, LMV101E, LMV102E, TNZ1211,
TPG1346, added after the last CSV batch). The 149 served time-invalid files all
have TIME_PERIOD 100% invalid and TIME_PERIOD_2 valid (110 constant indicator
titles, 24 hours-worked bands, 4 base-year labels, 9 other, 2 month names). Of
160 conflicting-grain files, 95 are county splits that dropped locality (no
locality disjointness is verified, so none may be summed), 32 source label
collisions, 18 inherited, 15 dropped another dimension. Backfilling
`dimension_structure` on a copy for 1,926 unprofiled served matrices restores 749
latest KPIs (1,525 → 2,274 of 3,368), all on split children; 584 of those rest only
on `profile_flat` verification and need an independent additivity check.

Tests on 2026-10-03: 38 passing, 3 warnings. Chart eval: 1,986 baseline cases unchanged, 2,116
added. Search: 17 top sets unchanged, 2 order changes. These results establish
regression stability within their scope, not accuracy of published totals.
