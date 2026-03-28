# Phase 8: Strip Aggregate/Total Rows from Parquet

## Problem

~13% of canonical parquet files contain pre-computed aggregate rows that duplicate the detail data. When a chart shows "all genders" it sums Male + Female + Total, producing 2x the real value.

### Common patterns

| Dim type | Total values | Datasets affected |
|---|---|---|
| geo | `TOTAL`, `Nivel National` | ~520 |
| gender | `Total`, `Total persoane` | ~230 |
| age | `Total`, `Total persoane`, `Toate varstele` | ~160 |
| residence | `Total` (Urban + Rural) | ~200 |
| indicator | `Salariati - total`, `Industrie - total`, etc. | ~100 (tricky) |

### The hard part

Not every value containing "total" is an aggregate:
- `Total fructe` is an indicator name, not a sum
- `Cheltuieli totale de consum` is a measured variable
- `Suprafata totala amenajata` is just a label
- Some "totals" are weighted averages or indices, not simple sums

## Approach: Interactive Detection Script

### `scripts/detect-totals.py`

**Phase A: Automated detection** (high confidence)
1. For each parquet file, identify dimension columns (exclude TIME_PERIOD, OBS_VALUE)
2. For each dimension column, check if any value matches known total patterns:
   - Exact: `Total`, `TOTAL`, `Nivel National`, `Toate varstele`, `Ambele sexe`
   - Prefix: `Total persoane`, `Total ...` (when dim_type is age/gender/residence)
3. **Validation heuristic**: For candidate total values, check if `OBS_VALUE` is approximately equal to the sum of the other values for the same time period and remaining dimension combination. If sum matches within 5% tolerance, it's a confirmed aggregate.

**Phase B: Interactive confirmation** (medium/low confidence)
1. For candidates where the sum doesn't match (weighted averages, rates, etc.), prompt the user with:
   - The dimension column and candidate value
   - Sample rows showing the candidate value vs others
   - The sum-check result
2. User confirms: `y` (strip), `n` (keep), `s` (skip dataset)
3. Save decisions to `data/logs/total-decisions.json` for reproducibility

**Phase C: Apply**
1. Modify `12-parquet-to-sdmx.py` to read decisions file
2. When generating parquet, add WHERE clause to exclude confirmed total rows
3. Re-run parquet generation for affected datasets only

### Decision file format

```json
{
  "POP105A": {
    "SEX": {"Total": "strip", "reason": "sum_match"},
    "RESIDENCE": {"Total": "strip", "reason": "sum_match"},
    "AGE": {"Total persoane": "strip", "reason": "sum_match"}
  },
  "FPC104D": {
    "ECON_ACTIVITY": {"Industrie - total": "keep", "reason": "user_confirmed_not_aggregate"}
  }
}
```

### Keyword dictionary (starting point)

```python
# High confidence — strip without asking if sum-check passes
KNOWN_TOTALS = {
    'geo':       ['TOTAL', 'Total', 'Nivel National'],
    'gender':    ['Total', 'Total persoane', 'Ambele sexe'],
    'age':       ['Total', 'Total persoane', 'Toate varstele', 'Toate grupele de varsta'],
    'residence': ['Total', 'Urban + Rural', 'Urban+Rural'],
}

# Medium confidence — always ask
MAYBE_TOTALS_RE = r'(?i)^total\b|(?i)\btotal$|(?i)\btoate\b'
```

## Integration with parquet pipeline

Option A (preferred): Add a `--strip-totals` flag to `12-parquet-to-sdmx.py` that reads the decisions file and adds exclusion WHERE clauses during parquet generation.

Option B: Separate script `scripts/strip-totals-from-parquet.py` that reads existing parquets, filters, and overwrites. Simpler but doesn't integrate with the pipeline.

## Scope

- All 3,632 canonical parquets
- Expect ~400-500 datasets to have rows stripped
- Typical reduction: 5-15% fewer rows per affected dataset
- No metadata changes needed (dimension_options still lists all options for reference)

## Timing

Can be done anytime — parquet regeneration is the only expensive step. Benefits from having the UI available to visually verify results. Recommended: after the SDMX UI framework is functional enough to spot-check datasets.
