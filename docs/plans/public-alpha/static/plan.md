# Fully static site on shared hosting, with a verified browser port of the query rules

## Context

The alpha runs as FastAPI + DuckDB on Fly. Validating it needs Docker, and the server peaked
at 1.2 GB RSS locally. The owner wants deployment on shared hosting (Apache) and full
exploration (any filter on any dataset). Measurements show the data is small enough for the
browser:
- 3,346 of 3,376 served datasets total 71.5 MB (median 3.4 KB, p90 44 KB);
- one family (POP107D/108D, domicile × locality × single age, 187 MB) splits into 0.4–0.9 MB
  files per county.

Decision (owner): **fully static**.
- The build pre-transforms the data and precomputes everything bounded with the existing
  Python services.
- The browser loads only the dataset (or slice) being viewed, then filters and aggregates it
  locally.
- The aggregation safety rules (PA-01) are ported to JavaScript and **proven equal to the
  Python version** by a generated parity suite over every served dataset. Python stays the
  specification and the build tool; the port must match it.

Accepted losses, documented:
- public REST/SDMX query endpoints: replaced by static per-dataset files (raw parquet +
  JSON), with SDMX structure files only;
- Ask: stays off;
- server-side logs and rate limits;
- full-text ranking: DuckDB FTS is replaced by a prebuilt client index, re-judged with the
  PA-02 judgments.

The FastAPI app stays for development and as the oracle for the build and tests. Fly
becomes optional.

The old static scaffold (root `build-static-site.py`, `docs/misc-ideas/static-site/`) is
stale and is not reused.

## Architecture

**Build (`scripts/build-static.py`, Python, read-only on the generation)** writes `_static/`:

1. **Recorded responses for every bounded endpoint.** These are recorded via
   `fastapi.testclient.TestClient(app)`, so there is no logic duplication:
   - catalog, categories, corpus summary;
   - per dataset × ro/en: `/api/datasets/{code}`, `/insights`, `/related`;
   - places and baselines;
   - population reference;
   - `/recipes/tourism_intensity?year=Y` and the evidence ZIP for every year;
   - each composed tile's default `/data` (warm start; must equal the engine's output).

   Each response goes to a deterministic key path (path + sorted params).
2. **Data:** `data/{code}.json` holds dictionary-encoded columnar rows (`dims`, `dicts`,
   `codes`, `values`), with a pre-gzipped `.json.gz` alongside. Datasets over a row
   threshold (about 200k) are also written as partitions by `REF_AREA` and by
   `TIME_PERIOD`, plus `data/{code}.index.json` listing the partitions. The raw parquet is
   copied too, for downloads and machines.
3. **Policy context per dataset:** `policy/{code}.json` serializes exactly what
   `decide_grouped` uses:
   - `get_aggregation_context()`: dimensions with parsed options, actual values,
     `dimension_structure` levels, measure, unit type;
   - the `kpi_total_checks` row for `source_total_gate`;
   - the file grain status from the generation manifest;
   - row count, plus the MAX/windowing constants.
4. **Search:**
   - `search/concepts.json`, a copy of `app/data/concepts.json`;
   - `search/places.json`;
   - `search/facts.json`, the `dataset_facts` for every concept variant and recipe;
   - `search/index.json`, a compact per-dataset document (names RO/EN, tags,
     definition snippet, family/parent, time range) for a client-side BM25.
5. **Pages:**
   - pre-rendered `/dataset/{code}/index.html` via `pages.render_dataset_page`;
   - `place/{type}/{slug}/index.html`;
   - `sitemap.xml` and `robots.txt` (`--base-url`);
   - `app/static/` assets, `view-profiles/`, `geo/`;
   - generated `config.js` (`mode: "static"`);
   - `build.json` (generation, commit);
   - `static-manifest.json` with the sha256 of every file.

**Browser engine (`app/static/js/engine/`, ES modules, also runnable in Node):**
- `policy.js`: port of `aggregation_policy.decide`/`combine`/`compute_change`, the
  `dimension_structure` accessors, and `dataset_meta.decide_grouped` / `_effective` /
  `source_total_gate`.
- `query.js`: port of `data_query.run_query` semantics:
  - validation messages;
  - decision → effective filters;
  - grain gate (the slice duplicate-key check runs on the loaded rows);
  - filter / group / SUM / AVG;
  - deterministic ordering;
  - limit, truncation, time window, `partial_period_dropped`;
  - the `selection.missing_values` and `contract` / `generation` / `quality` fields.

  It returns the same JSON shape as `/data`.
- `data.js`: loads the dataset file, or only the partitions the filters need (by county or
  year; all partitions only for whole-country, all-years queries on the big family). It
  caches per generation.
- `search.js`: port of `concept_search` (`parse_query`, `match_concepts`, cards from
  precomputed facts) plus client BM25 for family results.
- `export.js`: CSV, built from the complete loaded rows, with the same columns and
  formula-safety as `export.make_row_transform`. Also evidence ZIPs in schema
  `tempo-evidence/1`, using a small store-only ZIP writer and SubtleCrypto sha256. XLSX via
  lazy-loaded SheetJS (optional).
