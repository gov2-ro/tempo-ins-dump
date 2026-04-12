# Dataset Shape Taxonomy

Auto-generated classification of 1958 datasets into 12 chart-relevant clusters.
Use this to identify chart improvement opportunities per cluster.

## Summary

| # | Cluster | Count | % | Primary Chart | Description |
|---|---------|-------|---|---------------|-------------|
| 1 | Simple Time Series | 161 | 8.2% | line | Single indicator over time, no structural dims |
| 2 | Categorical Time | 520 | 26.6% | small_multiples / heatmap | Time + medium-cardinality categorical dim (6-50 options) |
| 3 | Composition (%) | 295 | 15.1% | area_stacked | Percentage unit, parts-of-whole over time |
| 4 | Gender-Split | 107 | 5.5% | line | Binary gender breakdown over time |
| 5 | Age Cohort | 86 | 4.4% | heatmap / grouped_bar | Age groups over time (no gender) |
| 6 | Population Pyramid | 69 | 3.5% | population_pyramid | Age + gender over time |
| 7 | Cartographic | 452 | 23.1% | choropleth | Geographic (county/region) + time, no demographic dims |
| 8 | Geo + Demographic | 135 | 6.9% | choropleth / line | Geographic + gender/age/residence |
| 9 | Urban/Rural | 84 | 4.3% | line | Residence (urban/rural) splits over time |
| 10 | Categorical Snapshot | 25 | 1.3% | grouped_bar | No time, no geo — pure categorical cross-tabs |
| 11 | Geo Snapshot | 24 | 1.2% | choropleth | Geographic, no time dimension |
| 12 | Edge Cases | 0 | 0.0% | varies | High-dimensional or rare combos |

## Exemplars per Cluster

### 1. Simple Time Series (161 datasets)
_Single indicator over time, no structural dims_

| Code | Name | Fill Rate | Rows | Trend | Screenshot |
|------|------|-----------|------|-------|------------|
| `CON107B` | Principalele agregate, pe locuitor - SEC 2010, preturi curen | 100.0% | 150 | increasing | ![CON107B](chart-taxonomy/CON107B.png) |
| `SAN107A` | Asistenta medicala de urgenta, pe elemente specifice | 100.0% | 102 | volatile | ![SAN107A](chart-taxonomy/SAN107A.png) |
| `TRN120A` | Nave de navigatie interioara, pe categorii de nave, inregist | 100.0% | 102 | volatile | ![TRN120A](chart-taxonomy/TRN120A.png) |

### 2. Categorical Time (520 datasets)
_Time + medium-cardinality categorical dim (6-50 options)_

| Code | Name | Fill Rate | Rows | Trend | Screenshot |
|------|------|-----------|------|-------|------------|
| `AGR201G` | Efectivele de porcine existente la 1 mai, pe grupe de greuta | 100.0% | 238 | volatile | ![AGR201G](chart-taxonomy/AGR201G.png) |
| `BUF101A` | ABF Bunuri de folosinta indelungata la 100 gospodarii | 100.0% | 136 | volatile | ![BUF101A](chart-taxonomy/BUF101A.png) |
| `CDP102D` | Cercetatori din activitatea cercetare-dezvoltare pe domenii  | 100.0% | 203 | volatile | ![CDP102D](chart-taxonomy/CDP102D.png) |

### 3. Composition (%) (295 datasets)
_Percentage unit, parts-of-whole over time_

| Code | Name | Fill Rate | Rows | Trend | Screenshot |
|------|------|-----------|------|-------|------------|
| `COM109B` | Indicii volumului cifrei de afaceri la nivelul sectiunii G d | 100.0% | 564 | volatile | ![COM109B](chart-taxonomy/COM109B.png) |
| `CON104R` | Produsul intern brut trimestrial - serie ajustata sezonier C | 100.0% | 3,509 | volatile | ![CON104R](chart-taxonomy/CON104R.png) |
| `CON104S` | Produsul intern brut trimestrial - serie ajustata sezonier C | 100.0% | 3,509 | volatile | ![CON104S](chart-taxonomy/CON104S.png) |

### 4. Gender-Split (107 datasets)
_Binary gender breakdown over time_

| Code | Name | Fill Rate | Rows | Trend | Screenshot |
|------|------|-----------|------|-------|------------|
| `TLR1111` | Tinta 1 - Social - Rata de supraaglomerare | 90.9% | 170 | volatile | ![TLR1111](chart-taxonomy/TLR1111.png) |
| `TIC113A` | Ponderea persoanelor de 16-74 ani care au utilizat internetu | 82.5% | 198 | volatile | ![TIC113A](chart-taxonomy/TIC113A.png) |
| `CAV103A` | Structura persoanelor de 16 ani si peste dupa opinia privind | 66.7% | 102 | volatile | ![CAV103A](chart-taxonomy/CAV103A.png) |

