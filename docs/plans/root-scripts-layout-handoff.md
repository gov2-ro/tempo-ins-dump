# Handoff: move the root-level scripts into subfolders

Written 2026-10-18. A move, not a rewrite: no behaviour change, no renumbering. Paste the prompt
below into a new session, or tell it: "Implement docs/plans/root-scripts-layout-handoff.md".

```text
Reorganise the root-level Python scripts of tempo-ins-dump into subfolders and update every
path that refers to them. A move, not a rewrite: no behaviour change, no renumbering.

## 0. Preconditions — check each, stop and report if any fails
1. The main checkout (~/devbox/gov2/tempo-ins-dump) is clean: `git status --short` shows nothing
   tracked as modified. In particular the edits that were pending there on 2026-10-18
   (docs/BACKLOG.md, docs/activity-history.md, readme.md, LICENSE.txt) are committed, and the old
   untracked docs/plans/ copy is gone or moved out of the repo.
2. `main` contains `fix/ask-answer-quality` and `fix/03-corpus-repair`:
   `git merge-base --is-ancestor fix/ask-answer-quality main && git merge-base --is-ancestor fix/03-corpus-repair main`.
3. The merged worktrees are removed: `git worktree list` shows only the main checkout (and
   any worktree the owner deliberately kept). `git branch --no-merged main` lists no branch whose
   commits touch a root `.py`. If one does, stop and report. Never reset/clean/stash other worktrees.
Then: create a NEW branch `chore/root-scripts-layout` from up-to-date `main` in its own worktree
(e.g. `git worktree add ../tempo-layout -b chore/root-scripts-layout main`). Read AGENTS.md
(canonical guidance) and readme.md before anything else.

## 1. Target layout (propose adjustments before moving; ask if unsure)
- `pipeline/`: active stage scripts with their CURRENT filenames:
  1-fetch-context, 2-fetch-matrices, 3-fetch-metas, 4-build-meta-index, 6-fetch-csv,
  8-setup-duckdb-schema, 9-csv-to-parquet, 10-import-metadata, 10-classify-dimensions,
  11-build-sdmx-codes, 11-coverage-profiler, 12-split-datasets, 13-dimension-structure,
  detect_trends, generate_view_profiles, build-geo-regions, generate_sdmx_yaml, get-news,
  update-pipeline.
- Shared modules duckdb_config, sdmx_labels, split_rules: choose ONE import strategy and justify
  it (a package such as `pipeline/lib/` or `tempo_pipeline/`, or importable via the pipeline
  folder). app/, scripts/, tests/ and tools/ import them (~23 files for duckdb_config): find them
  all with grep; don't guess.
- `pipeline/legacy/`: 5-varstats-db, 7-data-compactor, 10-sdmx-export, 12-parquet-to-sdmx
  (deprecated: never run against the corpus).
- `tools/duckdb-browser.py`; `test_chart_selector.py` → `scripts/` (a report, not a test; pytest
  must not collect it).
- Root keeps project files only: readme, AGENTS.md, CLAUDE.md, Dockerfile, fly.toml,
  requirements*, pytest.ini, llms.txt, LICENSE.

## 2. Known path hazards (each needs explicit handling and a test or a check)
- `duckdb_config.BASE_DIR = Path(__file__).parent`: moving it moves the default data dir. The
  default must still resolve to `<repo>/data`; `TEMPO_DATA_DIR` and `TEMPO_PIPELINE_DATA_DIR`
  keep working unchanged.
- `update-pipeline.py` runs children by bare filename (`python_rc("6-fetch-csv.py", …)`,
  `cwd=data_dir().parent`). Resolve scripts relative to the orchestrator file, not the cwd.
- `6-fetch-csv.py` resolves `data/` from the cwd; `3-fetch-metas.py` writes the repo's
  `data/2-metas` regardless of env. After the move they must write exactly where they did before.
  A wrong relative path could create a stray `data/` or touch the live corpus.
- Hyphenated scripts are loaded by file path in tests/tools (importlib spec_from_file_location /
  runpy: tests/fix03b_env.py, test_fix03b_orchestrator.py, test_split_dry_run.py,
  test_fix03_audit.py, test_fix03_fetch_chunks.py, test_pa01_grain_guard.py, …). Update all.
- Other callers: scripts/ (release-check.py, prepare-deploy-data.sh, check-kpi-totals.py,
  build-static.py, …), tools/tempo-dev-mcp (pipeline status, lineage), .github/workflows/ci.yml,
  Dockerfile (copies only app/: confirm the app has no root import).
- Docs: AGENTS.md (pipeline table, commands, gotchas), readme.md, docs/CURRENT_STATE.md,
  docs/DEPLOY-STATIC.md and the active plans/specs. Do NOT rewrite dated history
  (docs/activity-history.md entries, completed records, docs/fixes/ evidence); add one dated note
  "scripts moved to pipeline/ on <date>". Count `grep -rlE "[0-9]+-[a-z-]+\.py"` before/after.
- Outside git: `.mcp.json` (gitignored, absolute paths) may point at moved files. Report what
  must change; don't edit it unless asked. No crontab entries exist for this repo.

## 3. Execution
- Phase 1 (own commit): legacy/deprecated + duckdb-browser + test_chart_selector; refs; tests.
- Phase 2 (own commit): active pipeline + shared modules + orchestrator script table + callers.
- `git mv` only (history follows); no code changes beyond paths/imports. No root compatibility
  shims unless you argue for a short transition and the owner agrees.
- One writer at a time: stop any dev server first. Never run pipeline scripts against
  `data/corpus/metadata.duckdb`. Several profilers rebuild whole tables without `--matrix`;
  `11-build-sdmx-codes.py` without `--matrix` destroys mappings. Read each argparse block; don't
  probe with --help.

## 4. Acceptance (record every command and result)
- `source ~/devbox/envs/240826/bin/activate`; `python -m pytest tests -q` passes, both synthetic
  and with `TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-gen-20261012/data` (read-only copy).
  Compare counts with main before the move; explain any change.
- `python pipeline/update-pipeline.py --matrix ACC101B --dry-run` gives the same plan as before
  (diff outputs before/after).
- One real single-matrix run on a COPY: copy the generation to a scratch dir, set
  `TEMPO_PIPELINE_DATA_DIR=<copy>/data`, run stages 9 → 12 → 13 for one small matrix through the
  orchestrator; prove nothing outside the copy changed (mtimes/hashes of live data/ and repo tree).
- `python scripts/release-check.py` (no --deploy) and the static parity tests still pass;
  `scripts/eval-ask-tasks.py` keeps its current pass count.
- Dev MCP tools reading pipeline status/lineage still work (if available in the session).
- `git grep` finds no stale root path to a moved script outside dated history.

## 5. Deliverables
- Branch with two commits (Phase 1, Phase 2), not pushed, not merged.
- AGENTS.md and readme.md updated (AGENTS is canonical; CLAUDE.md only imports it).
- docs/activity-history.md entry (what, why, import strategy, hazards handled); BACKLOG leftovers.
- Report: old → new file map, reference counts before/after, test counts, dry-run diff, copy-run
  evidence, and the `.mcp.json` lines the owner must change.
Ask before deleting anything, before touching `.mcp.json`, and before merging.
```
