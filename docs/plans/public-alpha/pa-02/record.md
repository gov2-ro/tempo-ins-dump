# PA-02 implementation record

Branch `pa/00-baseline`, generation `a6737a26…` (copy `tempo-gen-20261005`).
Recorded 2026-10-11. Not deployed. Real first-time task completion is PA-04's to
measure; this record covers the automated checks only.

## Increments

| Commit | Scope | Audit |
|---|---|---|
| `070b589` | PA-02a: `/api/search` with reviewed concepts (`app/data/concepts.json`), parsed places/level/year, ambiguity and alternatives, family-grouped full-text results; `/api/datasets/{code}/options` (searchable, paginated actual values, period bounds); both search overlays; selection headline on the dataset page | A07, A11 |
| `06d9280` | PA-02b: home "question / place / indicator" entry points with guided Q1–Q4; place themes from stable context codes; `?place=` carried into dataset selection | A11 |
| `9b8829b` | PA-02b: related datasets labelled by difference instead of "100%"; mobile Dimension Browser select | A10, A11 |
| `072ff92` | PA-02c: canonical `/dataset/{code}` with initial HTML + JSON-LD; alias/filtered noindex; `sitemap.xml`; `robots.txt` | A12 |

## Search judgments

Reviewed truth in `data/eval/pa02_concept_judgments.json`: 21 RO/EN phrases
for Q1–Q4 (two or more per question, accented and unaccented, ambiguous forms)
plus 4 unrelated queries. All pass, both with the corpus (`/api/search`) and
without it (matcher). The existing 17-question search eval is unchanged,
because `search_datasets` was not modified. Concept selection is judged
separately from ordering inside a family.

| Phrase | First concept → dataset | Selection |
|---|---|---|
| Cum a evoluat populația rezidentă a județului Cluj? | resident_population → POP105A_judete_grupe | REF_AREA=Cluj |
| populatie | resident_population, **ambiguous**; alternatives: domicile, 1 July | — |
| Cum se compară salariul mediu net în Cluj, Iași și București? | net_earnings → FOM106E_judete | 3 counties |
| salariu mediu brut bucuresti | gross_earnings → FOM107E_judete | Bucharest |
| În ce județe este cea mai mare rată a șomajului înregistrat? | registered_unemployment_rate → SOM103A_judete | level=county |
| unemployment rate | registered, **ambiguous**; alternative: ILO | — |
| Ce județe au cele mai multe înnoptări turistice pe locuitor? | tourist_overnight_stays → TUR105D_judete | level=county |
| Cluj-Napoca populatie | resident_population; place flagged "city, data is for Cluj county" | Cluj |
| populatia rezidenta 2030 | resident_population; "no data for 2030 (2012–2025)", not pinned | — |

## Journey checks (browser, :8097 on the copy)

- Home at 1280/390: entry points visible, 43 counties in the picker, no overflow.
  The guided Q3 link opens the search showing the SOM103A concept card.
- The search answer to "Cum a evoluat…Cluj" (keyboard ↓ Enter) opens
  `POP105A_judete_grupe` with `f={"REF_AREA":"Cluj"}`. The headline card reads
  **Selecția ta: Cluj 697.030 · 2025 · ▲0.5% față de 2024**, the dataset-wide
  KPIs are labelled as such, and the map highlights Cluj.
- Place Bucharest → POP105A_judete_grupe: the selection resolves to
  `Municipiul Bucuresti`, 1,709,458 (2025). A dataset with no geography and
  `?place=` shows a notice instead of national data.
- FOM106E / SOM103A with a county selection: the headline shows "Total
  indisponibil: rată/medie/indice fără ponderi". This is PA-00's blocker, made
  visible, not a number. TUR105D for Cluj/Iași/Bucharest 2024 matches the Q4
  inputs (1,208,319 / 602,753 / 3,969,063).
- Cluj place page: 0 of 997 datasets under "Other" (was 868); 19 groups.
- Dimension Browser at 320/390: a labelled 44px select, in sync with the
  pills; no overflow.
- Canonical pages: `/dataset/POP105A_judete_grupe` and `/dataset/FOM106F`
  render the dashboard with no page errors and no 4xx; the definition, unit,
  periods and source are in the HTML before JavaScript runs. Sitemap: 3,432 URLs.

## Tests

`python -m pytest tests -q`: **563 passed, 44 skipped** (all skips corpus-marked);
`-m corpus` on the copy: **44 passed**. New: `test_pa02_search.py` (39 + 21
corpus), `test_pa02_pages.py` (8), place theme and diacritics tests in
`test_fix06_place_indicators.py`.

## Remaining restrictions

- Concepts cover the Q1–Q4 families and their look-alikes only. Other
  vocabulary still relies on full-text ranking, which remains weak for long
  questions.
- Places: counties and Bucharest. Localities are flagged ("city, not county")
  but not resolved; regions are not parsed from text.
- The comparison flow (dataset → Iași/Bucharest at a common period) works
  through the filter row and the selection headline. There is no dedicated
  "compare with" control yet.
- Keyboard and screen-reader work covered the new controls only, not a full audit.
- `Dockerfile` now passes `--proxy-headers` so canonical URLs carry https behind
  Fly. Verify in the PA-04 image.

## Rollback

Revert the commits in reverse order. Old `/dataset-v2.html?code=` links work
throughout; the PA-01 safety boundary is untouched by PA-02.
