# Dataset notes and decisions

Generated from `app/data/dataset_notes.json` by `scripts/build-notes-report.py`;
edit the JSON, not this file. Public notes are shown on the dataset pages.
How totals, averages and rates are computed: [METHODOLOGY](../METHODOLOGY.md).

## To take up with INS

- **POP105A-census-break** (`POP105A`): Is a back-calculation of 2012–2021 on the 2021 census basis planned, so the county series can be compared across the break?  
  Context: The series breaks between 2021 and 2022: estimates up to 2021 rest on the 2011 census, from 2022 on the 2021 census. The drop between the two years reflects the change of base, not only population change.
- **pivot-header-only-large-dims** (`EXP101F`, `EXP102F`): Is there a documented option limit for /tempo-ins/pivot? An empty CSV is indistinguishable from an empty dataset.  
  Context: The TEMPO pivot API answers with a header-only CSV when a dimension has over 1,000 selected options; the data was fetched in chunks.
- **metadata-stale-periods** (`EXP102F`): Is the matrix metadata (period list, ultimaActualizare) guaranteed to be updated together with the data?  
  Context: The matrix metadata lagged behind the data: its period list ended in 2024 while INS already published newer data.

## Source issues (ours or INS's)

- **locality-fetch-bucharest** (`AGR101B`, `AGR108B`, `AGR109B`, `AGR112B`, `AGR115B`, `AGR201B`, `AGR202B`, `ART101B` and 61 more): Bucharest's rows were missing from the locality-level downloads (our fetch error, not INS's): the SIRUTA file says 'Bucuresti', INS says 'Municipiul Bucuresti'. New or merged localities were lost the same way. Fixed and re-fetched on 2026-10-12. Evidence: Generation tempo-gen-20261012: all 69 now have Bucharest rows; 53 also gained localities the SIRUTA file cannot place (fetched against every county). Summed KPI checks for these datasets: 36 mismatches became matches.
- **pivot-header-only-large-dims** (`EXP101F`, `EXP102F`): The TEMPO pivot API answers with a header-only CSV when a dimension has over 1,000 selected options; the data was fetched in chunks. Evidence: FIX-03 repair, 2026-10-05: EXP101F/EXP102F checked cell by cell against the website export.
- **metadata-stale-periods** (`EXP102F`): The matrix metadata lagged behind the data: its period list ended in 2024 while INS already published newer data. Evidence: FIX-03 repair, 2026-10-05.

## Decisions

- **POP105A-census-break** [series_break] (`POP105A`): The series breaks between 2021 and 2022: estimates up to 2021 rest on the 2011 census, from 2022 on the 2021 census. The drop between the two years reflects the change of base, not only population change. Decided by owner, 2026-10-12 (PA-00 Q1).
- **POP105A-revisions** [provisional] (`POP105A`): Data up to 2023 is final; 2024 is revised, and 2025–2026 may still be revised by INS. Decided by owner, 2026-10-12 (PA-00 Q1).
- **FOM106E-classification** [series_break] (`FOM106E`, `FOM106A`): FOM106E starts in 2008 and uses the CAEN Rev.2 classification; years up to 2007 are in FOM106A, on CAEN Rev.1. The two series are not joined: the activities do not map one to one. Decided by owner, 2026-10-12 (PA-00 Q2).
- **FOM106E-annual-vs-monthly** [definition] (`FOM106E`): The monthly average from the annual survey includes back pay, so it differs from the average earnings in INS's monthly releases. Decided by owner, 2026-10-12 (PA-00 Q2).
- **FOM106E-tax-facilities** [caveat] (`FOM106E`): Between 2019 and 2024 some categories of employees had tax and contribution relief. Their net earnings are closer to gross, which affects comparisons between activities and counties. Decided by owner, 2026-10-12 (PA-00 Q2).
- **FOM106E-SOM103A-published-totals** [decision] (`FOM106E`, `SOM103A`): Our download lacks the Total rows (all activities × both sexes in FOM106E; both sexes in SOM103A). INS's published totals, fetched separately, are served; the weighted reconstruction stays as a cross-check (it differs by at most one unit, from rounding). Decided by owner, 2026-10-12 (PA-00 Q2/Q3).
- **SOM103A-registered-not-ilo** [definition] (`SOM103A`, `SOM103B`): Registered unemployment rate: unemployed people registered with the employment agencies (ANOFM) relative to the civilian active population. It is not the ILO unemployment rate from the labour force survey. Decided by owner, 2026-10-12 (PA-00 Q3).
- **TUR105D-coverage** [coverage] (`TUR105D`, `TUR105E`, `TUR105H`): Covers only accommodation establishments with at least 5 bed-places; Romanian and foreign tourists. Decided by owner, 2026-10-12 (PA-00 Q4).
- **TUR105EH-county-split** [excluded] (`TUR105E_judet`, `TUR105H_judet`): This county set lost its locality column in processing, so a county appears once per locality. Its values cannot be added up per county, and the set is not used for the stays-per-resident indicator. The problem is ours, not INS's, and is queued for repair. Decided by owner, 2026-10-12 (PA-00 Q4).
- **locality-fetch-bucharest** [source_issue] (`AGR101B`, `AGR108B`, `AGR109B`, `AGR112B`, `AGR115B`, `AGR201B`, `AGR202B`, `ART101B` and 61 more): Bucharest's rows were missing from the locality-level downloads (our fetch error, not INS's): the SIRUTA file says 'Bucuresti', INS says 'Municipiul Bucuresti'. New or merged localities were lost the same way. Fixed and re-fetched on 2026-10-12. Decided by owner, 2026-10-12 (re-fetch of the 69 affected matrices).
- **totals-not-in-download** [decision] (`FOM106E`, `SOM103A`, `POP105A`, `TUR105D`): Our download omits the 'Total' options; the totals shown are computed (exact sums for counts) or fetched separately from INS (means and rates). See docs/METHODOLOGY.md. Decided by owner, 2026-10-12.

