# Homepage refresh (ins.gov2.ro) — implementation plan

Handoff document for an implementing agent. Read "Context" and "Constraints" before touching code.

## Context

The homepage (`/`, the home view of the v1 explorer) is one long category listing. It has no `<h1>`, no value sentence, and no visible search field: search sits behind a topbar trigger, and the corpus figures and county picker are squeezed into a small topbar strip. County profiles, Compare, the three recipes, Ask, the public MCP and SDMX are barely linked or not linked at all.

The sibling project posturi.gov2.ro (`/home/pax/g2-dev/posturi.gov.ro`, homepage in `webapp-php/pages/home.php`) shows a bolder pattern: a two-column hero with search and large figures, a tile map of the counties as an entry point, full-bleed bands, and feature tiles.

Goal: give the homepage a hero and promote the site's features, above all county profiles, without changing the visual language of the site.

Decisions already taken by the owner:

- **Keep tempo's design tokens** (colours, radius, dark mode). Borrow posturi's structure, not the gov2 design system.
- **Hero = search and big figures on the left, county tile map on the right.** Each tile opens that county's profile.
- **Feature tiles for:** county profiles, recipes and Compare, Ask, developers (MCP, SDMX, `llms.txt`), dimensions explorer.

## Constraints

1. **Other agents are working in this repo at the same time, on other subjects.**
   - Work in your own worktree and branch: `git worktree add ../tempo-ins-dump-home -b feat/homepage-refresh`.
   - `data/` is gitignored, so the worktree has none. Point the app at the main checkout's data read-only: `TEMPO_DATA_DIR=/home/pax/g2-dev/tempo-ins-dump/data`. Run no pipeline script.
   - Use your own port (8097, the default of `tests/browser/audit_layout.py`). Do not stop or restart servers you did not start.
   - Touch only the files listed below. Add the `docs/activity-history.md` entry last, after rebasing on `main`, because that file is edited by everyone.
   - Do not merge, push or deploy. Stop at a committed branch and report.
2. **The live site is the static build.** `/api/*` paths are answered in the browser by `app/static/js/engine/static-api.js`, and an unknown path throws 404. Use only answers the build already records: `/api/corpus/summary`, `/api/categories`, `/api/places`, `/api/reference/population?level=county`, `/api/recipes`. **Add no endpoint.**
3. **`explore.css` and `ui-rhythm.css` are loaded by every page.** Every new rule must be scoped under `.landing-page` or use a new `landing-` class. Use existing tokens only (`--bg-*`, `--text-*`, `--accent`, `--border`, `--radius*`, `--page-gutter`, `--content-width`); the page must work in both themes.
4. **The catalog view reuses `#browse-view`.** New home-only blocks must be hidden when a category is drilled (`body.catalog-page`) and in the `?code=` and `?page=about` views. Verify how `drillCategory` (`explore-app.js` ~`:960`) toggles the body classes before relying on them.
5. RO and EN both, switched at runtime: every new string goes in the `UI.ro` / `UI.en` dictionaries (`explore-app.js:10-157`), not in inline ternaries.
6. No new dependency, no build step. Minimal code: reuse what exists.

## Target layout

```
topbar: logo · Locuri · Ask · ? · theme · language      (search trigger and tools strip leave the topbar on home)

+-----------------------------+------------------------+
| H1                          |      SM MM    SV BT    |
| one-sentence lead           |   BH SJ BN NT IS       |
|                             |   AR CJ MS HR BC VS    |
| [ Caută: populație, șomaj ] |   TM HD AB SB BV CV .. |
|                             |   ...                  |
| 1.9xx     x,x mld   1990–   |  Profiluri de județ →  |
| seturi    valori    2026    |  [Județ… v] legend     |
+-----------------------------+------------------------+
| full-bleed band: 5 feature tiles                     |
+------------------------------------------------------+
| h2 Întrebări de pornire  — the six question links    |
| h2 Teme — theme nav, then the existing category grid |
+------------------------------------------------------+
footer
```

Below 1024 px the hero stacks (text, then map). Below 640 px the tiles are one column. No horizontal scroll at 320 px.

## Work, in four chunks (each leaves the page working; commit after each)

### 1. Hero: heading, search, figures

Files: `app/static/index.html`, `app/static/js/explore-app.js`, `app/static/css/ui-rhythm.css`.

