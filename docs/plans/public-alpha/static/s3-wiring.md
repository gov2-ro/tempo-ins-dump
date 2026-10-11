# Static S3: the pages on the static build (2026-10-11)

The same pages now run in two modes, chosen by `js/config.js`:
- **server:** the file as committed; every call goes to the FastAPI `/api`.
- **static:** `build-static.py` overwrites `config.js` with `{"mode": "static"}`.
  `API.fetch` then answers the same paths from the build's files through
  `js/engine/static-api.js`, loaded on first use. The pages do not know which
  mode they are in.

| Path | Static answer | Proven equal by |
|---|---|---|
| categories, corpus summary, category summaries, dimensions, population reference, places (+ profiles, KPI baselines), recipes list, dataset detail / insights / related (ro+en) | recorded once from the real app (`scripts/static_api.py`, TestClient) as `rec/…json.gz`; errors recorded with their status | the recorder (no logic copied) |
| `/datasets/{c}/data` | `engine/query.js` (run_query port) | `parity.mjs` (S1/S2) |
| `/datasets` (catalog, filters, sorts, free text) | `engine/search.js` over `rec/catalog.json.gz`; free text uses the FTS sidecar's BM25 index, exported exactly (stemmer none), sharded in 64 term files | `api-parity.mjs` |
| `/search` (concept search) | `engine/search.js`: port of parse_query, match_concepts, concept/recipe cards, family results | `api-parity.mjs` (PA-02 judgments + fuzz) |
| `/datasets/{c}/options` | `static-api.js` from the data tables, with period bounds in the policy | `api-parity.mjs` |
| `/datasets/{c}/download` CSV | written in the browser, byte-identical to the server (EN labels, formula safety, ordering) | `api-parity.mjs` (text or sha256) |
| XLSX | SheetJS 0.18.5 (cdnjs), loaded on demand | none (format only) |
| dataset evidence ZIP | `engine/evidence.js` (store-only ZIP, SHA-256 manifest) | `api-parity.mjs` (result, observations, README; manifest hashes) |
| `/recipes/{id}?year&areas` | recorded per year × language, with the area subset applied client-side exactly as `run()` does | `api-parity.mjs` |
| recipe evidence ZIP | recorded per year × language (full year; an area subset is not applied) | the recorder |
| Ask, SDMX data | not available: entry points hidden | — |

Two server fixes came out of the parity runs:
- **BM25 ties are now deterministic.** `_fts_search` orders by
  `round(score, 8)`; identical split siblings used to differ in the last bit by
  summation order. On the copy, the 17 eval questions keep the same top 10.
- **Q2/Q3 recipes list every common year,** not only the year they read.
  Without this, the page's year selector showed a single year.

Parity on a sample build of the copy:
- 784/784 API cases match, plus 4 budget refusals;
- 504/504 with downloads and evidence included.

Browser smoke with `tools/static-engine/serve.py` (Apache's rewrites, no
Python app):
- 13 pages × 1280/390 px;
- no `/api` request, no console error, no horizontal scroll.

The agent search eval differs from its baseline in 13 of 17 questions, for
reasons that predate this work: the baseline was built on an older search
index. Rebuilding the baseline is a separate decision.