## All notes by kind

### definition

| Note | Datasets | Public | Text (en) |
|---|---|---|---|
| FOM106E-annual-vs-monthly | `FOM106E` | yes | The monthly average from the annual survey includes back pay, so it differs from the average earnings in INS's monthly releases. |
| SOM103A-registered-not-ilo | `SOM103A`, `SOM103B` | yes | Registered unemployment rate: unemployed people registered with the employment agencies (ANOFM) relative to the civilian active population. It is not the ILO unemployment rate from the labour force survey. |

### coverage

| Note | Datasets | Public | Text (en) |
|---|---|---|---|
| TUR105D-coverage | `TUR105D`, `TUR105E`, `TUR105H` | yes | Covers only accommodation establishments with at least 5 bed-places; Romanian and foreign tourists. |

### series_break

| Note | Datasets | Public | Text (en) |
|---|---|---|---|
| POP105A-census-break | `POP105A` | yes | The series breaks between 2021 and 2022: estimates up to 2021 rest on the 2011 census, from 2022 on the 2021 census. The drop between the two years reflects the change of base, not only population change. |
| FOM106E-classification | `FOM106E`, `FOM106A` | yes | FOM106E starts in 2008 and uses the CAEN Rev.2 classification; years up to 2007 are in FOM106A, on CAEN Rev.1. The two series are not joined: the activities do not map one to one. |
| SOM103A-bucharest-sai | `SOM103A` | yes | For 1991–1996 INS gives Bucharest twice: 'Municipiul Bucuresti' and 'Mun. Bucuresti - incl. SAI' (including the Ilfov Agricultural Sector). Ilfov county appears separately from 1997. Comparisons across that boundary are not on the same territory. |
| TUR105D-rented-rooms | `TUR105D` | yes | From 2021 the data also includes rented apartments and rooms (2021–2022 were revised). Comparisons with earlier years are not on the same coverage. |

### provisional

| Note | Datasets | Public | Text (en) |
|---|---|---|---|
| POP105A-revisions | `POP105A` | yes | Data up to 2023 is final; 2024 is revised, and 2025–2026 may still be revised by INS. |

### caveat

| Note | Datasets | Public | Text (en) |
|---|---|---|---|
| POP105A-single-ages | `POP105A_judete_varste`, `POP105A_regiuni_varste`, `POP105A_macroregiuni_varste` | yes | This set has single years of age from 0 to 84, without the 85-and-over group. Its sum is not the total population; use the age-group set for totals. |
| FOM106E-tax-facilities | `FOM106E` | yes | Between 2019 and 2024 some categories of employees had tax and contribution relief. Their net earnings are closer to gross, which affects comparisons between activities and counties. |
| SOM101B-women-only | `SOM101B` | yes | The set covers women only (the source has just the Total and Feminin options). Do not use it as the total number of unemployed. |

### excluded

| Note | Datasets | Public | Text (en) |
|---|---|---|---|
| TUR105EH-county-split | `TUR105E_judet`, `TUR105H_judet` | yes | This county set lost its locality column in processing, so a county appears once per locality. Its values cannot be added up per county, and the set is not used for the stays-per-resident indicator. The problem is ours, not INS's, and is queued for repair. |

### decision

| Note | Datasets | Public | Text (en) |
|---|---|---|---|
| FOM106E-SOM103A-published-totals | `FOM106E`, `SOM103A` | no | Our download lacks the Total rows (all activities × both sexes in FOM106E; both sexes in SOM103A). INS's published totals, fetched separately, are served; the weighted reconstruction stays as a cross-check (it differs by at most one unit, from rounding). |
| totals-not-in-download | `FOM106E`, `SOM103A`, `POP105A`, `TUR105D` | no | Our download omits the 'Total' options; the totals shown are computed (exact sums for counts) or fetched separately from INS (means and rates). See docs/METHODOLOGY.md. |

### source_issue

| Note | Datasets | Public | Text (en) |
|---|---|---|---|
| locality-fetch-bucharest | `AGR101B`, `AGR108B`, `AGR109B`, `AGR112B` and 65 more | no | Bucharest's rows were missing from the locality-level downloads (our fetch error, not INS's): the SIRUTA file says 'Bucuresti', INS says 'Municipiul Bucuresti'. New or merged localities were lost the same way. Fixed and re-fetched on 2026-10-12. |
| pivot-header-only-large-dims | `EXP101F`, `EXP102F` | no | The TEMPO pivot API answers with a header-only CSV when a dimension has over 1,000 selected options; the data was fetched in chunks. |
| metadata-stale-periods | `EXP102F` | no | The matrix metadata lagged behind the data: its period list ended in 2024 while INS already published newer data. |
