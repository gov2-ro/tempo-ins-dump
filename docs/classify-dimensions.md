# Dimension Classification & Normalization

**Script:** `10-classify-dimensions.py`
**Database:** `data/tempo_metadata.duckdb`
**Run time:** ~10 seconds for all 1,888 datasets

---

## What It Does

The INS corpus stores all dimension values as raw Romanian text: `"Anul 2009"`, `"MACROREGIUNEA UNU"`, `"Masculin"`, `"Procente"`, `"18-24 ani"`. This script batch-processes every dimension option across all datasets and:

1. **Classifies** each dimension into a semantic type (`time`, `geo`, `gender`, `age`, `residence`, `unit`, `indicator`)
2. **Parses** each option label into structured fields (year, quarter, geo_level, etc.)
3. **Profiles** each dataset into an archetype (`time_series`, `geo_time`, `demographic`, etc.)
4. Writes results to two new DuckDB tables — no raw string parsing needed at query time

---

## Usage

```bash
source ~/devbox/envs/240826/bin/activate

# Process all datasets (fast, ~10s)
python 10-classify-dimensions.py

# Test a single dataset with verbose output
python 10-classify-dimensions.py --matrix ACC101B --debug

# Useful for inspecting unknowns
python 10-classify-dimensions.py --debug 2>&1 | grep 'conf=0'
```

---

## Output Tables

### `dimension_options_parsed`

One row per unique `nom_item_id` (18,203 rows from 325,762 option occurrences).

| Column | Type | Description |
|---|---|---|
| `nom_item_id` | INTEGER PK | Globally unique option ID from INS |
| `dim_type` | TEXT | `time` \| `geo` \| `gender` \| `age` \| `residence` \| `unit` \| `indicator` |
| `year` | INTEGER | Extracted year (time dims only) |
| `quarter` | INTEGER | 1–4 (quarterly datasets) |
| `month` | INTEGER | 1–12 (monthly datasets) |
| `semester` | INTEGER | 1–2 |
| `time_granularity` | TEXT | `annual` \| `quarterly` \| `monthly` \| `semester` \| `other` |
| `geo_level` | TEXT | `national` \| `macroregion` \| `region` \| `county` \| `locality` \| `residence` \| `unknown` |
| `siruta_code` | INTEGER | SIRUTA locality code (locality-level rows only) |
| `geo_name_clean` | TEXT | Cleaned geographic name |
| `gender` | TEXT | `male` \| `female` \| `total` \| `unknown` |
| `age_min` | INTEGER | Lower bound (999 = no upper limit) |
| `age_max` | INTEGER | Upper bound |
| `unit_type` | TEXT | `percentage` \| `count` \| `currency` \| `area` \| `weight` \| `energy` \| `index` \| `rate` \| `distance` \| `time_unit` \| `other` |
| `unit_scale` | INTEGER | Multiplier: 1, 1000, 1,000,000 |
| `currency` | TEXT | `RON` \| `EUR` \| `USD` \| NULL |
| `parse_confidence` | REAL | 0.0–1.0 |
| `raw_label` | TEXT | Original label (for debugging) |

**Example queries:**

```sql
-- All time options parsed from "Anul YYYY"
SELECT raw_label, year, time_granularity
FROM dimension_options_parsed
WHERE dim_type = 'time' AND time_granularity = 'annual'
LIMIT 10;

-- Quarterly options
SELECT raw_label, year, quarter
FROM dimension_options_parsed
WHERE quarter IS NOT NULL
ORDER BY year, quarter;

-- County-level geo options
SELECT raw_label, geo_level, geo_name_clean
FROM dimension_options_parsed
WHERE geo_level = 'county'
LIMIT 20;

-- Unit types and their scales
SELECT unit_type, unit_scale, currency, COUNT(*) as n
FROM dimension_options_parsed
WHERE dim_type = 'unit'
GROUP BY 1, 2, 3
ORDER BY n DESC;
```