- Add `<header id="landing-hero" class="landing-hero">` as the first child of `#browse-view` (`index.html:112`), with two columns: `.landing-hero-main` and `.landing-hero-map`.
- Render it from a new `renderHero(corpus)` called in `showBrowse()` where `renderBrowseHeader` is called today (`explore-app.js:541`).
  - `<h1>` and lead: replace the unused `browseTitle` / `browseSub` / `browseTagline` strings (`:12-14`, `:84-86`). Proposed copy, owner may edit: RO "Statistica oficială a României, mai ușor de explorat" / EN "Romania's official statistics, easier to explore"; lead RO "Seturile de date INS Tempo, cu grafice, profiluri de județ și descărcări." The page must state it is not an INS product only once: the notice bar already does.
  - Search: a large button styled as a field (`.landing-search`) that calls the existing `this.openSearch()` (`:3411`). Do not build a second search. Keep the `/` shortcut.
  - Three figures from `summary.corpus`: datasets, observations, time span. Inspect the actual keys in `app/routers/categories.py:101-176` before use. Format with the existing `formatNumber`. Large type: about `clamp(1.75rem, 3.5vw, 2.75rem)`, weight 700, tabular numbers; label below in `--text-2`. The H1 should be the largest heading on the page (about `clamp(1.75rem, 4vw, 2.75rem)`), unlike posturi's shrunk one.
- Remove the topbar strip: delete the `#landing-tools` creation in `renderEntryPoints` (`:709-730`), `renderBrowseHeader`'s `#corpus-compact` write, and the `.landing-tools` / `.corpus-compact` rules in `ui-rhythm.css` (`:21-24`, `:128-140`, `:210`). On `.landing-page`, hide the topbar `#search-trigger`; remove the landing-specific topbar search rules that then become dead (`ui-rhythm.css:129`, `:137-138`, `:194`, `:204`). Check each rule's selector list before deleting, since several lines carry rules for other pages too.

### 2. County tile map

Files: new `app/static/js/county-tiles.js`, `index.html` (script tag), `explore-app.js`, `ui-rhythm.css`.

- New module `county-tiles.js` exporting, in the same browser-and-Node style as `theme-overviews.js`:
  - `TILES`: code → `[slug, col, row]` for the 42 counties on a 9×7 grid. Port the coordinates from `posturi.gov.ro/webapp-php/helpers.php:2975-2988` (`HOME_COUNTY_TILES`).
  - `steps(values)`: four quantile or log-scale steps for shading, with the break values for the legend.
  - A new file is justified here: the data is testable in Node and reusable by `places.html` later.
- **Slugs must match tempo's, not posturi's.** Tempo builds them with `slugify(name)` (`app/services/place_service.py:49`) from the names in `/api/places`. Check all 42 against the real `/api/places` answer; Bucharest in particular may differ ("bucuresti" vs "municipiul-bucuresti"). Fix `TILES` to tempo's slugs.
- `renderCountyMap()` in `explore-app.js`, called from `renderHero`:
  - Each tile is an `<a href="/place/county/{slug}">` (append `?lang=en` in English, as `:722` does) showing the county code, with `aria-label` and `title` "Cluj — profil de județ". Links, not buttons: the map must work with keyboard and open-in-new-tab.
  - Use `/api/places` (already fetched for the picker) for names. Render only tiles whose slug exists in the answer.
  - Shading: latest-year resident population from `API.fetch('/reference/population', {level:'county'})` (shape `{population: {areaName: {year: value}}}`, see `app/routers/dataset_data.py:46-79` and its use in `dashboard-v2.js:1436-1449`). Match area names to tiles through the same slug rule. Steps as `--accent` at four opacities over `--bg-1`; text colour must keep contrast on the darkest step in both themes. Show a legend with the break values, the year and the source code (POP105A). **If the fetch fails or a county does not match, render the tiles unshaded** and no legend; never guess.
  - Under the map: the caption link "Profiluri de județ →" (`/places`) and the county `<select>` moved from the old topbar strip (reuse the code at `:717-729`), as the fallback for small screens.
- CSS: a CSS grid, `grid-template-columns: repeat(9, minmax(0, 2.75rem))`, 3 px gap, tiles at least 40 px tall, visible focus ring. Model: `posturi.gov.ro/webapp-php/assets/app.css:565-590` (rewrite without `@apply`).

### 3. Feature band

Files: `index.html`, `explore-app.js`, `ui-rhythm.css`.

- Add `<section id="landing-features" class="landing-band">` after the hero, with a visible `<h2>` ("Ce poți face aici" / "What you can do here") and five tiles. Each tile: an inline SVG icon in the style of the existing topbar icons, an `<h3>`, one sentence, one or more links.
  1. **Profiluri de județ** — "Populație, salarii, șomaj și natalitate pentru fiecare județ." → `/places`.
  2. **Indicatori gata calculați** — the three recipes as links, names from `API.fetch('/recipes', {lang})`, each to `/compare.html?recipe={id}` (see `compare.js:76-90`); plus "Compară două seturi →" to `/compare.html`. If the fetch fails, show only the Compare link.
  3. **Întreabă (Ask)** — "Pune o întrebare în limbaj natural; răspunsul vine cu surse." → `/ask.html`, with a small "beta · poate cere propria cheie API" note. Do not fetch `/api/ask/config` from the homepage.
  4. **Pentru dezvoltatori** — links to `/llms.txt` and the SDMX documentation. Show the MCP endpoint (`{api_origin}/mcp`, as copyable text) only when `window.TEMPO_CONFIG.api_origin` is set. Confirm the link targets exist before writing them: `llms.txt` at the site root, `docs/SDMX-API.md` on GitHub.
  5. **Explorator de dimensiuni** — "Vezi ce dimensiuni au seturile și unde se regăsesc." → `/dimensions-explorer.html`.
