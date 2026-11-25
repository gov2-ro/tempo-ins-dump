# NAV — One top bar for every page

Brief for a Sonnet session. Written by Opus on 2026-11-25.

## Why

Seven pages copy the top bar by hand, and the copies have drifted. Some differences:

- `index.html`: sidebar toggle, search trigger, Locuri, Ask, API, About, theme, language.
- `places.html` and `place.html`: "Date" and "Locuri" as text, with no icons and no search.
- `ask.html`: "← Datasets" and its own settings panel.
- `dataset-v2.html` and `compare.html`: the `site-chrome.js` bar with an "Ask AI – NL2SQL" title.
- `api.html`: its own copy of the bar.
- `dimensions-explorer.html`: a different bar again.

Selected user testing starts soon. Users must see the same navigation on every page.

## Decisions (Opus)

1. **One source of markup.** `site-chrome.js` renders the bar into a placeholder on each page:
   `<nav class="topbar" id="topbar" data-active="data|places|ask|api|…"></nav>`. Do not copy the bar
   into HTML files again. The pre-rendered dataset pages from `scripts/build-static.py` must also get it.
2. **Same order everywhere:**
   - Left: the logo, then a page slot (for example the sidebar toggle on the home page).
   - Centre: the global search trigger, on every page (the `/` key opens it).
   - Right: Date · Locuri · Ask · API, each with an icon and a label. The current page is marked
     (`aria-current="page"`). Then a page slot (Ask settings, the place search), then About (`?`),
     theme and language.
3. **Same labels in both languages:** Date/Data, Locuri/Places, Ask, API. Drop "NL2SQL" and
   "← Datasets".
4. **Keep the existing element ids** (`search-trigger`, `theme-toggle`, `lang-toggle`, `about-btn`,
   `sidebar-toggle`). `explore-app.js` and the page controllers bind to them.
5. **Phone width:** at 375 px the labels collapse to icons (`.tb-label` already does this on the home
   page). No horizontal scroll.
6. **Keep the theme and language preferences** in the same `localStorage` keys (`lens_theme`,
   `lens_lang`).

## Out of scope

The footer, the sidebar contents, and page content. The city-pages work (CP) changes the content of
`places.html` and `place.html` at the same time; do not touch their content area.

## Acceptance

- `python -m pytest tests -q` passes, and `tests/test_static_parity.py` passes.
- A Playwright smoke of every page (`/`, `/?code=POP107A`, `/dataset-v2.html?code=POP107A`,
  `/compare.html`, `/places`, `/place/county/cluj`, `/ask.html`, `/api.html`, `/dimensions-explorer.html`)
  at 1280 px and at 375 px. Check: the same links in the same order, the active link, the theme and
  language toggles, `/` opens the search, no console errors, and `scrollWidth` equals the viewport width.
- Attach before and after screenshots of each page's bar.

## Stop and ask

Stop and ask if a page cannot use the shared bar without a change to its controller's behaviour.