---

### `matrix_profiles`

One row per dataset (1,888 rows).

| Column | Type | Description |
|---|---|---|
| `matrix_code` | TEXT PK | Dataset identifier (e.g. `ACC101B`) |
| `has_time` | BOOLEAN | Has a time dimension |
| `time_granularity` | TEXT | Dominant granularity (`annual` / `quarterly` / `monthly` / `mixed`) |
| `time_year_min` | INTEGER | Earliest year in dataset |
| `time_year_max` | INTEGER | Latest year in dataset |
| `has_geo` | BOOLEAN | Has a geographic dimension |
| `geo_levels` | TEXT | JSON array, e.g. `["county","national","region"]` |
| `has_gender` | BOOLEAN | Has a gender dimension |
| `has_age` | BOOLEAN | Has an age group dimension |
| `has_residence` | BOOLEAN | Has an urban/rural dimension |
| `unit_types` | TEXT | JSON array of unit types |
| `primary_unit_type` | TEXT | Most common unit type |
| `dim_count` | INTEGER | Number of dimensions |
| `archetype` | TEXT | Dataset archetype (see below) |
| `parse_coverage` | REAL | Fraction of options parsed with confidence ≥ 0.8 |

**Example queries:**

```sql
-- Archetype distribution
SELECT archetype, COUNT(*) as n
FROM matrix_profiles
GROUP BY archetype
ORDER BY n DESC;

-- Quarterly datasets spanning multiple decades
SELECT matrix_code, time_year_min, time_year_max
FROM matrix_profiles
WHERE time_granularity = 'quarterly'
ORDER BY (time_year_max - time_year_min) DESC
LIMIT 10;

-- Datasets with both geo and gender breakdowns
SELECT matrix_code, geo_levels, has_gender, has_age
FROM matrix_profiles
WHERE has_geo AND (has_gender OR has_age)
LIMIT 20;
```

---

## Normalization Recipes

### Time (`"Perioade"` dimension)

| Raw label | year | quarter | month | granularity |
|---|---|---|---|---|
| `Anul 2009` | 2009 | — | — | annual |
| `Trimestrul I 2022` | 2022 | 1 | — | quarterly |
| `Trimestrul IV 2020` | 2020 | 4 | — | quarterly |
| `Semestrul II 2018` | 2018 | — | — | semester |
| `Luna ianuarie 2021` | 2021 | — | 1 | monthly |
| `Luna 3 2021` | 2021 | — | 3 | monthly |
| `2015` | 2015 | — | — | annual |

Dimension detected by label containing: `perioade`, `trimestre`, `semestre`, `luni calendaristice`, `ani`.

### Geography

Detection hierarchy (first match wins):

| Label pattern | `geo_level` |
|---|---|
| `TOTAL`, `Romania`, `Nivel National` | `national` |
| Starts with `MACROREGIUNEA` | `macroregion` |
| Starts with `Regiunea` | `region` |
| Matches 42-county name list (diacritic-normalized) | `county` |
| `Municipiul Bucuresti` variants | `county` |
| 4–6 leading digits + name (SIRUTA) | `locality` |
| Contains `urban` / `rural` | `residence` |

Dimension detected by label containing: `macroregiuni`, `regiuni`, `judete`, `localitati`, `municipii`, `orase`, `comune`, `tari`.

### Gender (`"Sexe"` dimension)

| Raw label | `gender` |
|---|---|
| Masculin / Barbati / Baieti | `male` |
| Feminin / Femei / Fete | `female` |
| Sex necunoscut | `unknown` |
| Total / Ambele sexe | `total` |

### Age (`"Varste si grupe de varsta"` dimension)

| Raw label | age_min | age_max |
|---|---|---|
| `15-24 ani` | 15 | 24 |
| `65 ani si peste` | 65 | 999 |
| `sub 1 an` | 0 | 0 |
| `Total` | 0 | 999 |

