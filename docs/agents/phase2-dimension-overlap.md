# Agent 2B: Dimension Overlap Mapper

**Type:** `Bash`
**Phase:** 2 (independent of Phase 1 — only needs existing metadata tables)
**Output table:** `dataset_relationships`
**Runtime:** ~30 seconds for 1,886 datasets (18,880 relationships)

## What it does

Finds related datasets by comparing their dimension-type fingerprints. Avoids the O(N²) = 3.5M pairwise trap by grouping: only compares datasets within the same L2 context, plus datasets that share identical dim-type fingerprints across contexts. Stores top 10 relationships per dataset. Enables:
- "Related datasets" sidebar on dataset detail page
- Cross-dataset comparison feature
- "Same topic, different breakdown" discovery

## Output Schema

```sql
CREATE TABLE dataset_relationships (
    matrix_a          VARCHAR,  -- composite PK
    matrix_b          VARCHAR,  -- composite PK
    shared_dim_types  VARCHAR,  -- JSON: e.g., ["geo", "time", "unit"]
    shared_dim_count  INTEGER,
    same_context      BOOLEAN,  -- same L2 context_code
    relationship_type VARCHAR,  -- 'same_topic' | 'same_structure' | 'complementary'
    similarity_score  DOUBLE    -- 0-1
)
```

**Relationship type rules:**
- `same_topic`: `same_context = TRUE` AND `shared_dim_count >= 2`
- `same_structure`: `same_context = FALSE` AND identical dim-type fingerprint (same set of types)
- `complementary`: otherwise (different context, partial overlap)

**Similarity score:** `shared_dim_count / max_dim_count_of_either` + 0.125 bonus if `same_context`

## Scalability Strategy

Full N² = 1,886² / 2 ≈ 1.78M pairs — too slow. Instead:

1. **Within-context pairs**: Group datasets by their L2 `context_code`. Compare all pairs within each context group. Most groups are small (2-10 datasets). Total: ~88K pairs.
2. **Same-fingerprint pairs**: Group datasets by their dim-type fingerprint (e.g., `"geo,indicator,time,unit"`). Compare across context groups. Total: ~371K pairs.
3. **Combined**: ~459K pairs, takes ~15 seconds.
4. **Deduplicate** and keep top 10 per dataset by similarity_score DESC.

## Prompt Template

```
You are Agent 2B: Dimension Overlap Mapper.

**Environment:**
- Activate: `source {{VENV_PATH}}/bin/activate`
- Working dir: `{{PROJECT_DIR}}`
- DuckDB: `{{DB_PATH}}`

**DB Schema:**
- `matrices` — matrix_code, context_code
- `dimensions` — matrix_code, dimension_id
- `dimension_options` — dimension_id, nom_item_id
- `dimension_options_parsed` — nom_item_id, dim_type

**Task:**
Write a Python script (heredoc) and run it. Steps:

1. Connect to {{DB_PATH}} read-write.
   Try main DB; if locked, write to fallback `{{PROJECT_DIR}}/data/dataset_relationships.duckdb`.

2. DROP TABLE IF EXISTS dataset_relationships; CREATE:
   matrix_a VARCHAR, matrix_b VARCHAR, shared_dim_types VARCHAR,
   shared_dim_count INTEGER, same_context BOOLEAN, relationship_type VARCHAR,
   similarity_score DOUBLE
   PRIMARY KEY (matrix_a, matrix_b)

3. Pre-load dim-type fingerprints:
   SELECT d.matrix_code, dop.dim_type
   FROM dimensions d
   JOIN dimension_options dopt ON dopt.dimension_id = d.dimension_id
   JOIN dimension_options_parsed dop ON dop.nom_item_id = dopt.nom_item_id
   GROUP BY d.matrix_code, dop.dim_type
   (Never alias dimension_options as "do" — reserved SQL word. Use "dopt".)
   → dict: {matrix_code → frozenset of dim_types}

4. Pre-load context_code per matrix:
   → dict: {matrix_code → context_code}

5. Build candidate pairs using TWO grouping strategies:
   a. Within-context: for each context_code, get all datasets in it.
      Generate all pairwise combinations within the group.
   b. Same-fingerprint: for each unique frozenset, get all datasets with that fingerprint.
      Generate all pairwise combinations (limit to fingerprints with <= 200 datasets to avoid explosion).
   Combine candidate pairs, deduplicate (always store as (min(a,b), max(a,b)) canonical form).

6. For each candidate pair (a, b):
   fp_a = fingerprints[a], fp_b = fingerprints[b]
   shared = fp_a & fp_b
   shared_dim_count = len(shared)
   if shared_dim_count == 0: skip
   same_ctx = context[a] == context[b]
   max_dims = max(len(fp_a), len(fp_b))
   score = shared_dim_count / max_dims + (0.125 if same_ctx else 0)
   score = min(score, 1.0)
   relationship_type:
     if same_ctx and shared_dim_count >= 2: 'same_topic'
     elif fp_a == fp_b: 'same_structure'
     else: 'complementary'
   Keep pair if score >= 0.3

7. Keep top 10 per dataset by similarity_score DESC:
   Build {matrix_code → [top 10 partners]} dict.
   Collect all unique pairs from top-10 lists.
   Insert only those pairs (not all candidates).

8. Insert records. Print progress every 10,000 pairs.

9. Print summary:
   - Total relationships
   - Distribution by relationship_type
   - Average similarity_score
   - Top 5 most-connected datasets (highest number of relationships)
   - Sample: relationships for matrix_code='{{SAMPLE_MATRIX_CODE}}'
```

## Adaptation Notes

- **Context grouping depth**: This agent uses L2 context (direct parent of dataset). If your NSI has a shallow hierarchy (2 levels), use L1. If very deep (5+ levels), L3 might be better to avoid overly small groups.
- **Fingerprint explosion**: Some fingerprints like `{time, unit}` may match hundreds of datasets. The `<= 200` limit prevents generating millions of pairs from a single large fingerprint group. Adjust based on your dataset count and runtime tolerance.
- **Top-N limit**: 10 relationships per dataset is suitable for a sidebar. Increase to 20 for a dedicated "compare" feature.
- **Minimum similarity**: The 0.3 threshold filters out weak associations. Lower to 0.2 to include more distant relationships; raise to 0.5 for tighter connections only.
- **Parallel write conflict**: Agent 2B may run concurrently with 2A and 2C. If they all try to write to the same DuckDB, use the fallback pattern. Agent 2B handles this by checking for `duckdb.IOException` and falling back to `data/dataset_relationships.duckdb`.
