# Plan: Split variant discoverability + TEC101A split

## Context
Split sub-datasets (TEC101B_euro, TEC101B_numar) exist in the `matrices` table but are invisible in practice:
- They sort to the bottom (NULL `ultima_actualizare`)
- The list search only matches `matrix_name`, not `matrix_code` — searching "TEC101B" won't find the variants
- Neither `list_datasets` nor `get_dataset` API endpoints expose the parent↔variant relationship
- TEC101A has the same UM split structure as TEC101B but hasn't been processed yet

---

## Files to Modify
- `app/routers/datasets.py` — update `list_datasets` and `get_dataset` endpoints

---

## Fix 1: `list_datasets` — add matrix_code to search + split metadata

### Search change
Add `matrix_code` to the search haystack:

```python
if q:
    where.append("(LOWER(m.matrix_name) LIKE LOWER(?) OR LOWER(m.matrix_code) LIKE LOWER(?))")
    params.extend([f"%{q}%", f"%{q}%"])
```

### Add split_count to result
Join `dataset_splits` to count variants per parent:

```sql
SELECT
    m.matrix_code,
    ...
    m.is_split,
    m.parent_matrix_code,
    COUNT(ds.sub_matrix_code) as split_count
FROM matrices m
LEFT JOIN matrix_profiles p ON m.matrix_code = p.matrix_code
LEFT JOIN dataset_splits ds ON ds.parent_matrix_code = m.matrix_code
WHERE {where_sql}
GROUP BY m.matrix_code, m.matrix_name, ...  -- all selected cols
```

Add `is_split`, `parent_matrix_code`, `split_count` to the returned dicts.

---

## Fix 2: `get_dataset` — expose variant relationships

### For parent datasets: add `splits` list
After the existing metadata fetch, query variants:

```python
splits = conn.execute("""
    SELECT sub_matrix_code, split_value, row_count, split_dimensions
    FROM dataset_splits
    WHERE parent_matrix_code = ?
    ORDER BY sub_matrix_code
""", [matrix_code]).fetchall()

split_list = [
    {"matrix_code": r[0], "label": r[1], "row_count": r[2],
     "split_dimensions": json.loads(r[3]) if r[3] else None}
    for r in splits
]
```

Include `"splits": split_list` in the return dict.

### For variant datasets: add `parent` info
```python
parent_info = None
if m_is_split:  # from the matrices row
    parent_row = conn.execute("""
        SELECT matrix_code, matrix_name FROM matrices
        WHERE matrix_code = ?
    """, [parent_matrix_code]).fetchone()
    if parent_row:
        parent_info = {"matrix_code": parent_row[0], "matrix_name": parent_row[1]}
```

Include `"parent": parent_info` in the return dict.

### Schema note
`matrices` already has `is_split` and `parent_matrix_code` columns (added by `ensure_schema`).
Fetch them in the existing `get_dataset` SELECT:
```sql
SELECT matrix_code, matrix_name, context_code, ancestor_codes,
       definitie, metodologie, ultima_actualizare, observatii,
       row_count, mat_max_dim, is_split, parent_matrix_code
FROM matrices WHERE matrix_code = ?
```

---

## Fix 3: Run splitter for TEC101A

TEC101A has the same `Unitati de masura` with multiple options as TEC101B. Run:
```bash
python 12-split-datasets.py --matrix TEC101A
```

---

## Verification

1. Start the API and check list endpoint returns split metadata:
   ```
   GET /api/datasets?q=TEC101B
   → should return TEC101B (split_count=2), TEC101B_euro, TEC101B_numar
   ```

2. Check parent dataset detail:
   ```
   GET /api/datasets/TEC101B
   → response.splits = [{matrix_code: "TEC101B_euro", ...}, {matrix_code: "TEC101B_numar", ...}]
   ```

3. Check variant dataset detail:
   ```
   GET /api/datasets/TEC101B_euro
   → response.parent = {matrix_code: "TEC101B", matrix_name: "Intreprinderi..."}
   ```

4. Verify TEC101A split:
   ```bash
   python 12-split-datasets.py --matrix TEC101A --dry-run
   ```
