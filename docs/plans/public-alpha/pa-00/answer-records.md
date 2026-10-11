# PA-00 answer records, Q1–Q5

Version 1, 2026-10-11, generation `a6737a263a34…` (see [baseline](baseline.md)).
Machine-readable expectations: [answers.json](answers.json).

**No record is `verified`.** Verification needs a reviewer and an independent INS
cell. INS could not be reached today, and the retained exports contain no total
rows (stage 6 drops options labelled "Total"). Values below come from the corpus
and were cross-checked against the retained CSVs. They are not golden numbers.

| Q | Status | Blocker / next step |
|---|---|---|
| Q1 population | `candidate` | Fetch INS Total cells for Cluj/Iași/Bucharest 2012–2025; explain the national 7,120 gap |
| Q2 net earnings | `blocked` | No county all-activities × both-sexes cell in the corpus |
| Q3 unemployment | `blocked` | No both-sexes rate in the corpus. Source decided: SOM103A (annual) |
| Q4 tourism intensity | `candidate`, **feasible** | Denominator approved (1 January). Still needs county denominators verified, as in Q1 |
| Q5 share/reproduce | `candidate` | Checklist below; acceptance is PA-03 |

**Decisions (owner, 2026-10-11):** the reference-cell fetch is approved; Q3 uses
SOM103A (annual); Q4 uses population on 1 January of the same year.

**Approved prerequisite:** a bounded, read-only INS fetch
of the reference cells below. Results are stored as retained evidence with
fetch time and sha256, and are not written into the corpus. Folding the cells into
the corpus would be a separate FIX-03-style repair.

| Matrix | Cells | Requests |
|---|---|---|
| POP105A | Total age × Total sex × Total residence × {TOTAL, 42 counties} × 2012–2025 | 1–2 |
| FOM106E | TOTAL activity × Total sex × {TOTAL, 42 counties} × 2008–2024 | 1 |
| SOM103A | Total sex × {TOTAL, 42 counties} × 1991–2024 | 1 |
| TUR105D | Total × Total × {TOTAL, 42 counties} × 2012–2024 (numerator per county) | 1 |

Spec: [reference-cells.json](reference-cells.json). Command (not yet run: INS
offline on 2026-10-11):

```bash
python scripts/fetch-ins-reference-cells.py --spec docs/plans/public-alpha/pa-00/reference-cells.json \
  --meta-dir $G/2-metas/ro --out /Users/pax/devbox/gov2/tempo-gen-20261005/reports/pa00-reference-cells
```

## Source files

Retained INS exports in `tempo-gen-20261005/data/`. `ultimaActualizare` is the INS
"last updated" date in the retained metadata.

| File | sha256 | INS updated |
|---|---|---|
| `2-metas/ro/POP105A.json` | `e1016ca853d36eb8546f2765f7d2f3ed934217f4ed75d0d68a8b010d31cb3684` | 02-09-2025 |
| `4-datasets/ro/POP105A.csv` | `009347a6415a2feac08a7b4ac791a8d4aa5705948f01b39fe84908b58575b5f2` | — |
| `2-metas/ro/TUR105D.json` | `61261a474ce58e77a1bd87462605b718056dad115a4767a462b42c54106c8084` | 02-04-2025 |
| `4-datasets/ro/TUR105D.csv` | `22b60d5b2d992369d6460ff9719e5cd0915e13f113bbd1c79c244796ea71148d` | — |
| `2-metas/ro/SOM103A.json` | `b646986956fef4776b82ec3f69ade1ba14291d7e129573c3df9734114bc90619` | 15-10-2025 |
| `4-datasets/ro/SOM103A.csv` | `f7544bd6b33e9e863b605f58f4ad4870b8d595a0a74934ab692773e1485bdbfe` | — |
| `2-metas/ro/SOM103B.json` | `27fb02d0b99d9e71dd1099edb4a67a7c9ff25fb001f253bec38aafc6cd0b1c47` | 13-07-2026 |
| `4-datasets/ro/SOM103B.csv` | `89afc8326e34f3a568de6c43ba89aeac49f1945bc639e2257ac1734084041226` | — |
| `2-metas/ro/FOM106E.json` | `c7d4f96f39b0829447700defc6d2730793ba54e9ca4de0e39b602de6b13015e1` | 04-09-2025 |
| `4-datasets/ro/FOM106E.csv` | `2de12d8f448f9a373748244f625f9aeac7d1601a18649aa8b19691ca250844c9` | — |

