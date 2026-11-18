# Homepage refresh — handoff (2026-11-18)

Spec: [plan.md](plan.md) (copied from the planning session). Branch `feat/homepage-refresh`, cut from
`main` at `bf91fbf`. The branch is pushed; nothing is merged or deployed. The work was started on the production
VPS and moved here; read "Machine-specific" before re-running anything.

## State

| Chunk | Status | Commit |
|---|---|---|
| 1. Hero: h1, lead, search field, three figures; topbar strip removed | done | `e107632` |
| 2. County tile map (`js/county-tiles.js`), shading, legend, picker | done | `d67d45c` |
| 3. Feature band (five tiles) | done | `49941c3` |
| 4. Headings, order, cleanup, pre-paint theme, RO defaults, docs | done; verified 2026-11-19 (Mac) | `55ff4a3` |

The branch is pushed (`origin/feat/homepage-refresh`). It is not merged or deployed.

Remaining:
- **Rebase on `main`**: not done, because the branch is already on `origin`. The owner decides
  between a rebase with a force push and a merge of `main`. `main` has 6 commits after `bf91fbf`
  (About MCP/BYOK sections, deploy-static); they touch `explore-app.js` (`UI.*.aboutHtml`) and
  `explore.css` only.
- **`docs/activity-history.md` entry**: not written. Add it after the rebase or merge decision
  (everyone edits that file).
- Copy wording is a proposal for the owner (see "Owner decisions").

## Verification on the Mac (2026-11-19)

- **Full suite**: `2378 passed, 34 skipped, 7 warnings in 826.26s` (exit 0).
- **`tests/browser/audit_layout.py --shots DIR`** (app on :8097): all 8 home runs OK (320, 390, 768,
  1440 px; RO light and EN dark). Four other runs fail, and they fail on `main` too:
  `v1-POP107A` and `v1-long` at 320 EN dark (`.dim-picker-select` with English labels, scrollWidth 332)
  and `v2-POP107A` at 320 (scrollWidth 321). To compare with a `main` worktree, link
  `data/2-metas` into it: `dataset_meta._EN_METAS_DIR` reads the checkout's `data/2-metas/en`, not
  `TEMPO_DATA_DIR`, so without it English labels fall back to Romanian.
- **Static mode** (`build-static.py --codes POP107A --api-origin http://localhost:8097`, served by
  `tools/static-engine/serve.py`): RO and EN, light and dark, 390 and 1440 px. Hero figures
  3.376 / 149 mil. (149M) / 1901–2026, 42 shaded tiles with a 4-step legend, five feature tiles,
  the MCP line, no horizontal scroll, no `/api` request. The only errors are 20 404s per load for
  `rec/insights/*` and `rec/datasets/CON104*`: the theme cards ask for datasets that a
  `--codes POP107A` build does not record. A full build records them.
- **Manual checks** (server mode, Playwright): `/` opens the search overlay and focuses
  `#search-input` (a `/` typed into another input or a select stays there). The language and theme
  toggles redraw the hero, map and legend with no reload; the steps stay the same, the colours
  follow the theme. Tile clicks (and Enter on a focused tile) reach `/place/county/cluj` and
  `/place/county/municipiul-bucuresti`. `/?q=somaj` opens the overlay with the query and 15 results
  over the hero, as on `main` (same `openSearch(q)` call).

## What was verified against code and data (the plan left these open)

- **Corpus summary keys** (`app/routers/categories.py` `get_corpus_summary`): `corpus = {datasets,
  observations, categories, time_span: {min, max}, geo_datasets}`. On the served generation:
  3,376 datasets, 149,494,783 observations, 1901–2026. The plan's "x,x mld" was wrong: it is
  ~149 million, shown with the existing `formatCompact` ("149 mil." / "149M").
- **Body classes**: `showBrowse` and `showCategoryGrid` add `landing-page` and remove `catalog-page`;
  `drillCategory` removes `landing-page` and adds `catalog-page`; `showAbout` and the `?code=` view
  (`showDashboardV1`) remove both. So `body:not(.landing-page)` hides every home-only block in the
  catalog, `?code=` and about views. On `?cat=` deep links `showBrowse` still renders the hero
  (hidden) before drilling, so `/places`, `/recipes` and `/reference/population` are fetched there too.
