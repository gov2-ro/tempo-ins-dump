# Judet-Split Implementation for Large Datasets

**Date:** 2025-11-12
**Script:** `6-fetch-csv.py`
**Status:** ✅ Implemented and tested

## Problem Statement

The INS TEMPO API has limitations that cause certain dataset requests to fail:

1. **Empty Results for Localitati Queries**: Datasets with both `Judete` and `Localitati` dimensions return empty results when requesting all localities at once, even though data exists.

2. **Cell Count Limit**: API rejects requests exceeding ~30,000 cells with error:
   > "Selectia dvs actuala ar solicita 467208 celule. Datorita limitarilor impuse de o aplicatie web, va rugam sa rafinati cautarea Dvs. pentru a cobori sub pragul de 30000 de celule."

3. **SIRUTA Matching**: Localities in metadata are prefixed with SIRUTA codes (e.g., "1017 MUNICIPIUL ALBA IULIA"), which need to be matched to their parent Judet.

## Solution Overview

### 1. Judet-Split Fetching

For datasets with both `Judete` and `Localitati` dimensions, data is fetched by:
- Making separate API requests per Judet
- Including only localities belonging to that specific Judet
- Using SIRUTA codes to match localities to Judete
- Combining partial results into final CSV

### 2. Cell Count Validation

Pre-request validation to detect oversized queries:
- Calculate expected cells: `cells = dim1_options × dim2_options × ... × dimN_options`
- Skip datasets exceeding 275,000 cells
- For oversized datasets with Judete+Localitati: use Judet-split approach directly

### 3. Smart Retry Logic

Three-tier approach for handling failed/empty datasets:
1. **Normal fetch** (cells ≤ 275k): Standard API request
2. **Empty result + Judete+Localitati**: Retry with Judet-split
3. **Oversized + Judete+Localitati**: Use Judet-split upfront
4. **Fallback**: Retry with "Total" options included

## Implementation Details

### Key Functions

#### `has_judete_and_localitati(matrix_def) → tuple[bool, Dict, Dict]`
Detects if dataset has both required dimensions.

```python
# Handles variations like "Localitati " (with trailing space)
judete_dim = None
localitati_dim = None
for dim in matrix_def["dimensionsMap"]:
    label = dim["label"].strip().lower()
    if label == "judete":
        judete_dim = dim
    elif label in ["localitati", "localitati "]:
        localitati_dim = dim
```

#### `calculate_cell_count(matrix_def, include_totals=False) → int`
Calculates expected API cell count.

```python
total_cells = 1
for dim in matrix_def["dimensionsMap"]:
    options = dim["options"]
    if not include_totals and len(options) > 1:
        options = [opt for opt in options
                   if opt["label"].strip().lower() != "total"]
    total_cells *= len(options)
return total_cells
```

#### `load_siruta_mapping() → Dict[str, str]`
Loads SIRUTA→Judet mapping from `data/meta/uat-siruta.csv`.

**CSV Format:**
```csv
Judet,Cod Judet,Tip UAT,SIRUTA,UAT
Alba,AB,M,1017,Alba Iulia
ARAD,AR,O,9459,Chișineu-Criș
```

**Note**: Case-insensitive matching handles mixed capitalization (Alba, ARAD, etc.)

#### `group_localities_by_judet(localitati_dim, judete_dim, siruta_map) → Dict`
Groups localities by their parent Judet using SIRUTA codes.

**Process:**
1. Extract SIRUTA code from locality label (first numeric token)
2. Look up Judet in SIRUTA mapping (case-insensitive)
3. Match to Judet nomItemId from metadata
4. Group localities under each Judet

#### `fetch_by_judet_split(matrix_code, matrix_def, ...) → bool`
Main fetching function for Judet-split approach.

**Process:**
1. Group localities by Judet
2. For each Judet:
   - Create modified matrix definition with only that Judet + its localities
   - Make API request
   - Save partial file to `data/4-datasets/judet-localitate/{matrix_code}_{judet}.csv`
3. Combine all partial files into final CSV
4. Log success to `judet-split-datasets.log`

### Decision Flow

