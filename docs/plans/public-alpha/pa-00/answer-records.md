# PA-00 answer records, Q1–Q5

Version 2, 2026-10-12, generation `c307f28a8c7b…` (copy `tempo-gen-20261012`,
POP105A/SOM103A/TUR105D refreshed from INS; see [refresh](#refreshed-generation-2026-10-12)).
Re-pinned 2026-10-15 to generation `9b3e065d2fe9…` (same copy, POP107D/POP108D re-fetched
with Bucharest, per-dimension INS checks loaded). Q1–Q4 keep their values: no source
of theirs was re-fetched (POP105A, `published_totals`, TUR105D), and the Q4 answer test
passes on the new generation.
Version 1 (2026-10-11) was recorded on generation `a6737a263a34…` (see [baseline](baseline.md));
sections below that cite 2024 as the latest year describe v1.
Machine-readable expectations: [answers.json](answers.json).

**Q1–Q4 are `verified`** (owner review, 2026-10-12; see
[Review decisions](#review-decisions-2026-10-12)). Q2 and Q3 are served from INS's
own Total cells, with the reconstruction as a cross-check.

| Q | Status | Blocker / next step |
|---|---|---|
| Q1 population | **`verified`** (2026-10-12) | Equal to INS in all 645 area-years 2012–2026. Presentation requirements below |
| Q2 net earnings | **`verified`** (2026-10-12) | INS's Total cells (`published_totals`). 2024: Cluj 5,921, Iași 5,098, Bucharest 6,730, national 4,959 |
| Q3 unemployment | **`verified`** (2026-10-12) | INS's Total cells. 2025: Teleorman 9.3 (rank 1), Iași 3.4, Cluj 1.5, Bucharest 0.5, national 3.3 |
| Q4 tourism intensity | **`verified`** (2026-10-12) | Latest year **2025**; 2 decimals; coverage in the label; TUR105E/H exclusion approved |
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

Spec: [reference-cells.json](reference-cells.json). Run on 2026-10-12 (INS was
offline on 2026-10-11):

```bash
python scripts/fetch-ins-reference-cells.py --spec docs/plans/public-alpha/pa-00/reference-cells.json \
  --meta-dir $G/2-metas/ro --out /Users/pax/devbox/gov2/tempo-gen-20261005/reports/pa00-reference-cells
```

## Reconstruction from data already downloaded (2026-10-11)

Q2 and Q3 lack INS's published total cell, but the corpus holds the weights INS
itself uses. Both now run as reviewed recipes (`/api/recipes/{id}`, evidence ZIP
with an offline `recompute.py`): `net_earnings_county` (kind `weighted_mean`) and
`registered_unemployment_county` (kind `rate_from_counts`).

| Question | Method | Check | County results 2024 (candidate) |
|---|---|---|---|
| Q2 net earnings | Σ(earnings × average employees) / Σ employees over CAEN **sections** (A–S, not divisions or INDUSTRIE) × both sexes, joining FOM106E_judete with FOM104F_judete (same breakdown) | national 2024: **4,959.2** vs INS TOTAL 4,959 lei (retained cell); 42/42 areas | Cluj 5,921; Iași 5,097; Bucharest 6,730 (the unweighted mean the app refuses would say 5,522 / 4,880 / 6,890) |
| Q3 registered unemployment | rate = 100 × ΣU / Σ(U / rate_sex). U by sex = year-end registered unemployed from **SOM101E** (December, summed over localities); rates from SOM103A_judete. The active population by sex is recovered as U / rate. | Rebuilding the **regional** rates by sex from the counties reproduces the published SOM103A regional cells to rounding for 2022–2024 (every region except București-Ilfov men, below). SOM101E women's counts equal SOM101B's to within 6 people nationally, so year-end counts are SOM103A's numerator. Every county result lies between its two sex rates. 41/42 areas | Cluj 1.43; Iași 3.61; Teleorman 9.58 (rank 1); **Bucharest excluded**: SOM101E has no Bucharest rows in our fetch, so only the range 0.6–0.7 is known. The place page shows 1.5 / 3.6 / 0.6 from the unweighted mean. |

**Correction (same day):** an earlier draft of this table gave Q3 = 3.30 %
nationally, with Cluj 1.6 and Teleorman 8.3, from SOM101B_judete. SOM101B carries
**women only** (its options are Total and Feminin, and the fetch dropped Total).
Those figures were the women's rate, not the both-sexes rate. The national
both-sexes 3.3 % cannot be checked from downloaded data without Bucharest.

The INS reference cells (next section) settle Bucharest's Q3 value and check both
reconstructions by county. Rounding limits the reconstructions:
earnings are published in whole lei, and rates to 0.1. A sex's recovered active
population is U / rate, so its error is up to ±0.05 / rate (±8 % at 0.6 %). That
moves a county's both-sexes rate only within its two sex rates. The recipes are
labelled "reconstituit" and carry these checks as tests
(`tests/test_pa03_recipe_kinds.py`).

## Review decisions (2026-10-12)

Owner review of v2. "Verified" means the definition, scope and presentation were
approved and every expected value equals an independent INS cell.

- **Q1 — verified.** Resident population (POP105A, usual residence ≥ 12 months),
  not domicile (POP107A). "Cluj" is the county, never Cluj-Napoca. Required in the
  presentation: mark the 2021→2022 break as a change of census basis (2011 → 2021),
  not population loss; label 2025–2026 as not final (INS: data before 2024 is final,
  2024 is revised, later years may still change).
- **Q2 — definition approved; use INS values.** Average net monthly earnings from the
  annual survey (FOM106E), nominal lei, latest 2024; includes back pay, so it differs
  from the monthly release. Do not join FOM106A (CAEN Rev.1, to 2007) with FOM106E
  (Rev.2, from 2008). Notes to carry on the dataset: series start and classification,
  annual vs monthly, 2019–2024 tax facilities for some employee groups.
- **Q3 — definition approved; use INS values.** Registered unemployment (ANOFM), not
  the ILO rate; SOM103A annual, latest 2025; 41 counties + Bucharest, one decimal,
  ties by name, changes in percentage points.
- **Q4 — verified.** Display **2 decimals** (2025 has two display ties, 1.79 and 0.70;
  ranks follow the unrounded values). The label states the coverage: structures with
  at least 5 bed-places, Romanian and foreign tourists. Excluding TUR105E_judet and
  TUR105H_judet is approved. Their conflict is ours, not INS's: the county split
  drops the locality column, so a county-year repeats once per locality (FIX-03 queue).
- **Served (2026-10-12):** `published_totals` holds INS's Total cells for FOM106E and
  SOM103A at every level (2,854 cells); they equal the independently fetched
  reference cells in all 2,230 shared cells. Recipes v2 serve them; place pages show
  them with an "INS" badge, and country/region baselines come from INS's own cells.
- **Decision log for INS.** Every note above is recorded per dataset in
  `app/data/dataset_notes.json`; `docs/reports/ins-notes.md` lists them, with the
  points to raise with INS.

## INS reference cells (2026-10-12)

Four requests, all `labels_ok`, no blank cells. Evidence directory
`tempo-gen-20261005/reports/pa00-reference-cells/`: the CSVs, `manifest.json`
(payload, fetch time, sha256), INS's current matrix metadata
(`ins-metadata-2026-10-12/`), and `compare_pa00.py` → `compare.json`.

| Cells | sha256 |
|---|---|
| `POP105A-total-counties-2012-2025.csv` (602) | `46fd2812c136407a34b73469b36b1e835a643ad6fe945c331dc0b885f2d805b5` |
| `FOM106E-total-counties-2008-2024.csv` (731) | `595d88ac9b0e8e77907f026a402b6ccf5789197d5ad95e1a0acec75ce22f49f2` |
| `SOM103A-total-counties-1991-2024.csv` (1,456) | `3fd7eb2ac9f2ec0469d63b865b9fc21b86cab225970dd7351b0b0d36b20d81f0` |
| `TUR105D-total-counties-2012-2024.csv` (559) | `a3d8442508e43ad487e60959d5b00c150d5af5f6e531081eb2acd53d5b616096` |

| Check | Result |
|---|---|
| Q1 POP105A, summed partition vs INS Total, 43 areas | 2012–2023: **516/516 equal**. 2024: 43 differ (−321…+309). 2025: 43 differ (national −7,120). INS's county cells sum to its national cell in every year |
| Q4 TUR105D, summed partition vs INS Total | **559/559 equal**, 2012–2024 |
| Q4 2024 ratio, INS cells on both sides | Same ranking for 42 areas; max difference 0.0005. At 3 decimals: Vâlcea 4.263, Caraș-Severin 2.709, Bucharest 2.306, Harghita 1.818, Cluj 1.743, Maramureș 1.390 |
| Q2 `net_earnings_county` vs INS Total, 2008–2024 | all 714 within ±1.2 lei; **649/714** equal once rounded to whole lei. 2024 misses: Iași (5,097 vs 5,098), Bistrița-Năsăud, Satu Mare, Botoșani, Teleorman, Dolj (all ±1) |
| Q3 `registered_unemployment_county` vs INS Total-sex rate, 2010–2024 | all 615 within ±0.09 pp; **512/615** equal once rounded to 0.1. 10 misses in 2024 (e.g. Dolj 8.7 vs 8.8, Ilfov 0.3 vs 0.4), so the reconstructed ranking order differs from INS's. INS publishes 1991–2024; the recipe covers 2010–2024 only (SOM101E) |

**Why Q1 2024–2025 differ: a source revision, not a corpus defect.** INS's
current POP105A metadata says last updated **10-09-2026**; our export is the
02-09-2025 version. INS now publishes 1 January 2026 and revised 2024 and 2025.
The 2025 national gap (19,036,031 vs 19,043,151) is that revision. Earlier years
are unchanged.

**The generation is behind INS for three of the four sources.** Current INS
metadata (2026-10-12) vs retained:

| Matrix | Retained `ultimaActualizare` | INS now | New periods |
|---|---|---|---|
| POP105A | 02-09-2025 | 10-09-2026 | 1 Jan 2026; 2024–2025 revised |
| SOM103A | 15-10-2025 | 09-02-2026 | 2025 |
| TUR105D | 02-04-2025 | 08-04-2026 | 2025 |
| FOM106E | 04-09-2025 | 04-09-2025 | none |

**What this means for the records.** Q2 and Q3 reconstructions are close but are
not INS's published statistic: the rounded value differs in 9 % (Q2) and 17 % (Q3)
of cells, and a ranking question is sensitive to that. INS publishes the exact
cell. Owner decisions:
1. **Refresh** POP105A, SOM103A and TUR105D — **done 2026-10-12**, see below.
2. **Serve INS's Total cells** — **decided 2026-10-12** for Q2/Q3 (keep "Total" options at fetch for these
   matrices, or register the reference cells as a reviewed source) and keep the
   reconstructions as cross-checks. Either way is a FIX-03-style corpus change.

**Why a reconstructed total can differ from INS's although both start from "the
same data".** They don't start from the same data. INS computes its Total from
unrounded survey figures; we only have its *published* parts, each rounded (whole
lei; 0.1 pp). A count total is unaffected: counts are published exactly and add up,
so Q1/Q4 sums equal INS to the person. A mean or a rate is a weighted average of its
parts. Each rounded part is off by ≤0.5 lei (≤0.05 pp), so our weighted average is
off by ≤0.5 from INS's unrounded total, and INS then rounds that total by up to 0.5
more: up to 1 lei (0.1 pp) apart, and a different last digit whenever the true value
sits near a rounding boundary. Observed: Q3 always within that bound; Q2 within it
except 2 of 714 cells (≤1.14 lei, Botoșani and Galați 2020), where FOM104F's employee
counts are slightly different weights from INS's own.

## Refreshed generation (2026-10-12)

Copy `~/devbox/gov2/tempo-gen-20261012/data`, an APFS clone of `tempo-gen-20261005`
with only POP105A, SOM103A and TUR105D refreshed (metadata + CSV from INS, stages B–D
for the 3 parents and 12 children), generation `c307f28a8c7b…` (after the
published totals, the children's re-profiling and the re-fetch of 69 locality-level
matrices that lacked Bucharest). Not published. Q1–Q4 values are unchanged by the
re-fetch; the Q3 reconstruction now covers Bucharest (2024: 0.654 vs INS 0.7).

- **Source diff:** POP105A 25,832 cells revised (2024–2025 only), 22,042 new (2026);
  SOM103A +108 cells (2025); TUR105D +1,086 (2025). No other cell changed or vanished.
- **Corpus diff:** exactly the 15 touched parquet files and their view profiles; same
  children, columns and split rules; 0 unmatched labels; audit unchanged (160
  conflicting-grain files, as before). DB rows changed only for those 15 codes (plus
  the new `Anul 2026` time code).
- **Global profilers:** `11-coverage-profiler.py`, `profile-values.py` and
  `detect_trends.py` rewrite every dataset. Their rows for untouched datasets were
  restored from the source generation, and `dataset_coverage` was kept whole (its
  profiler cannot read SDMX geo values) with POP105A's row counts updated.
  `generate_view_profiles.py --matrix` gives split children a different, wrong
  profile, so the full generator ran to a side folder: identical for every untouched
  dataset; the 15 touched profiles were copied in.
- **KPI total gate:** re-checked against INS for the touched datasets: POP105A
  `_grupe` 2026 = 19,041,322, exact match; `_varste` still `mismatch` (ages stop at 84).
- **Against the reference cells** (re-fetched with the extended ranges into
  `tempo-gen-20261012/reports/pa00-reference-cells/`): Q1 645/645 equal, Q4
  numerator 602/602 equal, Q4 2024 ratio now identical to INS-cell ratios.
- **Latest answers (candidate):** Q1 Cluj 1 Jan 2026 **701,564** (Iași 781,948,
  Bucharest 1,713,832). Q4 2025: Constanța 8.475, Brașov 4.911, Vâlcea 4.252,
  Covasna 3.036, Caraș-Severin 2.662 … Bucharest 2.441, Cluj 1.789, Iași 0.739.
  Q3 2025 (INS): Cluj 1.5, Iași 3.4, Bucharest 0.5, national 3.3. Q2 unchanged (FOM106E
  still ends in 2024).
- Corpus tests (51) pass on this generation; the Q4 record test skips on the old one.

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

- **Identity:** Q1 v2, **`verified`**, owner, 2026-10-12.
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
  sexes, both residence types; Bucharest has no rural rows). **INS Total cells
  (2026-10-12):** equal for every area 2012–2023. 2024–2025 differ because INS
  revised them on 10-09-2026 (Cluj 2024 693,413, 2025 697,374; Iași 778,694 /
  780,271; Bucharest 1,721,475 / 1,709,191). Tolerance for counts: 0, so 2024–2025
  need a POP105A refresh.
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

- **Identity:** Q2 v2, **`verified`**, owner, 2026-10-12; served from INS's Total cells.
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
- **INS Total cells (2026-10-12):** 2024 Cluj **5,921**, Iași **5,098**,
  Bucharest **6,730**, national 4,959. The recipe gives 5,921 / 5,097 / 6,730.
- **Unblock:** decide whether to serve INS's Total cells (see
  [INS reference cells](#ins-reference-cells-2026-10-12)), then approve the record.
- **Negative cases:** gross vs net; averaging divisions; mixing FOM106A Rev.1 with
  FOM106E Rev.2 across 2008; a county with a missing year.

## Q3 — Registered unemployment ranking

- **Identity:** Q3 v2, **`verified`**, owner, 2026-10-12; served from INS's Total cells.
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
- **INS Total-sex cells (2026-10-12), 2024:** Teleorman 9.6, Vaslui 9.2, Dolj 8.8,
  Mehedinți 8.5, Suceava 6.6 … Timiș 1.1, Bucharest **0.7**, Ilfov 0.4. Cluj 1.4,
  Iași 3.6, national 3.3. INS now also has 2025.
- **Unblock:** decide whether to serve INS's Total cells, then rank 42 areas,
  percent with one decimal as published, ties broken by area name, changes in
  percentage points.
- **Negative cases:** BIM rate; an unweighted sex average; ranking each county's
  own latest month; correlation on a constant axis.

## Q4 — Tourism intensity

- **Identity:** Q4 v2, **`verified`**, owner, 2026-10-12. **Feasibility: feasible.** PA-03 may plan
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
  **INS county cells (2026-10-12):** numerator equals INS in all 559 county-year
  cells 2012–2024. Denominator: as Q1 (2024 revised by INS; the ranking is
  unchanged, 6 areas move by 0.001).
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