Recompute with the `shasum` line in [Reproduction](#reproduction). Retained INS cells from the 2026-10-05 total check:
`tempo-gen-20261005/reports/totals/cache/{POP105A,FOM106E,SOM103A,TUR105C}-*.csv`.

---

## Q1 — Resident population over time

- **Identity:** Q1 v1, `candidate`, unreviewed.
- **Intent:** RO “Cum a evoluat populația rezidentă a județului Cluj?”, “populatia
  rezidenta Cluj”, “câți locuitori are județul Cluj”. EN “How has Cluj county's
  resident population changed?”, “Cluj population over time”. Ambiguity:
  resident (POP105A) vs domicile (POP107A) vs 1 July (POP106A); county vs
  Cluj-Napoca municipality.
- **Sources:** `POP105A` → `POP105A_judete_grupe`. Definition: usual residence
  (Reg. 1260/2013). County detail from 1 January 2012.
- **Selection:** `REF_AREA` ∈ {Cluj, Iasi, Municipiul Bucuresti} (county level; place
  slugs `county/cluj`, `county/iasi`, `county/municipiul-bucuresti`). Collapse the
  18 five-year age groups (0–4 … 85+), both sexes and urban + rural. Never use
  `_judete_varste`: its single years stop at 84, so its sum is about 2 % short.
- **Meaning:** stock, persons, reference date 1 January. Annual, 2012–2025.
- **Expected (candidate):** Cluj 2012 693,608 … 2021 710,664 · 2022 683,028 ·
  2023 688,844 · 2024 693,507 · **2025 697,030**. Iași 2025 780,364; Bucharest
  2025 1,709,458. Full series in `answers.json`. No missing years.
- **Series break:** every county drops between 2021 and 2022 (Cluj −27,636).
  Pre-2022 estimates rest on the 2011 census, later ones on the 2021 census
  (POP105A methodology). A change across that boundary must be labelled, not
  presented as population loss. *Needs reviewer confirmation from the INS
  quality report.* INS says 2023 was revised and earlier years are final.
- **Verification:** **Observed:** 42 county-year sums equal the retained CSV
  exactly. The partition is complete by construction (groups tile 0–85+, both
  sexes, both residence types; Bucharest has no rural rows). **Missing:** an INS
  Total cell per county. National 2025: ours 19,036,031, INS cell (fetched
  2026-10-05) 19,043,151. Unexplained. Possibly a later revision; retained
  metadata is the 2 Sep 2025 version. Tolerance for counts: 0.
- **Quality:** unique grain (no duplicate keys); not in the conflicting-grain
  list; source-total check `match` only under a 0.5 % tolerance (see above).
- **Interaction:** line chart 2012–2025 with the break marked; latest value and
  reference date beside it; link state `county/cluj` + `POP105A_judete_grupe`.
  **Observed:** `/data` grouped by `TIME_PERIOD` with `REF_AREA=[Cluj]` returns
  these values (`valid_slice`, `sum_partition`). The Cluj and Iași place pages
  show 2025. **The Bucharest place page shows no population KPI.**
- **Negative cases:** domicile/1 July datasets offered as "the same"; 2026
  requested (not in this generation); summing years; summing `_varste` or mixing
  `_grupe` and `_varste`; locality "Cluj-Napoca" resolved as the county; unknown
  value `Clujj` (**Observed:** `unavailable/slice_value_missing`, correct).

## Q2 — County net earnings comparison

- **Identity:** Q2 v1, **`blocked`**.
- **Intent:** RO “Cum se compară salariul mediu net în Cluj, Iași și București?”,
  “salariu mediu net cluj iasi bucuresti”. EN “Compare average net earnings in
  Cluj, Iași and Bucharest”, “average salary by county”. Ambiguity: net vs gross
  (FOM104*); monthly figure from the annual survey vs the monthly release.
- **Sources:** `FOM106E` → `FOM106E_judete` (CAEN Rev.2, 2008–2024; FOM106A
  continues it to 2007). Annual survey, lei, nominal. The annual figure includes
  back pay that the monthly release does not (source note).
- **Blocker:** the corpus holds 67 CAEN sections/divisions × 2 sexes per county.
  The TOTAL-activity × Total-sex mean is the needed cell, and it was dropped at
  fetch. These are means, so they cannot be summed or simply averaged.
  **Observed:** the API refuses (`missing_weights`); with `approximate=1` it
  returns an unweighted mean (Cluj 5,522, Iași 4,880, Bucharest 6,890 for 2024).
  That is not the statistic. The place page omits the KPI with a note blaming
  the source. It should blame our fetch.
- **Unblock:** fetch the reference cells (1 request), then approve the record.
  Latest common period in this generation would be 2024. INS national TOTAL 2024 =
  4,959 lei (retained cell).
- **Negative cases:** gross vs net; averaging divisions; mixing FOM106A Rev.1 with
  FOM106E Rev.2 across 2008; a county with a missing year.

## Q3 — Registered unemployment ranking

- **Identity:** Q3 v1, **`blocked`**.
- **Intent:** RO “În ce județe este cea mai mare rată a șomajului înregistrat?”,
  “somaj judete”. EN “Which counties have the highest registered unemployment
  rate?”, “unemployment rate by county”. Ambiguity: registered (ANOFM) vs ILO/BIM
  survey (AMG*); annual vs end-of-month.
- **Sources:** **`SOM103A` (annual, 1991–2024), decided 2026-10-11.** `SOM103B`
  (end of month, to 2026-05) is a different statistic and stays out of Q3. The rate
  is registered unemployed / civilian active population × 100.
- **Blocker:** only Masculin/Feminin rates per county. The weights (active
  population by sex and county) are not in the corpus. **Observed:** the API
  refuses by default. The Cluj place page shows **1.5 % (2024)**, a labelled
  unweighted mean of 1.3 and 1.6. Its definition text says INS has no
  both-sexes row. INS does have one (national Total 2024 = 3.3 %, retained cell).
- **Universe:** 41 counties + Municipiul Bucuresti (42). Bucharest was labelled
  "Mun. Bucuresti -incl. SAI" for 1991–1996 only; it needs one identity across
  that relabelling.
- **Unblock:** fetch the reference cells (1 request), rank 42 areas in 2024,
  percent with one decimal as published, ties broken by area name, changes in
  percentage points.
- **Negative cases:** BIM rate; an unweighted sex average; ranking each county's
  own latest month; correlation on a constant axis.

## Q4 — Tourism intensity

- **Identity:** Q4 v1, `candidate`. **Feasibility: feasible.** PA-03 may plan
  against it once the denominator is approved and verified.
- **Intent:** RO “Ce județe au cele mai multe înnoptări turistice pe locuitor?”,
  “innoptari pe locuitor judete”. EN “Which counties have the most tourist
  overnight stays per resident?”, “tourism intensity by county”.
- **Sources:** numerator `TUR105D` → `TUR105D_judete` (annual, structures with at
  least 5 bed-places, all structure types, Romanian + foreign tourists).
  Denominator `POP105A_judete_grupe` as in Q1. **Exclude `TUR105E_judet` and
  `TUR105H_judet`.** Both have conflicting grain.
- **Formula (approved 2026-10-11):** stays(county, Y) / resident population(county, 1 Jan Y).
  The owner also considered "the population observation nearest the year, past or
  future". It was not chosen, because it needs a substitution rule and the
  denominator year would vary between counties. If it is ever added, it must be a
  separately named approximation.
  Name it "înnoptări per locuitor (populația rezidentă la 1 ianuarie)". It is not
  an annual-average population, and not the share of residents travelling.
- **Period:** latest common year **2024**. TUR105D ends at 2024; POP105A has
  1 Jan 2025, but 2025 stays are not in this generation. 2021–2022 were revised
  to include rented rooms/apartments, so do not compare with earlier years
  without a note.
- **Verification:** **Observed:** the numerator's 2024 national sum is
  **30,837,328**, equal to the INS `TUR105C` Total cell (fetched 2026-10-05). That
  is independent evidence that types × tourist types × counties is a complete,
  disjoint partition for 2024. Unique grain; 42 areas; 5 zero cells, no nulls.
  Denominator: same status as Q1 (no county INS cell yet).
- **Candidate result 2024** (feasibility only, not approved): Constanța 8.465,
  Brașov 5.270, Vâlcea 4.264, Covasna 3.123, Bihor 2.784 … Bucharest 2.305, Cluj
  1.742, Iași 0.774 … Teleorman 0.019. All 42 areas match on both sides; no ties
  at 3 decimals. Full table in `answers.json`.
- **Negative cases:** nearest-year denominator (the per-capita transform does this
  today); dividing by POP107A domicile; summing TUR105E/H; zero or missing
  denominator → unavailable; national row in the ranking.

## Q5 — Share and reproduce

Checklist for PA-03. No implementation was assessed.

- [ ] Live link carries dataset code(s), effective filters, period policy (`latest`
      vs fixed year) and the formula version; reopening shows the resolved period
      and the current generation id.
- [ ] Evidence bundle: result values, exact input slices (rows), query specs,
      definitions and source URLs, formula + version, rounding rule, generation id,
      INS "last updated" per source, fetch vintage, retrieval timestamp.
- [ ] Q4 recomputed from the bundle alone, offline, with identical rounding.
- [ ] A live link never claims to serve a retained snapshot.
- [ ] Single-source case (Q1) and recipe case (Q4) both exercised.

## Reproduction

```bash
source ~/devbox/envs/240826/bin/activate
G=/Users/pax/devbox/gov2/tempo-gen-20261005/data
shasum -a 256 $G/2-metas/ro/{POP105A,TUR105D,SOM103A,SOM103B,FOM106E,FOM106A}.json \
              $G/4-datasets/ro/{POP105A,TUR105D,SOM103A,SOM103B,FOM106E}.csv
# Q1: sum per area/year; compare with the raw CSV's five-year groups
duckdb -c "SELECT REF_AREA, TIME_PERIOD, SUM(OBS_VALUE) FROM '$G/corpus/parquet/POP105A_judete_grupe.parquet'
           WHERE REF_AREA IN ('Cluj','Iasi','Municipiul Bucuresti') GROUP BY ALL ORDER BY ALL"
# Q4 numerator cross-check (expect 30837328 for 2024)
duckdb -c "SELECT TIME_PERIOD, SUM(OBS_VALUE) FROM '$G/corpus/parquet/TUR105D_judete.parquet' GROUP BY 1 ORDER BY 1"
# App behaviour: TestClient on app.main with TEMPO_DATA_DIR=$G, /api/datasets/<code>/data
```
