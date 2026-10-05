# CLAUDE.md

Project guidance lives in AGENTS.md (shared with other coding agents) — edit it there.

@AGENTS.md

## Claude Code specifics
- The `tempo-dev` MCP tools (`mcp__tempo-dev__*`) are deferred. Load them by name
  before use, and prefer them to ad-hoc DuckDB scripts for inspecting datasets:
  `tempo_dataset_info`, `tempo_sample`, `tempo_query`, `tempo_dataset_lineage`.
  Check `tempo_pipeline_status` before touching the pipeline.
- Browser checks: `npx playwright`, or the claude-in-chrome tools against
  `http://localhost:8080`.
- `graphify-out/` (gitignored) holds a knowledge graph of the repo. `/graphify`
  can query it, but it may lag behind the code.
- No `.codegraph/` index exists here, so skip CodeGraph.
