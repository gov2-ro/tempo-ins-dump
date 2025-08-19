# Profiler and Explorer Guide

Date: 2025-08-20

This document explains how the INS CSV Profiler and the internal Explorer UI work, where outputs are written, and how to use the n-/d- validation flags.

## Overview

- Profiler (`profiling/data_profiler.py`)
  - Validates and profiles INS-style CSVs
  - Emits per-file CSV profiles and a combined JSON when `--orchestrate` is used
  - Integrates INS-specific rules to surface `n-*` and `d-*` validation flags
- Explorer (`ui/server.py` + static `ui/explorer.*`)
  - Lightweight internal UI for browsing combined JSONs
  - Sidebar search and flag filters
  - Dataset detail with metadata and preview of the first 15 rows

## Output paths (repo-local by default)

- CSV profiles: `data/profiling/datasets/`
- Combined JSONs: `data/profiling/combined/`

You can override the combined JSON output directory at run-time with `--combined_out`.

The Explorer prefers the repo-local combined directory (`data/profiling/combined/`). You can override it with the `COMBINED_DIR` environment variable.

## Running the profiler

- Basic (single file):
  - `python profiling/data_profiler.py data/4-datasets/ro/AED109A.csv --orchestrate`
- Directory (batch):
  - `python profiling/data_profiler.py data/4-datasets/ro/ --orchestrate --quiet`

Useful flags:
- `--quiet`  Reduce console output and disable progress bar
- `--debug`  Verbose debug for troubleshooting (e.g., flag extraction)
- `--force`  Regenerate CSV profiles even if they exist
- `--combined_out PATH`  Write combined JSONs to `PATH` instead of the default
- `--rules` / `--unit-rules`  Override classification rules files

Interrupt any long run safely with Ctrl+C.

## Validation flags (n-* and d-*)

INS-specific validation rules add tags indicating what a column name suggests (`n-*`) and what the column data contains (`d-*`). Examples:
- Name-based: `n-time`, `n-time-perioade`, `n-geo`, `n-geo-judete`, `n-multiple`
- Data-based: `d-time`, `d-time-ani`, `d-gender`, `d-geo`, `d-geo-regiune`, `d-grupe-varsta`, `d-mediu-geo`, `d-total`, `d-prefix`, `d-suffix`

Where to find them:
- In combined JSON: `columns[*].validation_flags`
- Also included in `file_checks.validation_results[*].context.validation_flags`

For a narrative of rules, see `profiling/VALIDATION_README.md`.

## Combined JSON schema (simplified)

- `source_csv` (string): absolute path to the source CSV
- `file_checks` (object):
  - `um_label` (string|null)
  - `validation_summary` (object)
  - `validation_results` (array of objects): rule-level details with optional `context.validation_flags`
- `columns` (array of column objects):
  - `column_index` (int)
  - `column_name` (string)
  - `guessed_type` (string: e.g., string, integer, float, percent, year, trimestru, luna, um)
  - `unique_values_count` (int, optional)
  - `unique_values_sample` (string, optional)
  - `validation_flags` (array of strings, may be empty)
  - `semantic_categories` (string, optional — set when classifier matches)
  - `functional_types` (string, optional — set when classifier matches)

Notes:
- Numeric types and numpy values are converted to JSON-native types.
- Period-like columns (years, trimesters, months) are detected and normalized.

## Explorer UI

- Start the server: `python ui/server.py`
  - Default port: `http://127.0.0.1:5050`
  - Env:
    - `COMBINED_DIR=/abs/path/to/combined`  (defaults to `data/profiling/combined/`)
    - `DEBUG=1` for verbose logs
- Endpoints:
  - `GET /api/health` — basic health/status
  - `GET /api/flags` — counts of flags across datasets
  - `GET /api/datasets` — list (query params: `q`, `flags`, `limit`, `offset`)
  - `GET /api/datasets/<id>` — dataset JSON
  - `GET /api/datasets/<id>/preview` — first 15 rows of the source CSV
- Front-end:
  - `GET /` — Sidebar search + flag chips, dataset list, detail panel with metadata and preview

## Troubleshooting

- “I don’t see new JSONs in the repo”
  - Ensure you’re on the updated defaults (now repo-local). If overriding, pass `--combined_out data/profiling/combined/`.
- “I see too much console output”
  - Use `--quiet`.
- “I want more details about flags”
  - Use `--debug` and inspect `file_checks.validation_results`.
- UI shows 0 datasets
  - Check `COMBINED_DIR` and verify JSON files exist; hit `/api/health` for path and count.

## Changelog (2025-08-20)

- Defaults changed to repo-local:
  - CSV profiles → `data/profiling/datasets/`
  - Combined JSON → `data/profiling/combined/`
- Explorer now prefers repo-local combined path first.