### 5. Age Cohort (86 datasets)
_Age groups over time (no gender)_

| Code | Name | Fill Rate | Rows | Trend | Screenshot |
|------|------|-----------|------|-------|------------|
| `AGR201E` | Efectivele de bovine existente la 1 iunie, pe grupe de varst | 100.0% | 567 | volatile | ![AGR201E](chart-taxonomy/AGR201E.png) |
| `CDP102H` | Cercetatori din activitatea de cercetare-dezvoltare pe grupe | 100.0% | 147 | volatile | ![CDP102H](chart-taxonomy/CDP102H.png) |
| `POP208F` | Decedati sub 1 an cu resedinta obisnuita in Romania pe grupe | 95.7% | 286 | decreasing | ![POP208F](chart-taxonomy/POP208F.png) |

### 6. Population Pyramid (69 datasets)
_Age + gender over time_

| Code | Name | Fill Rate | Rows | Trend | Screenshot |
|------|------|-----------|------|-------|------------|
| `TFA0494` | Tinta 9 - Social - Rata tinerilor neocupati care nu urmeaza  | 80.0% | 408 | volatile | ![TFA0494](chart-taxonomy/TFA0494.png) |
| `TLH1019` | Tinta 1 - Social - RATA TINERILOR NEOCUPATI CARE NU URMEAZA  | 80.0% | 408 | volatile | ![TLH1019](chart-taxonomy/TLH1019.png) |
| `SAR118A` | Raportul dintre chintila superioara si cea inferioara S80/S2 | 66.7% | 102 | volatile | ![SAR118A](chart-taxonomy/SAR118A.png) |

### 7. Cartographic (452 datasets)
_Geographic (county/region) + time, no demographic dims_

| Code | Name | Fill Rate | Rows | Trend | Screenshot |
|------|------|-----------|------|-------|------------|
| `LOC103B_judet` | Suprafata locuibila existenta la sfarsitul anului pe forme d | 6510.7% | 160,164 | volatile | ![LOC103B_judet](chart-taxonomy/LOC103B_judet.png) |
| `LOC101B_judet` | Locuinte existente la sfarsitul anului pe forme de proprieta | 5156.3% | 131,073 | volatile | ![LOC101B_judet](chart-taxonomy/LOC101B_judet.png) |
| `LOC104B_judet` | Locuinte terminate in cursul anului pe surse de finantare, j | 1295.7% | 54,188 | volatile | ![LOC104B_judet](chart-taxonomy/LOC104B_judet.png) |

### 8. Geo + Demographic (135 datasets)
_Geographic + gender/age/residence_

| Code | Name | Fill Rate | Rows | Trend | Screenshot |
|------|------|-----------|------|-------|------------|
| `AMG158G` | AMIGO-Rata de ocupare (20-64 ani), pe grupe de varsta si reg | 88.9% | 1,152 | volatile | ![AMG158G](chart-taxonomy/AMG158G.png) |
| `POP203C` | Rata de fertilitate pentru nascutii-vii cu resedinta obisnui | 86.4% | 3,640 | volatile | ![POP203C](chart-taxonomy/POP203C.png) |
| `TAN0131` | Tinta 3 - Mediu - Numarul de interventii ale Inspectoratului | 81.3% | 3,485 | increasing | ![TAN0131](chart-taxonomy/TAN0131.png) |

### 9. Urban/Rural (84 datasets)
_Residence (urban/rural) splits over time_

