# FIX-07 — Responsive dataset controls and readable charts

Status: not started. Priority: P2. Owner: frontend.
Dependencies: coordinate FIX-02's unavailable/provenance payloads. Layout fixes
may proceed independently; do not change chart aggregation while fixing CSS.

## Problem and entry points

Live POP107A at 390px has document widths 617px (v1) and 445px (v2). Topbar actions,
chart pills and dimension selectors escape their containers. Desktop v2 clips long
numeric axis labels and exposes internal chart identifiers such as
population_pyramid. Bihor fits at the same narrow viewport, so reuse working
layout conventions instead of globally compressing every page.

Read index.html, dataset-v2.html, explore.css and relevant dataset styles,
`explore-app.js`, `dashboard-v2.js`, chart-factory/new-types/geo/demographic,
site-chrome.js and shared formatters. Determine actual loaded styles/scripts first;
historical controllers in _obsolete are not the live page.

## Required behavior

- At 390px and 320px, the page fits the viewport. Topbar actions remain reachable.
  Pills/selectors wrap or scroll inside a clearly bounded control container.
  Horizontal data tables may scroll within their own container; body overflow
  must not be used to hide unreachable controls.
- Keep labels, active selection and control focus visible. Keyboard users can
  operate the chart choices, period navigation and filter selectors; icon-only
  actions have meaningful accessible names. Preserve existing shortcuts.
- Charts resize after layout/theme/panel changes without stale canvas dimensions.
  Reserve enough axis margin and use shared compact number formatting with full
  values available in tooltips. Avoid clipping or ambiguous identical tick labels.
- Use translated user-facing chart names; leave internal identifiers in developer
  diagnostics. Explain sampling/windowing and unavailable totals consistently with
  FIX-02; do not recompute an unsafe total in a client helper.
- Preserve URL state, filters, theme/language, PNG export and period controls.
  Fix v1/v2 together until one is explicitly retired in a separate task.

## Acceptance checks

Use Playwright against fixture-backed local pages; record screenshots and DOM
assertions at 320, 390, 768 and 1440px in RO/EN and light/dark:

1. Home, search overlay, geo+age dataset, long categorical dataset, dataset v2,
   places directory and one place page have no unintended document overflow.
2. Every visible control is reachable and its focus ring/selected state is visible.
   Check keyboard flow and a 200% zoom case; screenshots alone are insufficient.
3. Numeric axes remain readable; tooltip values agree with data. Chart resize and
   switching chart/period/filter/theme do not emit console or request errors.
4. URL-state round-trip restores the selected filters/chart/period. Export and
   unavailable/sampled-state messages remain usable at narrow sizes.

Do not approve tests that merely assert overflow:hidden. Keep assertions focused
on control reachability and usable charts. Existing unrelated favicon 404 should
be fixed or explicitly separated from functional console-error checks.

## Completion evidence

Provide before/after viewport screenshots, browser assertions and the scope of any
remaining intentional overflow. Do not add a frontend framework or redesign the
navigation hierarchy as part of this repair.