- **County slugs**: only Bucharest differs from posturi: `B` is `municipiul-bucuresti` here
  (`bucuresti` in posturi). All 42 tile slugs equal the county slugs of `/api/places`, and
  `slugify` of all 42 `/api/reference/population?level=county` area names (e.g. "Municipiul
  Bucuresti") gives the same 42 slugs, in Python and in the JS port. Population years common to
  all 42 counties run to 2026 (min 186,131, max 1,713,832).
- **`categoryTrends`**: used only by `_renderTrendIndicator`, which had no caller. Both removed with
  the `/api/categories/trends` fetch; a home load now requests only `categories`, `corpus/summary`,
  `places`, `recipes`, `reference/population` (plus the existing theme teaser calls).
  `API.getCategoryTrends` stays in `api.js` (not in this change's files).
- **Developer links**: `/llms.txt` is served by `app/main.py` (GET; HEAD answers 404, which is
  harmless) and written at the static site root by `build-static.py`. `docs/SDMX-API.md` exists;
  linked as `https://github.com/gov2-ro/tempo-ins-dump/blob/main/docs/SDMX-API.md`. The MCP line
  shows only when `window.TEMPO_CONFIG.api_origin` is set (static builds with `--api-origin`).
- **Static build shipping**: `assemble_site` copies every file under `app/static` (except
  `_obsolete`), so `js/county-tiles.js` ships. `scripts/static_api.py` records `corpus-summary`,
  `categories`, `places`, `recipes.{lang}` and `population.{county,region,macroregion}`, and
  `static-api.js` `handle()` routes all five, so every path the homepage requests has a static
  answer. The Docker image copies `app/`, so the new file is in it.
- **Recipes**: `/api/recipes` returns `{recipes: [{id, version, question, name, status}]}`; three
  recipes. Names carry a long parenthetical; the tile strips a trailing `( … )`.

## Where the code differed from the plan, and what was done

- **`ui-rhythm.css` versioning**: commit `375f4ef` only bumped `explore-app.js`, it set no precedent
  for the CSS. Only `index.html` moved to `ui-rhythm.css?v=5`; the other six pages keep `v=4`
  (they are out of scope and unaffected; noted in `docs/BACKLOG.md`).
- **Deleted shared CSS** (`ui-rhythm.css`): `.landing-tools*` and `.corpus-compact` rules (incl. the
  1250 px media line); from the 900 px line only the four `.landing-page …` / `.landing-tools`
  selectors (the `.headlines-grid` and `.dims-page` rules there stay); the 640 px
  `.landing-page .topbar .search-trigger…` and `.landing-tools` rules; the 640 px
  `.landing-page .topbar .search-trigger > span` rule; the 641–900 px
  `.landing-page .topbar .topbar-left` block. In the 640 px font-size list, `.landing-tools select`
  became `.landing-county select`. Every deleted selector was scoped to `.landing-page` or to the
  removed `landing-tools`/`corpus-compact` elements, so no other page could match them. A Sonnet
  sub-agent compared six pages (places, a county profile, Ask, compare recipe, dataset-v2 POP107D,
  dimensions explorer) at 390 and 1440 px, light and dark, old CSS vs new: computed styles of every
  element identical; screenshot differences were async noise, except a 4×1 px sub-pixel difference
  on compare 390 light (2–4 per channel, identical computed styles).
- **County picker**: moved into the hero in chunk 1 (not chunk 2) so the picker was never missing
  between commits.
- **Order of home sections**: the theme nav sits above the questions in the catalog view, below the
  "Themes" heading on home. Instead of duplicating it, `renderQuestions` moves the `#theme-nav`
  node (`cat` given: before the questions; home: after `#landing-themes-title`).
- **Shading year**: the latest year that every county has, not each county's own latest. If any
  tile lacks a value, or the fetch fails, the map stays unshaded with no legend.
- **Dark contrast**: the darkest step uses `color: var(--bg-1)` on `var(--accent)` (white on indigo
  in light, near-black on light indigo in dark). Steps use `color-mix()` over `--bg-1`.
- **Static defaults**: besides the plan's lines, the search-footer hints and the footer
  "Dimensions" link got ids and are now localized in `applyLang` (they were English-only before,
  so switching their HTML to Romanian would otherwise have left English visitors with Romanian).
  Dashboard-view labels (Trends, Snapshot, …) were left alone.
- **Feature grid**: `minmax(min(100%, 14rem), 1fr)` (plan: 15rem) so all five tiles fit one row at
  1440 px instead of four plus an orphan.

## Tests

- `tests/test_county_tiles.py` (new): `9 passed, 1 skipped` without the corpus; with it
  `10 passed, 3 warnings` (FastAPI `regex` deprecation warnings, pre-existing). The corpus test
  checks tile slugs against `/api/places` and population area names (Python and JS `slugify`).
- Full suite: passed on 2026-11-19 (see "Verification on the Mac").

## Browser checks done (Playwright, app on :8097, server mode only)

- Home at 320, 390, 768, 1440 px, RO light and EN dark: no horizontal scroll, no console errors,
  screenshots looked at (hero, map with legend, band, headings).
- `/?cat=1`: hero, band and home headings hidden, topbar search back, nav above questions.
  `/?code=POP107A` and `/?page=about` render as before.
- `/api/reference/population` and `/api/recipes` blocked: map unshaded without legend, recipes tile
  shows only the Compare link, no page error.
- No request to `/api/categories/trends` on home.
- Static mode: exercised on 2026-11-19 (see "Verification on the Mac").

## Owner decisions

- Copy: h1 "Statistica oficială a României, mai ușor de explorat" / "Romania's official
  statistics, easier to explore"; lead; figure labels "seturi de date / valori / ani acoperiți";
  tile texts (`featPlaces` … `featDims`, `questionsTitle`, `themesTitle` in `UI.ro`/`UI.en` of
  `explore-app.js`). "Profiluri de județ" claims births among the profile contents: confirm.
- The span figure shows 1901–2026 (the corpus minimum year); decide if that is the figure to show.
- Meta descriptions still say "peste 1900 de seturi" (BACKLOG).

## Machine-specific (will differ locally)

- Interpreter: `~/devbox/envs/240826` did not exist on the VPS; a throwaway venv in the session
  scratch dir was built from `requirements-dev.txt` + `requirements-pipeline.txt` + `playwright`.
  Locally use `source ~/devbox/envs/240826/bin/activate`.
- Data: the main checkout on the VPS had no `data/corpus`, so the dev server and the corpus test read
  the deployed generation `/opt/tempo/current/data` (DuckDB opened `read_only=True` by `app/db.py`,
  `HOME` and `TEMPO_DUCKDB_TEMP_DIR` pointed at scratch copies). Locally use the checkout's `data/`.
- The static build output and screenshots lived in the scratch dir and are gone; rebuild locally.

## Files

`app/static/index.html`, `app/static/js/explore-app.js`, `app/static/css/ui-rhythm.css`,
new `app/static/js/county-tiles.js`, new `tests/test_county_tiles.py`, `AGENTS.md`,
`docs/BACKLOG.md`, this folder.
