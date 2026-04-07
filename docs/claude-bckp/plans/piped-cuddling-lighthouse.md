# Plan: Sub-split mixed-age-granularity datasets

## Context

Datasets like `POP107D_localitate` have an age dimension (`varste_si_grupe_de_varsta_nom_id`) that combines two distinct granularities:
- **Single-year ages**: "0 ani", "1 ani", ..., "84 ani", "85 ani si peste" (84 options)
- **5-year age groups**: "0-4 ani", "5-9 ani", ..., "80-84 ani" (18 options)

Both co-exist in the same parquet column, making the filter dropdown confusing (103 values mixed alphabetically). These are intentional INS overlapping granularities — not a data error.

**Affected datasets** (10 parent datasets, 4 already-split hierarchy variants):
- `POP105A`, `POP106A`, `POP107A`, `POP107D`, `POP108B`, `POP108D`, `POP111A`, `POP112A`, `POP320A`, `POP321A`
- Plus already-split: `POP107D_judet`, `POP107D_localitate`, `POP108D_judet`, `POP108D_localitate`

The split is determined by `dimension_options_parsed`: `age_min == age_max` (and not total) → single year; `age_min != age_max` and not `(0, 999)` → group.

## Approach

Add a new **Pattern E: `age_granularity`** to `split_rules.py` that detects datasets with mixed age granularity and emits two groups:
- `grupe` — 5-year group options (`age_min != age_max`, excluding total `(0,999)`)
- `varste` — single-year options (`age_min == age_max`, excluding `age_min=0` total)

The "Total" age option (`age_min=0, age_max=999`) gets duplicated into both groups (consistent with how slash_dims handles "other" items).

**Key constraint:** For already-split hierarchy variants (`POP107D_judet`, `POP107D_localitate`), the age sub-split should apply to those sub-datasets as well, not just the parent. The hierarchy split runs first; age granularity runs second. Since `12-split-datasets.py` rebuilds all splits from scratch on each run, the age sub-split needs to handle parquet-v3 sources too — or be applied as a post-processing step.

**Simpler alternative:** Apply age sub-split only to parent datasets. The `_judet`/`_localitate` variants will not be age-sub-split (they remain large but at least the parent dataset gets clean variants). This avoids 3-level nesting complexity.

→ **Go with simpler approach**: age sub-split applies to parent datasets only. Users who want grouped ages on locality data can first select a `POP107D_grupe` then additionally filter.

## Changes

### 1. `split_rules.py` — add `detect_age_granularity()`