| Code | Name | Fill Rate | Rows | Trend | Screenshot |
|------|------|-----------|------|-------|------------|
| `TAV0212` | Tinta 1 - Social - PREVALENTA MALNUTRITIEI (GREUTATEA RAPORT | 70.6% | 127 | volatile | ![TAV0212](chart-taxonomy/TAV0212.png) |
| `CAV101L` | Structura gospodariilor dupa masura in care fac fata cheltui | 66.7% | 216 | volatile | ![CAV101L](chart-taxonomy/CAV101L.png) |
| `CAV102S` | Structura gospodariilor dupa numarul camerelor de locuit, pe | 66.7% | 108 | volatile | ![CAV102S](chart-taxonomy/CAV102S.png) |

### 10. Categorical Snapshot (25 datasets)
_No time, no geo — pure categorical cross-tabs_

| Code | Name | Fill Rate | Rows | Trend | Screenshot |
|------|------|-----------|------|-------|------------|
| `PPA103A_lunar_lei_buc` | Preturile medii ale principalelor produse agricole pe total  | 100.0% | 260 | decreasing | ![PPA103A_lunar_lei_buc](chart-taxonomy/PPA103A_lunar_lei_buc.png) |
| `PPA103A_anual_lei_kg` | Preturile medii ale principalelor produse agricole pe total  | 76.8% | 952 | decreasing | ![PPA103A_anual_lei_kg](chart-taxonomy/PPA103A_anual_lei_kg.png) |
| `PNS101F_trimestrial_numar_persoane` | Numarul mediu trimestrial / anual al pensionarilor pe sistem | 60.1% | 3,903 | increasing | ![PNS101F_trimestrial_numar_persoane](chart-taxonomy/PNS101F_trimestrial_numar_persoane.png) |

### 11. Geo Snapshot (24 datasets)
_Geographic, no time dimension_

| Code | Name | Fill Rate | Rows | Trend | Screenshot |
|------|------|-----------|------|-------|------------|
| `PNS101D_regiuni_anual` | Numarul mediu trimestrial / anual al pensionarilor pe tipuri | 100.0% | 560 | volatile | ![PNS101D_regiuni_anual](chart-taxonomy/PNS101D_regiuni_anual.png) |
| `PNS101D_regiuni_trimestrial` | Numarul mediu trimestrial / anual al pensionarilor pe tipuri | 100.0% | 1,808 | volatile | ![PNS101D_regiuni_trimestrial](chart-taxonomy/PNS101D_regiuni_trimestrial.png) |
| `PNS101D_macroregiuni_anual` | Numarul mediu trimestrial / anual al pensionarilor pe tipuri | 100.0% | 280 | volatile | ![PNS101D_macroregiuni_anual](chart-taxonomy/PNS101D_macroregiuni_anual.png) |

### 12. Edge Cases (0 datasets)
_High-dimensional or rare combos_

_No exemplars found._

## Gap Analysis (Visual Audit)

Findings from reviewing all 33 exemplar screenshots (2026-04-11):

### High Priority

| Cluster | Issue | Impact | Suggested Fix |
|---------|-------|--------|---------------|
| **7. Cartographic** (452, 23.1%) | Exemplars hit 50k row limit → blank chart / table fallback | Largest geo cluster renders no map | Auto-filter to latest N years; or pre-aggregate county×year totals |
| **6. Pop Pyramid** (69, 3.5%) | Renders as line chart, not population_pyramid | Chart selector not scoring pyramid type for age+gender datasets | Fix chart_selector scoring for `has_age && has_gender` archetype |
| **3. Composition %** (295, 15.1%) | Renders as line, should be area_stacked for percentage data | Parts-of-whole meaning lost without stacking | Boost area_stacked score when `primary_unit_type='percentage'` |

### Medium Priority

| Cluster | Issue | Impact | Suggested Fix |
|---------|-------|--------|---------------|
| **2. Categorical Time** (520, 26.6%) | Too many series cluttering line chart (6-50 options) | Largest cluster, currently unreadable with many lines | Add small_multiples or heatmap as default for >8 series |
| **5. Age Cohort** (86, 4.4%) | Many age-group lines overlap — hard to read | Age progression pattern invisible | Default to heatmap (age × time) or grouped_bar |
| **10. Cat Snapshot** (25, 1.3%) | Some show as line with spike instead of grouped_bar | Misleading — connects unrelated categories with line | Ensure non-time datasets get bar, not line |
| **11. Geo Snapshot** (24, 1.2%) | Shows as line chart despite having geo dim + no time | Should be static choropleth or horizontal bar | Add geo_only → choropleth path in chart_selector |

### Low Priority / Working Well

| Cluster | Status | Notes |
|---------|--------|-------|
| **1. Simple Time Series** (161) | ✓ Good | Clean line charts, legend readable |
| **4. Gender-Split** (107) | ✓ Adequate | Line with M/F series works. Could add butterfly bar as option |
| **8. Geo + Demographic** (135) | ✓ Adequate | Line chart OK for multi-dim. Choropleth + facet would be ideal |
| **9. Urban/Rural** (84) | ✓ Good | 2-3 series line works well for urban/rural comparison |

### Summary of Priorities

1. **Fix 50k limit for choropleth** — affects 452 datasets (23% of corpus)
2. **Boost area_stacked for percentage data** — affects 295 datasets (15%)
3. **Add small_multiples/heatmap for high-cardinality time** — affects 520 datasets (27%)
4. **Fix population_pyramid selection** — affects 69 datasets (4%)
5. **Fix snapshot chart types** — affects 49 datasets (2.5%)

Total datasets with suboptimal chart: **~1,386 (71%)**

---
_Generated by `scripts/chart-taxonomy.py`, gap analysis added manually_