- Full-bleed band: `background: var(--bg-1); box-shadow: 0 0 0 100vmax var(--bg-1); clip-path: inset(0 -100vmax);` (the pattern at posturi `app.css:595-599`). Tiles: `--bg-0` surface, 1 px `--border`, `--radius`, grid `repeat(auto-fit, minmax(15rem, 1fr))`.
- Remove the now-duplicate "Dimensiuni ↗" link from `renderThemeNav` (`:764-767`). The footer link stays.

### 4. Order, headings, cleanup, tests, docs

- Visible `<h2>`s for the questions block ("Întrebări de pornire") and the category listing ("Teme"). `renderQuestions` and `renderThemeNav` also run in the catalog view: add the headings in the home containers, not inside those functions' output, unless you verify the catalog view is unaffected. `tests/test_static_parity.py:236-300` pins exactly six question links per theme; do not change `ThemeOverviews.questions`.
- Stop fetching `/api/categories/trends` on home (`showBrowse`, `:530`, `:535`) if `this.categoryTrends` and `_renderTrendIndicator` (`:910`) have no other use. Grep first; remove the dead function only if nothing calls it.
- Add the pre-paint theme script that `places.html:11-14` has, so light-theme visitors do not see a dark flash.
- Replace the English defaults in the static HTML with Romanian ("Search datasets...", "Navigate", "Dimensions", `aria-label`s at `index.html:48-57`, `:80`, `:94`, `:188`); JS still localizes at runtime.
- Bump the cache-busting query strings in `index.html` for every changed asset (`explore-app.js?v=107` → 108, `ui-rhythm.css?v=4` → 5, new `county-tiles.js?v=1`). Look at how commit `375f4ef` handled `ui-rhythm.css` on the other pages and follow that.
- Tests (new `tests/test_county_tiles.py`, run through Node like `tests/test_static_parity.py`, skipping without Node):
  - 42 tiles, distinct codes, distinct slugs, distinct `(col, row)`, all inside 9×7.
  - `steps()` on a fixed list returns the expected breaks and step per value; empty or all-equal input does not throw.
  - A `corpus`-marked test: every tile slug appears among the county slugs of `/api/places`, and every county there has a tile.
- Confirm the static build ships the new file: `scripts/build-static.py` `assemble_site` (`:284-308`) copies the static tree, and the Docker image copies `app/` (a test checks the root-module list only). Read, do not assume.
- Docs: update the "Pages" bullet for `index.html` in `AGENTS.md` only if a file name changed (add `county-tiles.js`). Add a `docs/BACKLOG.md` entry: the Open Graph image `img/landing.png` shows the old homepage and needs regenerating. Add the `docs/activity-history.md` entry last.

## Out of scope

- The gov2 design system, and any restyle of other pages.
- New API endpoints, a "top changes" feed, pre-rendering the homepage in the static build.
- Changes to `places.html`, `ask.html`, `compare.html`.
- Deploying, uploading the static site, or regenerating the OG image.

## Verification

Run from the worktree with the environment active (`source ~/devbox/envs/240826/bin/activate`).

1. `python -m pytest tests -q` passes, including the new tile tests and `tests/test_static_parity.py`.
2. Start the app on 8097 with `TEMPO_DATA_DIR` pointing at the main checkout's data. Then `python tests/browser/audit_layout.py --shots <scratch dir>` (read its `--help` first): the home page must show no overflow, no unreachable control and no console error at 320, 390, 768 and 1440 px, in RO light and EN dark. Look at the screenshots.
3. By hand in a browser, console and network tab open:
   - `/`: hero, shaded map with legend, five tiles; a tile opens the right county profile; the hero search opens the overlay; `/` shortcut works; language and theme toggles redraw the hero and map.
   - `/?cat=<code>` and a drilled category: hero and feature band are hidden; the catalog works as before.
   - `/?code=POP107A`, `/?page=about`, `/?q=somaj`: unchanged.
   - Block `/api/reference/population` and `/api/recipes` in devtools: the map renders unshaded, the recipes tile shows only the Compare link, nothing throws.
   - Check that no request goes to `/api/categories/trends` on home.
4. Static mode: if a static build directory exists locally, rebuild or serve it per `docs/DEPLOY-STATIC.md` and repeat step 3 on `/`. If you cannot, say so in the report rather than claiming it works; at minimum confirm that every path the homepage requests has a route in `static-api.js` `handle()` (`:341-383`).
5. Other pages still look the same: open `/places`, one county profile, `/ask.html`, `/compare.html` and one `/dataset/{code}` and compare with `main`, since the stylesheets are shared.

## Report back

State what was done per chunk, the test output, what was verified in a browser and what was not (static mode in particular), the final slugs that differed from posturi's, and any rule deleted from `ui-rhythm.css` that other pages might have depended on.
