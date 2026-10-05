# Corpus repair plan (dry run)

Data dir: `data/` (2026-10-05 snapshot; regenerate with `python scripts/repair-corpus.py --report-md … --report-json …`)

## Quarantine plan: 179 files {'leftover': 164, 'invalid': 15}

- `AMG1010_populatia_activa.parquet` rows=588 leftover: no matrices row and no dataset_splits row (name derives from registered AMG1010: likely stale split/rename)
- `AMG1010_populatia_inactiva.parquet` rows=588 leftover: no matrices row and no dataset_splits row (name derives from registered AMG1010: likely stale split/rename)
- `AMG1010_populatia_ocupata.parquet` rows=588 leftover: no matrices row and no dataset_splits row (name derives from registered AMG1010: likely stale split/rename)
- `AMG1010_rata_de_activitate_1564_ani.parquet` rows=588 leftover: no matrices row and no dataset_splits row (name derives from registered AMG1010: likely stale split/rename)
- `AMG1010_rata_de_ocupare_1564_ani.parquet` rows=588 leftover: no matrices row and no dataset_splits row (name derives from registered AMG1010: likely stale split/rename)
- `AMG1010_rata_somajului_bim.parquet` rows=588 leftover: no matrices row and no dataset_splits row (name derives from registered AMG1010: likely stale split/rename)
- `AMG1010_someri_bim.parquet` rows=588 leftover: no matrices row and no dataset_splits row (name derives from registered AMG1010: likely stale split/rename)
- `AMG155E_macroregiuni.parquet` rows=8232 leftover: no matrices row and no dataset_splits row (name derives from registered AMG155E: likely stale split/rename)
- `AMG155E_regiuni.parquet` rows=16464 leftover: no matrices row and no dataset_splits row (name derives from registered AMG155E: likely stale split/rename)
- `AMG155F_macroregiuni.parquet` rows=8232 leftover: no matrices row and no dataset_splits row (name derives from registered AMG155F: likely stale split/rename)
- `AMG155F_regiuni.parquet` rows=16464 leftover: no matrices row and no dataset_splits row (name derives from registered AMG155F: likely stale split/rename)
- `AMG156E_macroregiuni.parquet` rows=8232 leftover: no matrices row and no dataset_splits row (name derives from registered AMG156E: likely stale split/rename)
- ...

## Metadata-only matrices: 7 {'csv_never_fetched': 5, 'empty_at_source': 2}

- **ECC103B** (csv_never_fetched): metadata fetched (stage 3) but no CSV on disk and no mention in the fetch log: stage 6 never attempted/completed it (typically a matrix added after the last CSV batch)
- **EXP101F** (empty_at_source): CSV is header-only (88 bytes); fetch log reports 'Empty dataset' 8x and the retry with 'Total' options also failed. INS serves an empty export, so there is nothing to convert.
- **EXP102F** (empty_at_source): CSV is header-only (88 bytes); fetch log reports 'Empty dataset' 12x and the retry with 'Total' options also failed. INS serves an empty export, so there is nothing to convert.
- **LMV101E** (csv_never_fetched): metadata fetched (stage 3) but no CSV on disk and no mention in the fetch log: stage 6 never attempted/completed it (typically a matrix added after the last CSV batch)
- **LMV102E** (csv_never_fetched): metadata fetched (stage 3) but no CSV on disk and no mention in the fetch log: stage 6 never attempted/completed it (typically a matrix added after the last CSV batch)
- **TNZ1211** (csv_never_fetched): metadata fetched (stage 3) but no CSV on disk and no mention in the fetch log: stage 6 never attempted/completed it (typically a matrix added after the last CSV batch)
- **TPG1346** (csv_never_fetched): metadata fetched (stage 3) but no CSV on disk and no mention in the fetch log: stage 6 never attempted/completed it (typically a matrix added after the last CSV batch)

## Time misclassification: 149 served files

- `shifted_time_column/base_year_labels`: 4  e.g. CNS105A, CNS106A, FOM110A, PNS106A
- `shifted_time_column/constant_indicator_label`: 110  e.g. ECC101A, ECC102A, ECC106A, ECC107A
- `shifted_time_column/hours_worked_bands`: 24  e.g. AMG115A_anual, AMG115A_trimestrial, AMG115B_anual, AMG115B_trimestrial
- `shifted_time_column/month_names`: 2  e.g. CNF101F, CNF102C
- `shifted_time_column/other_categorical_labels`: 9  e.g. INT112A, INT112B, TCL0333_judete, TCL0333_macroregiuni

## Conflicting grain: 160 served files

- cause `county_split_dropped_locality`: 95
- cause `inherited_from_parent_source_duplicates`: 18
- cause `label_collision_in_source_options`: 32
- cause `split_dropped_other_dimension`: 15
- decision `investigate_source_do_not_deduplicate`: 50
- decision `preserve_locality_grain_or_mark_county_aggregate_unavailable`: 11
- decision `preserve_locality_grain_until_disjointness_verified`: 84
- decision `restore_dropped_dimension_or_split_finer`: 15