- `options.js`: searchable, paginated values from the loaded data.

**Frontend wiring.** `API` in `app/static/js/api.js` reads `config.js`:
- `mode "server"` (default, dev/Fly) is unchanged;
- `mode "static"`:
  - bounded `API.fetch` paths go to the recorded files;
  - `getDatasetData` goes to `engine.query`;
  - `search`, `getOptions`, `download` and evidence go to engine modules;
  - the raw `fetch('/api/places…')` calls in `place-page.js` / `places-page.js` go
    through `API.fetch`;
  - `/api/health` is replaced by `build.json`;
  - recipe area subsets are filtered client-side from the recorded full-year result.

**Hosting:**
- `deploy/static/.htaccess`:
  - pretty URLs;
  - the `/dataset.html` redirect;
  - `AddEncoding gzip` for `.json.gz`;
  - mime types;
  - caching rules.
- Versioned `releases/<gen12>-<commit>/` directories with a `current` symlink;
  `scripts/deploy-static.sh` (rsync then symlink swap) is dry-run by default. Uploading
  needs explicit authorization.

## Parity harness (the guarantee)

- `scripts/gen-parity-cases.py` runs `run_query` via TestClient for every served dataset:
  - all composed tile queries;
  - the headline series;
  - seeded fuzz: random `group_by` subsets, single, multi, total, level-member and invalid
    filter values, unknown columns, `approximate` on/off.

  It writes `{request, response}` cases. `concept_search` cases come from the PA-02
  judgments plus fuzzed phrases.
- `tools/static-engine/parity.mjs` (Node 22) runs the engine on the same cases. It
  requires:
  - identical errors and decisions (outcome, reason, blocking dimension, method, effective
    filters, levels);
  - identical columns, row keys and order, and flags;
  - values within 1e-9 relative (summation order).
- `tests/test_static_parity.py` runs it on the synthetic corpora (fix01/fix02b/grain
  fixtures, committed cases; this runs in CI). The corpus-marked run covers the full copy.
  It skips if Node is missing.

## Increments, each tested and committed

1. **S1, spike plus checkpoint.**
   - Build data, policy and recorded files for 4 datasets: POP105A_judete_grupe,
     FOM106F, SOM103A_judete and the POP107D family (partitioned).
   - Port `policy.js` + `query.js`; parity on those 4 plus all synthetic fixtures.
   - Measure file sizes, phone load and query time.
   - **Stop and report to the owner (go/no-go)** before the rest.
2. **S2:** full build for every served dataset; parity across the whole corpus; size and
   file-count report against shared-host limits.
3. **S3:**
   - frontend `mode: "static"` wiring;
   - `search.js` (judgments must still pass, family ranking re-checked against the 17
     eval questions, with differences explained);
   - `options.js`;
   - client CSV / evidence (the recipe `recompute.py` round trip still passes from the
     recorded bundles).
4. **S4:**
   - pages, `.htaccess` and the release layout;
   - `release-check.py --static`: manifest hashes, generation equality, every dataset
     has data/policy/meta/page, a parity sample;
   - `docs/DEPLOY-STATIC.md`, `llms.txt` (static files as the machine API), `AGENTS.md`;
   - the PA-04 release record updated.

## Critical files

- **New:**
  - `scripts/build-static.py`, `scripts/gen-parity-cases.py`
  - `app/static/js/engine/{policy,query,data,search,export,options}.js`
  - `app/static/js/config.js` (default server mode)
  - `tools/static-engine/parity.mjs`
  - `deploy/static/.htaccess`, `scripts/deploy-static.sh`
  - `docs/DEPLOY-STATIC.md`
  - `tests/test_static_build.py`, `tests/test_static_parity.py`, `tests/test_static_browser.py`
- **Modified:**
  - `app/static/js/api.js`
  - `place-page.js`, `places-page.js`, `compare.js`, `utils.js` (feedback generation from
    `build.json`)
  - `scripts/release-check.py`
- **Reused as specification and recorder (unchanged):**
  - `app/services/aggregation_policy.py`, `dimension_structure.py`
  - `dataset_meta.get_aggregation_context` / `decide_grouped` / `source_total_gate`
  - `data_query.run_query`
  - `grain_guard`, `concept_search`, `recipes`, `evidence`
  - `pages.render_dataset_page`
  - `export.make_row_transform`
- **Removed:** stale root `build-static-site.py`.

## Verification

- `python -m pytest tests -q`, including parity on the synthetic corpora;
  `-m corpus` parity over the copy (every served dataset, zero mismatches).
- Build `_static/` from the staged copy and serve it with `python -m http.server` (no
  Python app running). Run the PA-04 browser smoke (17 pages × RO/EN × 1280/390/320) and
  assert that no request goes to `/api/`.
- Q1 Cluj = 697,030 (2025); Q4 recipe equals the PA-00 record; PA-02 judgments pass;
  evidence ZIPs verify and `recompute.py` succeeds.
- Phone check at 390 px on the largest family filtered to one county: download < 1 MB and
  query < 1 s on a desktop-throttled profile.
- `release-check.py --static` passes. Nothing is uploaded without explicit authorization.
