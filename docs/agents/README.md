# Statistical Data Explorer — Sub-Agent Library

This folder contains reusable Claude Code sub-agent definitions for enriching statistical dataset metadata. They were designed for the INS TEMPO (Romanian National Statistics) explorer but are parameterized for reuse with any national statistics institute (NSI) that provides:

- A DuckDB metadata database with a `matrices` table (datasets) and a `dimensions` table
- Parquet files per dataset with numeric dimension ID columns and a `value` column
- A `dimension_options_parsed` table with semantic types (time/geo/gender/age/unit/residence/indicator)
- A `matrix_profiles` table with archetype classification per dataset

## Folder Structure

```
docs/agents/
├── README.md                      ← this file
├── pipeline.md                    ← orchestration guide (run order, dependencies, merging)
├── phase1-value-profiler.md       ← Agent 1A: statistical value profiles
├── phase1-coverage-profiler.md    ← Agent 1B: time/geo coverage and sparsity
├── phase1-trend-detector.md       ← Agent 1C: temporal trend detection
├── phase2-topic-tagger.md         ← Agent 2A: bilingual keyword tags
├── phase2-dimension-overlap.md    ← Agent 2B: cross-dataset relationships
├── phase2-chart-recommender.md    ← Agent 2C: data-driven chart recommendations
└── phase3-ia-designer.md          ← Agent 3A: information architecture spec
```

## How to Use

Each `.md` file is a **prompt template** for a Claude Code sub-agent (Bash or general-purpose type). To adapt for a new NSI project:

1. Copy the agent file
2. Replace all `{{PLACEHOLDER}}` values at the top of the file with your project specifics
3. Launch via the Task tool in Claude Code with `subagent_type: "Bash"` (or `"general-purpose"` for 3A)

## Prerequisites

Before running any agent, your database must have:

```sql
-- Required tables
matrices            -- matrix_code, matrix_name, context_code, parquet_path, row_count
dimensions          -- matrix_code, dim_column_name, option_count, dimension_id
dimension_options   -- dimension_id, nom_item_id, option_label
dimension_options_parsed  -- nom_item_id, dim_type, year, geo_level, ...
matrix_profiles     -- matrix_code, archetype, has_time, has_geo, has_gender, has_age
```

## Output Tables

After running all agents, your DB gains 6 enriched tables:

| Table | Rows | What it enables |
|---|---|---|
| `dataset_value_profiles` | 1 per dataset | Smart axis scaling, number formatting, "interesting dataset" ranking |
| `dataset_coverage` | 1 per dataset | Completeness badges, "show only datasets covering 2020+" filter |
| `dataset_trends` | 1 per dataset | Trending datasets, growth rate sorting, auto chart annotations |
| `dataset_tags` | N per dataset | Tag-based browsing, faceted search, related-by-topic |
| `dataset_relationships` | ≤10 per dataset | "Related datasets" sidebar, cross-dataset comparison |
| `dataset_chart_recs` | ≤12 per dataset | Smart chart carousel, beyond single archetype chart |

## Known Issues / Gotchas

- **DuckDB write lock**: Only one process can write at a time. Stop your dev server before running agents. The agents use a fallback pattern (write to a separate `.duckdb` file, merge when the lock is free).
- **`do` is a reserved word** in DuckDB SQL — never alias `dimension_options` as `do`. Use `dopt` instead.
- **Parallel agents hit the same write lock**: Run Phase 1 agents sequentially if they all write to the main DB, OR have them write to separate fallback files and merge at the end.
- **Metadata vs parquet ID mismatch**: The dimension_options table may list option IDs that don't appear in the actual parquet data (e.g., "Total" aggregates computed by the NSI but not stored in the download). Don't filter on these IDs for choropleth.
