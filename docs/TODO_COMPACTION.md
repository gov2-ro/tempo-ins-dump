# TODO: Fix Compacted Dataset Issues

## Current Status

**Using**: Original CSVs from `data/4-datasets/ro/` (text labels)
**Not Using**: Compacted CSVs from `data/5-compact-datasets/ro/` (numeric IDs)

## The Problem

The `7-data-compactor.py` script successfully compacts **some** datasets but fails on many others due to label mismatches between CSV data and JSON metadata.

### Example Issue: ACC101C

**CSV Data** (data/4-datasets/ro/ACC101C.csv):
```csv
CAEN Rev.2, Perioade, UM: Numar, Valoare
A  AGRICULTURA  SILVICULTURA SI PESCUIT, Anul 2008, Numar, 4
```

**JSON Metadata** (data/2-metas/ro/ACC101C.json):
```json
{
  "dimensionsMap": [{
    "label": "CAEN Rev.2",
    "options": [
      {"label": "A  AGRICULTURA, SILVICULTURA SI PESCUIT", "nomItemId": 23416}
    ]
  }]
}
```

**Mismatch**:
- CSV: `"A  AGRICULTURA  SILVICULTURA SI PESCUIT"` (no comma)
- JSON: `"A  AGRICULTURA, SILVICULTURA SI PESCUIT"` (comma after AGRICULTURA)

After normalization (`.strip().lower()`), these don't match, so the compactor leaves the text unchanged and logs a warning.

### Result

The compacted file contains **mixed data types**:
```csv
CAEN Rev.2, Perioade, UM: Numar, Valoare
A  AGRICULTURA  SILVICULTURA SI PESCUIT,4589,9669,4  ← TEXT, ID, ID, number
```

This causes Parquet conversion to fail when trying to cast to INTEGER.

## Root Cause

**Data quality issue from the INS source** - inconsistent formatting between:
- CSV downloads (raw data export)
- JSON metadata API (structured data)

## Impact

- ~40-50% of datasets failed to compact properly
- Files that worked: ACC101B, ADM101A, many AGR* files
- Files that failed: ACC101C, ACC102A, ACC102B, AED* files, AGR108A, etc.

## Potential Solutions

### Option 1: Improved Label Normalization (Recommended)

Enhance the matching logic in `7-data-compactor.py` to be more fuzzy:

```python
def normalize_label(label):
    """
    Aggressive normalization for matching CSV to JSON labels

    Rules:
    - Remove ALL punctuation (commas, periods, hyphens, etc.)
    - Collapse multiple spaces to single space
    - Lowercase
    - Trim whitespace
    """
    # Remove all non-alphanumeric except spaces
    label = re.sub(r'[^a-z0-9\s]', '', label.lower())
    # Collapse multiple spaces
    label = re.sub(r'\s+', ' ', label)
    return label.strip()
```

This would normalize both:
- `"A  AGRICULTURA  SILVICULTURA SI PESCUIT"`
- `"A  AGRICULTURA, SILVICULTURA SI PESCUIT"`

To the same string: `"a agricultura silvicultura si pescuit"`

### Option 2: Fix Source Data

Contact INS or write a script to clean up the CSV exports to match the JSON metadata exactly. (Not practical)

### Option 3: Use IDs from JSON

Instead of trying to match labels, reconstruct the data using:
1. The order of rows in the CSV
2. The dimension structure from JSON
3. Assuming rows follow the dimension order

This is risky and could corrupt data if assumptions are wrong.

## Benefits of Fixing Compaction

If we successfully compact all datasets to use numeric IDs:

- **Storage**: ~50% smaller Parquet files (integers vs text)
- **Query Performance**: Faster joins on integers vs text
- **Consistency**: All data in same format
- **Bandwidth**: Smaller files = faster transfers

## Current Workaround

Using original CSVs (`data/4-datasets/ro/`) with text labels:
- ✅ 100% reliability - all files work
- ✅ No data quality issues
- ✅ Simple and deterministic
- ❌ Larger Parquet files (~2x size)
- ❌ Slower queries (text comparison vs integer)

## Next Steps

1. Test Option 1 (improved normalization) on failed datasets
2. Verify no data corruption occurs
3. Re-run compaction with enhanced matching
4. Validate compacted files have 100% numeric IDs
5. Update Parquet conversion to use compacted files
6. Compare file sizes and query performance

## Related Files

- `7-data-compactor.py` - Compaction script to fix
- `data/5-compact-datasets/ro-compaction.log` - Compaction log with warnings
- `9-csv-to-parquet.py` - Currently uses original CSVs
- `duckdb_config.py` - CSV_SOURCE_DIR setting

## Success Metrics

A successful fix would achieve:
- [ ] 100% of datasets compacted (1,888/1,888)
- [ ] No mixed data types in compacted files
- [ ] All Parquet conversions succeed
- [ ] File size reduction of ~40-60%
- [ ] Query performance improvement of ~2-5x on joins