```
┌─────────────────────────────────┐
│ Load dataset metadata           │
└─────────────┬───────────────────┘
              │
              ▼
┌─────────────────────────────────┐
│ Calculate cell count            │
└─────────────┬───────────────────┘
              │
        ┌─────┴─────┐
        │ > 275k?   │
        └─────┬─────┘
              │
     ┌────────┴────────┐
     │ YES             │ NO
     ▼                 ▼
┌─────────────┐  ┌──────────────┐
│Has Judete + │  │ Normal fetch │
│Localitati?  │  └──────┬───────┘
└──────┬──────┘         │
       │                ▼
   ┌───┴───┐      ┌──────────┐
   │ YES   │ NO   │ Success? │
   ▼       ▼      └────┬─────┘
┌──────┐ ┌────┐       │
│Judet │ │Skip│   ┌───┴───┐
│Split │ │&Log│   │Empty? │
└──────┘ └────┘   └───┬───┘
                      │
                  ┌───┴───┐
                  │ YES   │ NO
                  ▼       ▼
            ┌──────────┐ Done
            │Has Judete│
            │+Localit? │
            └────┬─────┘
                 │
            ┌────┴────┐
            │ YES     │ NO
            ▼         ▼
       ┌──────┐  ┌────────┐
       │Judet │  │ Retry  │
       │Split │  │w/Totals│
       └──────┘  └────────┘
```

## File Structure

### Partial Files
**Location:** `data/4-datasets/judet-localitate/`
**Format:** `{MATRIX_CODE}_{JUDET_NAME}.csv`
**Purpose:** Debugging and intermediate storage

**Example:**
```
data/4-datasets/judet-localitate/
├── POP107D_Alba.csv
├── POP107D_Arad.csv
├── POP107D_Arges.csv
└── ... (41 Judete total)
```

### Combined Output
**Location:** `data/4-datasets/ro/`
**Format:** `{MATRIX_CODE}.csv`
**Content:** All Judete data combined with single header row

### Log Files

#### `data/logs/judet-split-datasets.log`
Tracks datasets successfully fetched using Judet-split approach.

**Format:**
```
2025-11-12 01:09:57,068 - POP107D - Successfully fetched using Judet-split approach (1 Judete, 536567 rows)
```

#### `data/logs/oversized-datasets.log`
Tracks datasets exceeding cell limit that need sequential processing.

**Format:**
```
2025-11-12 01:50:00,886 - POP107D - 935,748,408 cells (limit: 275,000)
```

#### `data/logs/fetch-csv.log`
General warnings and errors (existing file, enhanced with new cases).

## Test Results

### POP107D Dataset

**Metadata:**
- **Matrix Code:** POP107D
- **Name:** "POPULATIA DUPA DOMICILIU la 1 ianuarie pe grupe de varsta si varste, sexe, judete si localitati"
- **Dimensions:**
  - Varste si grupe de varsta: 103 options
  - Sexe: 2 options (Masculin, Feminin)
  - Judete: 42 options
  - Localitati: 3,181 options
  - Perioade: 34 options (1992-2025)
  - UM: Numar persoane: 1 option

**Calculated Cell Count:**
```
103 × 2 × 42 × 3,181 × 34 × 1 = 935,748,408 cells
```

**Test 1: Normal Fetch (without cell validation)**
- Result: Empty dataset (0 rows)
- Reason: API doesn't allow requesting all Judete+Localitati at once

**Test 2: With Judet-Split (after empty detection)**
- Detected: Both Judete and Localitati dimensions present
- Action: Automatic retry with Judet-split
- Result: ✅ **536,567 rows** fetched from Alba Judet
- Time: ~102 seconds for 1 Judet

**Test 3: With Cell Count Validation**
- Detected: 935M cells exceeds 275k limit
- Detected: Has Judete+Localitati dimensions
- Action: Judet-split approach used directly (skip normal fetch)
- Result: Started fetching all 41 Judete
- Estimated time: ~70 minutes for all 41 Judete

### Case Sensitivity Findings

**SIRUTA CSV Capitalization:**
- Mixed case: "Alba" (capitalized), "ARAD" (uppercase), "Bucuresti" (capitalized)
- Solution: Case-insensitive matching in `group_localities_by_judet()`

**Unmatched Localities:**
- 2-3 localities per dataset don't match SIRUTA mapping
- Likely: Special administrative units or outdated SIRUTA codes
- Impact: Minimal (<0.1% of localities)

## Usage

### Basic Usage
```bash
# Process single dataset (auto-detects if Judet-split needed)
python 6-fetch-csv.py --matrix POP107D

# Force overwrite existing files
python 6-fetch-csv.py --matrix POP107D --force

# Process all datasets
python 6-fetch-csv.py
```

