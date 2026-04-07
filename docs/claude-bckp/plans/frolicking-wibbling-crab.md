# Plan: Add Missing Data Quirks to `docs/data analysis.md`

## Context
`docs/data notes.md` contains field observations about structural quirks in the INS TEMPO datasets. Most of these are NOT yet documented in `docs/data analysis.md`, which is the canonical reference for data analysis and visualization strategy. The goal is to add a dedicated section covering these quirks so the analysis doc is complete for anyone building charts, aggregations, or classifiers on this data.

## Already Covered (skip)
- Multiple UMs in same column → `Multi-Unit Datasets` section in `data analysis.md`

## Changes: Add new section "Structural Quirks & Edge Cases"

Insert after the "Multi-Unit Datasets" subsection (around line 31), before "## Systematic Approach Framework".

### New section content to add:

#### 1. Composite Dimension Headers (e.g., TCJ0331)
- Column header reads: `Sexe/grupe de varsta/nivel de educatie/regiuni de dezvoltare`
- Slash-separated list = multiple independent dimension categories merged into one column
- Each row holds a value from exactly ONE of those categories
- Cannot be classified as a single semantic type; must be detected and split/filtered
- Implication: the column behaves differently from a standard categorical dimension

#### 2. "Din total" Hierarchical Breakdown Values
- Some datasets embed hierarchy indicators directly in data values via prefixes:
  - `din total: cazuri noi inregistrate`
  - `- din total familii monoparentale` (dash variant)
  - `- Rural`, `- Urban` (dash-prefixed sub-categories)
- These rows are breakdowns of a parent total, not independent observations
- Critical implications:
  - Do NOT aggregate across parent + child rows (double-counting)
  - Prefix variants are inconsistent across datasets (colon, dash, dash+din total)
  - Must detect and flag these rows before summing or visualizing
- Example datasets: SAN110A/B/C, ASS118B/D, SAN104B

#### 3. Sub-Dimensional Nesting: Judete > Localitati (e.g., AGR101B, SAN104B)
- Geographic hierarchy encoded across two separate columns: `Judete` + `Localitati`
- Locality values are composite strings: `SIRUTA_CODE LABEL` (e.g., `1017 MUNICIPIUL ALBA IULIA`, `6627 RAMET`)
- SIRUTA = numeric Romanian locality identifier
- Must parse: split on first space to extract code vs. label
- Relates to GIS section below

#### 4. GIS / Geographic Hierarchy Specifics
- Full hierarchy: National → Macroregion (MACROREGIUNEA UNU) → Region (Regiunea NORD-VEST) → County (Judet) → Locality/Municipality/Town
- "Nivel national" is implied when the region/county dimension value = "Total"
- Localities can be: Localitati (general), Municipii si orase (cities & towns), or Comune
- Municipality names include prefix: `MUNICIPIUL ALBA IULIA`, `ORAS CODLEA`, `MUNICIPIUL RESITA`
- SIRUTA codes in locality columns enable GIS joins

#### 5. Demographics: Mixed Age Granularity
- Same dimension column can contain both:
  - Individual ages: `varste` (e.g., exact year values)
  - Grouped ranges: `grupe de vârstă` (e.g., `25-34 ani`, `65 ani si peste`)
- Both types appear as distinct values in the same column, not in separate columns
- Cannot be sorted or compared numerically without parsing
- Implication: detect presence of age groups vs. individual ages before choosing chart type (histogram vs. grouped bar)

#### 6. Measure-as-Dimension Column (e.g., FOM121B)
- First column is not a categorical filter but a "measure selector"
- Example header: `Salariati salariul brut de baza si venitul brut realizat`
- Values in this column: count of employees (`Numarul salariatilor...`), base salary (`Salariul brut de baza`), gross income (`Venitul brut realizat`)
- These are completely different metric types sharing the same table structure
- Combined with mixed UM column (`Numar persoane` + `Lei`)
- Implication: treat this first column as a mandatory pivot axis — same as Multi-Unit treatment; always filter/separate before any aggregation or charting

## File to Edit
- `/Users/pax/devbox/gov2/tempo-ins-dump/docs/data analysis.md`
  - Insert new section after line 31 (end of Multi-Unit Datasets block)
  - Title: `## Structural Quirks & Edge Cases`

## Verification
- Read the updated file to confirm formatting is correct and content flows logically
- No code changes, no new files needed
