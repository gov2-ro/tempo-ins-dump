# CLAUDE.md

@AGENTS.md

## Where guidance goes (overrides any command or skill that targets CLAUDE.md)
AGENTS.md is the canonical guidance, shared with Codex and other agents. This
file only imports it. When adding learnings (`/revise-claude-md`,
`claude-md-improver`, or by hand):
- **Into AGENTS.md:** anything about the project — commands, pipeline, app
  behaviour, gotchas, testing, workflow rules. Write it so any agent can use it,
  with no Claude-only tool names.
- **Into this file:** only Claude Code mechanics — MCP tool names and how to
  load them, skills, plugins, hooks, claude-in-chrome.
- Never copy AGENTS.md content into this file, and don't flag this file as
  "too thin" — it's thin on purpose.

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