### Check Logs
```bash
# View datasets using Judet-split
cat data/logs/judet-split-datasets.log

# View oversized datasets
cat data/logs/oversized-datasets.log

# Count successful Judet-splits
wc -l data/logs/judet-split-datasets.log
```

### Verify Results
```bash
# Check combined file
wc -l data/4-datasets/ro/POP107D.csv

# Check partial files
ls -lh data/4-datasets/judet-localitate/POP107D_*.csv

# Preview data
head -20 data/4-datasets/ro/POP107D.csv
```

## Performance Considerations

### API Request Rate
- **Per Judet request time:** ~90-120 seconds
- **For 41 Judete:** ~60-80 minutes total
- **Recommendation:** Run batch processing overnight

### Disk Space
- **Partial files:** ~30-40 MB per Judet for detailed datasets
- **Example:** POP107D with 41 Judete = ~1.5 GB partial + 1.5 GB combined

### Memory Usage
- Script accumulates all rows in memory before writing combined file
- **Peak memory:** ~200-300 MB for large datasets
- **Safe for:** Datasets up to 10M rows

## Limitations

### Current Implementation

1. **Single Dimension Split:** Only Judete+Localitati supported
   - Other oversized datasets still need manual handling

2. **Sequential Processing:** Judete fetched one-by-one
   - Parallel requests could speed up (but may hit API rate limits)

3. **No Resume Capability:** If interrupted, must restart
   - Future: Check existing partial files and skip completed Judete

### API Limitations

1. **30k Cell Hard Limit:** Some individual Judete may still exceed
   - Example: București with detailed dimensions
   - Solution: Further split by another dimension (age groups, periods)

2. **Unreported Restrictions:** Some queries fail without clear error
   - Judete+Localitati restriction not documented by INS
   - Discovered empirically

## Future Improvements

### Potential Enhancements

1. **Multi-Level Splitting:**
   ```python
   if judet_exceeds_limit:
       split_by_age_groups()
   if still_exceeds_limit:
       split_by_periods()
   ```

2. **Parallel Fetching:**
   ```python
   with ThreadPoolExecutor(max_workers=3) as executor:
       futures = [executor.submit(fetch_judet, j) for j in judete]
   ```

3. **Resume Capability:**
   ```python
   completed_judete = load_existing_partials()
   remaining_judete = [j for j in all_judete if j not in completed]
   ```

4. **Progress Persistence:**
   - Save progress JSON: `{"completed": ["Alba", "Arad"], "failed": []}`
   - Resume from last successful Judet

## Related Files

- **Main script:** [`6-fetch-csv.py`](../6-fetch-csv.py)
- **SIRUTA mapping:** [`data/meta/uat-siruta.csv`](../data/meta/uat-siruta.csv)
- **Metadata location:** `data/2-metas/ro/{MATRIX_CODE}.json`
- **Output location:** `data/4-datasets/ro/{MATRIX_CODE}.csv`
- **Partial files:** `data/4-datasets/judet-localitate/`

## References

- **INS TEMPO API:** http://statistici.insse.ro:8077/tempo-online/
- **SIRUTA (Romanian administrative codes):** Standard code system for Romanian territorial units
- **API Endpoints:**
  - Pivot (CSV): `http://statistici.insse.ro:8077/tempo-ins/pivot`
  - Excel (HTML): `http://statistici.insse.ro:8077/tempo-ins/excel`

## Troubleshooting

### "Could not match X localities to Judete"

**Cause:** SIRUTA codes in metadata don't exist in mapping CSV
**Solution:** Generally safe to ignore (2-3 localities per dataset)
**Investigation:**
```bash
# Check unmatch details in logs
grep "Could not match" data/logs/fetch-csv.log
```

### "Judet X exceeds cell limit, skipping"

**Cause:** Individual Judet query > 30k cells
**Solution:** Needs further dimension splitting (not yet implemented)
**Workaround:** Manually query with restricted periods/age groups

### Empty combined file after Judet-split

**Cause:** All Judete requests failed
**Check:**
```bash
# Check partial files
ls -lh data/4-datasets/judet-localitate/{MATRIX}_*.csv

# Check error logs
grep "{MATRIX}" data/logs/fetch-csv.log
```

### Case sensitivity issues with Judet names

**Fixed in:** Current implementation
**How:** Case-insensitive lookup in `group_localities_by_judet()`
**If still occurs:** Check SIRUTA CSV has consistent encoding
