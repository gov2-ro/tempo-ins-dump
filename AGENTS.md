# AGENTS.md

Canonical guidance for coding agents (Codex, Claude Code, others) working in this
repository. `CLAUDE.md` imports this file — edit here, not there.

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo
root), reach for it before grep/find or reading files to understand or locate code:

- MCP: `codegraph_explore` returns relevant source and call paths. Name a file or
  symbol to read its current line-numbered source; load deferred tools by name.
- Shell: `codegraph explore "<symbol names or question>"` provides the same entry point.

If there is no `.codegraph/` directory, skip CodeGraph entirely; indexing is the
maintainer's decision.
<!-- CODEGRAPH_END -->

## Project Overview
Romanian National Institute of Statistics (INS) data scraper and explorer for
TEMPO Online. Two parts: a data pipeline (root Python scripts) that produces a
DuckDB metadata DB + one SDMX parquet per dataset, and a FastAPI + DuckDB web app
(`app/`) that serves it. Live: https://ins.gov2.ro

**Start here for current state:** [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md)
(how things actually work today, dated inventory) and
[docs/fixes/README.md](docs/fixes/README.md) (FIX-01…FIX-08 remediation packages
from the 2026-10-03 audit — specs, not completed work).

Don't hard-code corpus counts (files, tables, profiles) in docs — they rot within
weeks. Query them: `scripts/audit-corpus.py`, the dev MCP's `tempo_pipeline_status`,
or `information_schema` in `data/corpus/metadata.duckdb`.

## Data Pipeline

Script numbers are **historical filenames, not run order**. They stay as-is
because `update-pipeline.py`, the dev MCP, docs and history reference them.
Full rebuild order:

| Phase | Scripts, in order | Writes |
|---|---|---|
| A. Fetch | `1-fetch-context` → `2-fetch-matrices` → `3-fetch-metas` → `6-fetch-csv`; `4-build-meta-index` | `data/1-indexes/`, `data/2-metas/`, `data/4-datasets/` (per lang) |
| B. Metadata DB | `8-setup-duckdb-schema` (new scratch DB only) → `10-import-metadata` → `10-classify-dimensions` → `11-build-sdmx-codes`; then `scripts/build-i18n-dictionary.py` | `matrices`, `dimensions`, `dimension_options`, `dimension_options_parsed`, `matrix_profiles`, `sdmx_codes`, `sdmx_column_map`, `labels_i18n` |
| C. Convert | `9-csv-to-parquet` (**needs B's mappings**) → `12-split-datasets` | `data/corpus/parquet/`, `dataset_splits` |
| D. Profile | `13-dimension-structure`, `11-coverage-profiler`, `scripts/profile-values.py`, `detect_trends.py` → `generate_view_profiles.py` → `scripts/build-search-index.py` | `dimension_structure`, `dataset_coverage`, `dataset_value_profiles`, `dataset_trends`, `data/corpus/view-profiles/`, `data/corpus/search.duckdb` |
| E. Stage | `scripts/prepare-deploy-data.sh` | `deploy-data/` |

- **Legacy, not on the current path:** `5-varstats-db.py` (SQLite),
  `7-data-compactor.py` (label → ID compaction), `10-sdmx-export.py` (SDMX-CSV).
- **Deprecated — never run against the corpus:** `12-parquet-to-sdmx.py` (read a
  dead, lossy `parquet-v2/` snapshot; stage 9 has written SDMX directly since 2026-09-05).
- Stage 9 never writes NULL. A matrix with no `sdmx_column_map` rows keeps its
  original `*_nom_id`/`value` column shape; it canonicalizes once stage 11 covers it.
- `12-split-datasets.py` still falls back to `data/parquet-v2/` for v2-sourced splits.
- **Language:** only fetch scripts (1–7) take `--lang ro|en`; `update-pipeline.py`
  rejects `--lang en`/`TEMPO_LANG=en` (exit 2) until an enrichment-only mode exists.
  Processing scripts read `TEMPO_LANG` (via `duckdb_config.py`) for *inputs* but
  write the same canonical outputs. Neither `--lang en`, `TEMPO_LANG` nor
  `TEMPO_DATA_DIR` isolates pipeline writes — use a copied checkout for experiments.
- Most processing scripts accept `--matrix CODE`; flags differ, check `--help`.

**Orchestrator** `update-pipeline.py`: incremental runs from the INS news feed
(`get-news.py` → `data/insse_news.csv`). Per matrix: meta → CSV → stage 9 → split →
dim structure → view profile; then meta index + import + date sync. It does **not**
re-run phase B mappings or all of phase D (FIX-03 phase 2). Outcomes and the retry
set live in `data/logs/update-pipeline-state.json`; a required failure exits 1 and
freezes the watermark. Child scripts 3/6/12/13 exit nonzero on handled errors
(`6-fetch-csv` exit 3 = empty dataset); 1/2/4 still always exit 0.
Read-only corpus audit: `python scripts/audit-corpus.py --data-dir data`.

**Shared pipeline modules:** `duckdb_config.py` (paths, `TEMPO_LANG`),
`sdmx_labels.py` (`norm_label`/`parse_time_period`, shared by stages 9 and 11 so
their label matching agrees), `split_rules.py` (split-rule engine for stage 12).

Other root scripts: `generate_sdmx_yaml.py`, `build-geo-regions.py`,
`build-static-site.py`, `duckdb-browser.py` (Flask DB/parquet explorer, :5000),
`test_chart_selector.py` (a report, not a test). Helpers live in `scripts/`
(audit, eval baselines, search index, canonicalize, normalize); one-offs in
`scripts/utils/`. Details in [readme.md](readme.md).

## FastAPI Application (`app/`)

`main.py` mounts routers, `/view-profiles`, and `static/` at `/`. `config.py`
reads env: `TEMPO_DATA_DIR`, `TEMPO_MAX_ROWS` (50,000), `TEMPO_DEBUG`,
`TEMPO_ASK_ENABLED` (off by default) and other `TEMPO_ASK_*`/`TEMPO_LLM_*`.

- **Routers:** `datasets` (catalog/search/detail), `dataset_data` (data, insights,
  CSV/XLSX download), `categories`, `sdmx` (SDMX 2.1 data/datastructure/dataflow),
  `places`, `ask` (LLM Q&A).
- **Services:** `dataset_search` + `dataset_meta` (shared by routes, dev MCP and
  Ask agent), `query_builder`, `chart_selector` (+ `chart_selector_eval`),
  `dashboard_composer` (tile composition), `insights` (KPIs, sentences),
  `headlines` (+ `headline_config.json`), `dimension_structure`,
  `place_service`, `agent` + `llm_client`, `agent_eval`.
- **Pages** (`static/`):
  - `dataset-v2.html` + `js/dashboard-v2.js` — main dataset page
  - `index.html` + `js/explore-app.js` — v1 explorer: home, catalog, legacy
    dataset view (`/?code=`). Still served and maintained
  - `places.html`/`place.html` + `places-page.js`/`place-page.js` (KPI config
    in `static/data/place_kpi_config.json`), `compare.html` + `compare.js`,
    `ask.html` + `ask.js`, `dimensions-explorer.html` + `dims-explorer.js`
  - `js/site-chrome.js` — shared topbar for standalone pages. `chart-factory.js`
    dispatches to `chart-geo.js`, `chart-demographic.js`, `chart-new-types.js`
  - `static/geo/` — county/region/macroregion GeoJSON (ASCII county names)
- `_obsolete/` folders are archived. Don't edit or import from them.

## Dev MCP Server (`tools/tempo-dev-mcp/`)
Introspection tools: dataset info/sample/query, chart signatures, catalog stats,
routes, in-process endpoint calls, lineage, pipeline status, view-profile audit,
chart-selector and search evals. Tool reference: `tools/tempo-dev-mcp/README.md`.
It's registered in `.mcp.json`, which is **gitignored** (it holds absolute paths),
so a fresh clone has to add it.

## Commands

```bash
source ~/devbox/envs/240826/bin/activate          # always
uvicorn app.main:app --reload --port 8080          # app → http://localhost:8080
python -m pytest tests -q                          # tests; `corpus`-marked ones skip without data/
pip install -r requirements-dev.txt                # runtime + pytest/httpx (pipeline: requirements-pipeline.txt)
python 9-csv-to-parquet.py --matrix ACC101B        # single-matrix pipeline run
python 12-split-datasets.py --matrix ACC101B --dry-run
python update-pipeline.py --matrix ACC101B --dry-run
bash scripts/prepare-deploy-data.sh                # stage deploy data
```

## Verification before committing
- `python -m pytest tests -q` must pass. Add numerical tests on small temporary
  DuckDB/parquet fixtures. An HTTP 200 or a rendered chart doesn't prove a total is right.
- Chart/search changes: run the chart-selector and search evals (dev MCP
  `tempo_eval_chart_selector` / `tempo_eval_agent`). Explain expected diffs before
  rebuilding baselines (`scripts/build_*_baseline.py`, output in `data/eval/`).
- Frontend: smoke the affected pages (v1, v2, place, Ask) in a browser — console
  and network tab. `npx playwright` is available; see `scripts/dbv2-screenshot.mjs`.

## Gotchas
- **DuckDB write lock:** one writer at a time. Stop the dev server before running
  pipeline scripts. Parallel jobs that need to write should each use a separate
  `.duckdb` file and merge afterwards.
- **DuckDB concurrency:** `get_conn()` returns `_conn.cursor()`, not `_conn` —
  parallel requests need separate cursors.
- **Dimension levels:** a dim's options may tile the same domain more than once
  (POP107D's AGE has 85 single years AND 17 five-year bands). Never SUM or chart
  such a dim whole — restrict it to one level via `dimension_structure`. Accessors
  return empty when nothing was *verified*. That fallback is **unsafe** for
  overlapping totals (POP107A): don't assume unprofiled means additive (FIX-02).
- **Label-encoded hierarchies:** INS encodes trees with leading-space indentation
  and "- total" suffixes, so summing all options double-counts.
- **Legacy-shaped parquets** (`*_nom_id` columns, label-string values):
  `dataset_data.py` remaps SDMX ↔ legacy names in both directions.
- **Row caps:** `MAX_DATA_ROWS` also caps CSV/XLSX/SDMX exports without proper
  disclosure. Don't call them complete exports (FIX-04).
- Choropleth queries need `limit=50000` (all years × counties).
- `dataset_relationships` predates splitting, so split children have no rows.
  `get_related` falls back to parent + siblings.
- `is_composition` is a runtime-only parquet probe, so it scores `None` in the chart eval.
- `do` is a reserved word in DuckDB SQL — alias `dimension_options` as `dopt`.
- Initialize the schema only for a new scratch DB. Never force-recreate
  `data/corpus/metadata.duckdb`.

## Data layout
```
data/
  1-indexes/{lang}/   2-metas/{lang}/   4-datasets/{lang}/     source catalogs, metadata, CSVs
  4-datasets-slim-samples/{50,100}/                            small samples for LLM analysis
  parquet-v2/ro/      legacy snapshot (stage-12 fallback only)
  meta/               reference data (judet CSVs, SIRUTA)
  logs/               pipeline logs, last-pipeline-run.txt
  eval/               chart/search eval baselines (tracked)
  corpus/             ← what the app reads
    metadata.duckdb   inspect the actual schema; it is authoritative
    search.duckdb     bilingual FTS sidecar
    parquet/          one SDMX parquet per dataset + split children (includes leftovers)
    view-profiles/    per-dataset JSON
  _obsolete/          archived intermediates
```
Most of `data/` is gitignored, except `data/eval/`.

## Deployment
Fly.io app `tempo-ins-explorer` (shared-cpu-1x, 512MB, Amsterdam, 1 worker):
`Dockerfile` + `fly.toml` bake a `deploy-data/` snapshot from
`scripts/prepare-deploy-data.sh` (atomic staging incl. `search.duckdb` +
`MANIFEST.json`, previous kept as `deploy-data.prev`). Gate with
`python scripts/release-check.py [--docker] [--rollback]`; it deploys only with an
explicit `--deploy`. The image won't build without a staged manifest and search
index. Only `.github/workflows/ci.yml` is tracked (synthetic tests).
Oracle/HF Spaces templates live in `scripts/deploy/`. Validated release gates: FIX-05.

## Audit remediation handoff
- Start at [docs/fixes/README.md](docs/fixes/README.md). Implement one scoped package at a time.
- Specs describe intended behavior, not completed fixes. Update status only after acceptance checks.
- Use synthetic/copy-based fixtures for numerical and pipeline tests. Don't mutate the live corpus as a test.
- Preserve the current generation, and provide explicit migration/rollback evidence for data repairs.
- Commit code/docs only within the requested scope. Implementing a fix doesn't mean deploying it or repairing the corpus.

## Working Style
- Act as a senior full-stack developer; suggest improvements/optimizations proactively
- Keep answers concise; challenge assumptions rather than just agreeing
- If a request is ambiguous, ask follow-up questions before working
- For large files (>300 lines) or complex changes, plan BEFORE editing; break refactors into independently functional chunks
- Less code = less debt — make minimal, targeted changes; do not add files unless necessary
- For complex changes, add a debug-mode flag with verbose logging
- If unsure, say so instead of guessing

## Notes
- **Backlog**: When detecting things to address later, add a `- [ ]` entry with title + enough context to `docs/BACKLOG.md`
- **Activity log**: After meaningful work, add an entry at the top of `docs/activity-history.md` under `## YYYY-MM-DD — Short Title` (what + why + non-obvious decisions)
- **Slim samples**: When sampling datasets, prefer `data/4-datasets-slim-samples/50` (or `/100`) for smaller records and lower context use
- **Repo**: https://github.com/gov2-ro/tempo-ins-dump/