```python
def detect_age_granularity(conn) -> list[SplitRule]:
    """Pattern E: Age dimension with both single-year and grouped options."""
    rows = conn.execute("""
        WITH age_dims AS (
            SELECT d.matrix_code, d.dimension_id, d.dim_column_name
            FROM dimensions d
            WHERE (LOWER(d.dim_label) LIKE '%varst%' OR LOWER(d.dim_label) LIKE '%grupe%')
              AND NOT (d.matrix_code LIKE '%_judet' OR d.matrix_code LIKE '%_localitate'
                       OR d.matrix_code LIKE '%_grupe' OR d.matrix_code LIKE '%_varste')
        ),
        age_options AS (
            SELECT ad.matrix_code, ad.dimension_id, ad.dim_column_name,
                   dopt.nom_item_id, dopt.option_label,
                   dop.age_min, dop.age_max
            FROM age_dims ad
            JOIN dimension_options dopt ON dopt.dimension_id = ad.dimension_id
            JOIN dimension_options_parsed dop ON dop.nom_item_id = dopt.nom_item_id
            WHERE dop.dim_type = 'age' AND dop.age_min IS NOT NULL
        ),
        mixed AS (
            SELECT matrix_code, dimension_id, dim_column_name,
                   COUNT(CASE WHEN age_min = age_max AND age_min > 0 THEN 1 END) as singles,
                   COUNT(CASE WHEN age_min != age_max AND NOT (age_min=0 AND age_max=999) THEN 1 END) as groups
            FROM age_options
            GROUP BY matrix_code, dimension_id, dim_column_name
        )
        SELECT ao.matrix_code, ao.dimension_id, ao.dim_column_name,
               ao.nom_item_id, ao.option_label, ao.age_min, ao.age_max
        FROM age_options ao
        JOIN mixed m ON m.matrix_code = ao.matrix_code AND m.dimension_id = ao.dimension_id
        WHERE m.singles > 0 AND m.groups > 0
        ORDER BY ao.matrix_code, ao.age_min, ao.age_max
    """).fetchall()

    from collections import defaultdict
    by_matrix = defaultdict(list)
    for r in rows:
        by_matrix[(r[0], r[1], r[2])].append(r)

    rules = []
    for (mc, dim_id, dim_col), opts in by_matrix.items():
        grupe_ids, grupe_labels = [], {}
        varste_ids, varste_labels = [], {}
        total_ids, total_labels = [], {}

        for r in opts:
            oid, olabel, age_min, age_max = r[3], r[4], r[5], r[6]
            if age_min == 0 and age_max == 999:
                total_ids.append(oid); total_labels[oid] = olabel
            elif age_min == age_max:
                varste_ids.append(oid); varste_labels[oid] = olabel
            else:
                grupe_ids.append(oid); grupe_labels[oid] = olabel

        # Add totals to both groups
        for oid, olabel in total_labels.items():
            grupe_ids.append(oid); grupe_labels[oid] = olabel
            varste_ids.append(oid); varste_labels[oid] = olabel

        groups = [
            SplitGroup(label="grupe", option_ids=grupe_ids, option_labels=grupe_labels),
            SplitGroup(label="varste", option_ids=varste_ids, option_labels=varste_labels),
        ]
        rules.append(SplitRule(
            matrix_code=mc,
            pattern="age_granularity",
            split_dimension=dim_col,
            split_dimension_id=dim_id,
            groups=groups,
        ))

    logger.info(f"Pattern E (age_granularity): {len(rules)} datasets")
    return rules
```

Call it from `detect_all()`:
```python
age_gran = detect_age_granularity(conn)
all_rules = multi_um + mixed_metrics + slash_dims + hierarchy + age_gran
```

### 2. `12-split-datasets.py` — add `age_granularity` to argparse choices

```python
parser.add_argument("--pattern", choices=["multi_um", "mixed_metrics", "slash_dims", "hierarchy", "age_granularity"], ...)
```

No other changes to `12-split-datasets.py` — `split_parquet_by_filter` already handles filter-by-option-id splits generically (non-hierarchy path, lines 140–160).

## Files

- `split_rules.py` — add `detect_age_granularity()`, call from `detect_all()`
- `12-split-datasets.py` — add `age_granularity` to `--pattern` choices (line ~368)

## Verification

```bash
source ~/devbox/envs/240826/bin/activate
python 12-split-datasets.py --dry-run --pattern age_granularity
# Should show 10 datasets, 2 groups each

python 12-split-datasets.py --pattern age_granularity
# Creates parquet-v3/ro/POP107D_grupe.parquet, POP107D_varste.parquet, etc.

python -c "
import duckdb; conn = duckdb.connect()
r = conn.execute(\"SELECT DISTINCT varste_si_grupe_de_varsta_nom_id FROM 'data/parquet-v3/ro/POP107D_grupe.parquet' LIMIT 5\").fetchall()
print('grupe:', r)
r = conn.execute(\"SELECT DISTINCT varste_si_grupe_de_varsta_nom_id FROM 'data/parquet-v3/ro/POP107D_varste.parquet' LIMIT 5\").fetchall()
print('varste:', r)
"
# grupe: should show only '0-4 ani', '5-9 ani', etc.
# varste: should show only '0 ani', '1 ani', etc.
```
