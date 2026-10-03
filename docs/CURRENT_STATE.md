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

`update-pipeline.py` currently does per-matrix metadata → CSV → stage 9 → split →
structure → view profile, then index/import/date synchronization. It does **not**
implement the complete dependency order above, and failure/checkpoint guarantees
remain unresolved. Its --lang flag does not propagate uniformly to subprocess
TEMPO_LANG inputs. See FIX-03; do not advertise a safe bilingual refresh procedure.

## Local app and checks

Maintainer environment: `source ~/devbox/envs/240826/bin/activate`. Then:

```bash
uvicorn app.main:app --reload --port 8080
python -m pytest tests -q
```

requirements.txt covers app dependencies, not a complete reproducible pipeline/
test setup. Existing place tests read the local corpus; clean-checkout synthetic
CI and dependency sets are specified in FIX-05. Root `test_chart_selector.py` is a
reporting script, not a substitute for numerical regression tests.

The repo-local dev MCP exposes metadata/sample/query/lineage/profile and chart/
search eval tools; registration is local and .mcp.json is ignored. Check available
tools in the session rather than assuming another checkout has the same setup.

## Data/API contract and known limitations

- Catalog and detail: `/api/datasets`, `/api/datasets/{code}`.
- Data/insights/download: `/api/datasets/{code}/data`, `/insights`, `/download`.
- Home summary: `/api/corpus/summary`; places: `/places`, `/place/{type}/{slug}`.
- SDMX: `/sdmx/2.1/data/INS,{flow}`, `/datastructure/INS/{flow}/1.0`,
  `/dataflow/INS/{flow}/1.0`. Omitting the data key avoids HTTP dot-path
  normalization in clients. Contract and security fixes are pending FIX-01.
- Charts use MAX_DATA_ROWS (50,000 by default) with grouping/time-window behavior.
  Current CSV/XLSX and SDMX also cap observations without adequate disclosure.
  They must not be described as complete exports until FIX-04 lands.
- Aggregation safety, population overlap, home electricity/CPI cards and place
  rates remain unresolved. See FIX-02/FIX-06, not historical “fixed” chart claims.

## Deployment today

Fly app `tempo-ins-explorer`, live https://ins.gov2.ro/, shared-cpu-1x/512MB,
Amsterdam, one uvicorn worker. Main DuckDB connection is read-only with a 400MB
limit; get_conn returns a cursor per request. Other services open independent
connections, so this is not a global process memory cap.

`bash scripts/prepare-deploy-data.sh` copies metadata/parquets/profiles into
deploy-data and rebuilds the tarball; Docker copies this snapshot. Preparation
currently removes/recreates old staging and omits search.duckdb. It is not wired
automatically into Fly build. The locally present workflow is not tracked, so a
clean checkout has no established CI/release gate. Oracle/HF templates live under
`scripts/deploy/`; their historical availability does not prove active deployments.
FIX-05 defines validated staging, image checks and rollback before deployment.

Ask is disabled by default in app config and can accept BYOK. Fly config enables
chat content logging. Key persistence and request/tool budgets need FIX-08.
No keys or paid model calls are needed for the prescribed mocked tests.

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

Tests: 38 passing, 3 warnings. Chart eval: 1,986 baseline cases unchanged, 2,116
added. Search: 17 top sets unchanged, 2 order changes. These results establish
regression stability within their scope, not accuracy of published totals.