### Residence (`"Medii de rezidenta"` dimension)

Maps `Urban` / `Mediul urban` → `urban`, `Rural` / `Mediul rural` → `rural`.

### Unit of Measure (`"UM: ..."` dimension)

Key mappings:

| Raw label | `unit_type` | `unit_scale` | `currency` |
|---|---|---|---|
| Procente / % | percentage | 1 | — |
| Numar / Persoane | count | 1 | — |
| Mii / Mii persoane | count | 1,000 | — |
| Lei | currency | 1 | RON |
| Mii lei | currency | 1,000 | RON |
| Euro / Mii euro | currency | 1 / 1,000 | EUR |
| Hectare | area | 1 | — |
| Tone / Mii tone | weight | 1 / 1,000 | — |
| Indici | index | 1 | — |

---

## Results (as of last run)

**325,762** option rows fetched → **18,203** unique IDs parsed

### Archetype distribution

| Archetype | Count | Description |
|---|---|---|
| `time_series` | 976 | Time + thematic categorical dims |
| `geo_time` | 566 | Time + Romanian geography |
| `demographic` | 262 | Time + gender and/or age |
| `time_residence` | 84 | Time + urban/rural |

### Parse confidence

Virtually all time, geo (Romanian), gender, age, and unit options parse at **confidence 1.0**. Indicators (`dim_type = indicator`) are domain-specific and intentionally left unparsed — they're used as filter/pivot axes rather than numeric axes.

---

## Known Gaps & Next Steps

### 1. Extend unit labels (easy, ~30 min)

69 unknown unit labels, all rare (1–2 occurrences each). Run with `--debug` to see them, then add to `UNIT_MAP` in `10-classify-dimensions.py`:

```python
'kilograme':              ('weight',  1,       None),
'litri':                  ('volume',  1,       None),
'bucati':                 ('count',   1,       None),
'mii pasageri':           ('count',   1_000,   None),
'mii metri cubi':         ('volume',  1_000,   None),
'metri patrati':          ('area',    1,       None),
'mii ore':                ('time_unit', 1_000, None),
# ... etc
```

After adding, re-run `python 10-classify-dimensions.py` to refresh the tables.

### 2. Add `country` geo_level (medium, ~1–2 hours)

410 unknown geo labels are foreign country names (Franta, Germania, Italia, Austria, etc.) — these come from international trade and emigration datasets. Currently assigned `geo_level = unknown`.

Fix: add a country name list to `parse_geo()` and return `geo_level = 'country'` + ISO 3166-1 alpha-2 code. A lookup table of ~60 Romanian-language country names covers the bulk of cases.

### 3. Build visualization layer (next major phase)

With the parsed tables in place, each dataset now has a machine-readable profile. The next step is to add a chart tab to `duckdb-browser.py`:

- **`time_series`** datasets → line chart (x=year, y=value, series=indicator categories)
- **`geo_time`** datasets → regional bar chart or choropleth (grouped by geo_level)
- **`demographic`** datasets → grouped bar chart (x=year, y=value, color=gender or age group)

The key query pattern for any chart:

```sql
SELECT
    p_time.year,
    p_time.quarter,
    p_geo.geo_name_clean,
    p_geo.geo_level,
    p_gender.gender,
    data.value
FROM 'data/parquet/ro/ACC101B.parquet' data
JOIN dimension_options_parsed p_time
    ON data.perioade_nom_id = p_time.nom_item_id
JOIN dimension_options_parsed p_geo
    ON data.macroregiuni_..._nom_id = p_geo.nom_item_id
WHERE p_geo.geo_level = 'county'
  AND p_time.year BETWEEN 2010 AND 2023
ORDER BY p_time.year, p_geo.geo_name_clean;
```

This replaces all ad-hoc `REPLACE(label, 'Anul ', '')` gymnastics with a clean join.
