# Release notes: public alpha (draft, not published)

Draft for the maintainer to edit. Not a statement that anything is live.

## What you can do

- **Ask in your own words.** Search understands ordinary Romanian and English
  questions about resident population, net and gross earnings, registered and
  survey (ILO/BIM) unemployment, tourist overnight stays and tourism intensity.
  It recognises county names and years and opens the dataset with that
  selection. When a word is ambiguous ("populație", "șomaj") it shows the
  alternatives and their definitions.
- **Start from a county.** Each county profile lists its key indicators with
  definitions and sources, and groups its datasets by theme. Opening a dataset
  keeps the county selected.
- **Tourism intensity.** Overnight stays per resident for every county: chart,
  table, definition, exclusions and the source of both numbers.
- **Take the evidence away.** Every dataset view and the tourism page offer a
  ZIP with the result, the data it was computed from, the method, the source and
  checksums. The tourism ZIP also includes a small script that recomputes the
  ranking offline.
- **Share.** Links keep the selection. A link recomputes on the data the site
  serves at the time; the ZIP keeps the answer as it was.

## Data

- Source: INS, TEMPO Online. Data generation `a6737a26…` (built 2026-10-05).
  Latest source update date in the corpus: 2026-08-04. Each dataset shows its own.
- County resident population: 1 January, 2012–2025. Tourism: up to 2024.

## Known restrictions

- **County averages:** net earnings and both-sexes registered unemployment by
  county are not available yet. Our copy lacks the published totals, and the
  site will not average categories that need weights. Each such page says so.
- **Repeated observations:** 160 datasets repeat the same observation with
  different values in the source. They stay viewable as raw data, but the
  site will not total, rank or chart them.
- **2021→2022 break:** county population drops between 1 January 2021 and
  2022 partly because estimates switch from the 2011 to the 2021 census. Read
  that change with care.
- **Question assistant (Ask)** is not available in this alpha.
- **Search vocabulary** is curated only for the topics above. Other topics use
  plain text search.

## Report a problem

Use "Semnalează / Report" on any dataset or the tourism page. It opens a
prefilled public GitHub issue with the page, selection and data generation; you
decide whether to submit it.
