# PA-00 baseline record

Recorded 2026-10-11. Status: **first increment** — baseline, generation check,
test/eval run and exposure inventory are done; the answer records are in
[answer-records.md](answer-records.md) (none verified yet). Labels as in the
audit: **Observed** (run today), **Audit** (2026-10-11 audit, not re-run),
**Source** (read in code at the commit below).

## Code

| Item | Value |
|---|---|
| Implementation worktree | `../tempo-alpha`, branch `pa/00-baseline` |
| Base commit | `6a727a2f10b10c0d46e4ae1a5acf2a6ca6d0605c` (`feat/structural-bar-toggle`, the audited commit) |
| Contains | `integ/fix02-fix03` @ `2e6fec2`, which merges `fix/03-corpus-repair` @ `1c62741` and `fix/02-measure-classification` @ `585e7ac` |
| Intervening changes | None in code. The plan, the audit report/evidence and the matching BACKLOG/activity entries were copied from the `fix/03-corpus-repair` checkout (untracked/uncommitted there, left untouched) |
| Not in base | `main` @ `dc8de05` is an ancestor; nothing on `main` is missing |

Other worktrees were clean: `tempo-structbars` (6a727a2), `tempo-integ` (2e6fec2).

## Data generation

| Item | Value |
|---|---|
| Corpus | `/Users/pax/devbox/gov2/tempo-gen-20261005/data/corpus` (copy; the live `data/corpus` is not the baseline) |
| Generation | `a6737a263a34bf83b69dde1c8a0366f584396d28a78a716f0ce55563fdbdbb90`, built 2026-10-05T15:41:35Z |
| Hash check | **Observed:** recomputed with `build-generation-manifest.py --no-grain`; generation id, DB sha256, search index and view-profile digest all equal the stored manifest |
| Staged copy | `tempo-gen-20261005/deploy-data/MANIFEST.json` names the same generation (status `present`), latest observation 2026-08-04 |
| Corpus audit | **Observed:** `audit-corpus.py` (grain on) = audit figures: 4,110 files; 1,185 served canonical, 2,191 registered splits, 734 noncanonical parents; 0 registration issues; conflicting grain 174 files / **160 served**; duplicate grain 177; 1 file with any invalid time; 1 served file without view profile; coverage 1,225/3,376 served |
| Source vintage | Retained INS exports in `tempo-gen-20261005/data/{2-metas,4-datasets}/ro`. Candidate matrices were fetched Nov 2025 (SOM103B: Aug 2026). Hashes in [answer-records.md](answer-records.md#source-files) |
| Consumers | **Observed:** dev servers :8093 (`tempo-structbars`) and :8091 (`tempo-integ`) both run with `TEMPO_DATA_DIR=…/tempo-gen-20261005/data`. Tests/evals below used the same path |

`/api/health` reports `manifest: null` when serving this copy: it reads only a staged
`data/MANIFEST.json`, not `corpus/generation-manifest.json`. A running server
therefore cannot prove its generation (see findings).

## Environment

Python 3.12.13 (`~/devbox/envs/240826`); duckdb 1.4.2, fastapi 0.133.1,
starlette 0.52.1, pydantic 2.12.5, pandas 2.1.3, pyarrow 22.0.0, uvicorn 0.44.0,
pytest 9.0.3, httpx 0.28.1. Settings: `TEMPO_ASK_ENABLED` unset (hosted Ask off;
BYOK still accepted, see inventory), `TEMPO_MAX_ROWS` default 50,000, search
mode `fts` (production).

## Tests and evals

| Run | Result |
|---|---|
| `python -m pytest tests -q` (worktree, no corpus) | **468 passed, 23 skipped** (all 23 skips are `corpus`-marked). Audit recorded 462/29 in `tempo-structbars`; the 6-test difference was not investigated |
| `TEMPO_DATA_DIR=<copy> pytest -m corpus` | **23 passed**, 468 deselected |
| Chart-selector eval vs baseline | 1,986 baseline / 4,110 current; 39 primary changes, 143 top-set, 51 confidence, 303 score drifts, 2,124 added — identical to the audit |
| Search eval vs baseline | 17 questions; 13 top-set changes, 4 order changes — identical to the audit |

No baselines were rebuilt. Commands are in [Reproduction](#reproduction).

## Exposure inventory

Who enforces validation (V), the aggregation policy (P) and a quality/grain gate (Q)
on each public path, at the base commit. **No path checks conflicting grain** —
nothing in `app/` or the MCP reads the audit's `conflicting_grain` list (A04).

| Entry point | Route / file | V | P | Q | Notes and bypasses | Candidate |
|---|---|---|---|---|---|---|
| Dataset data | `GET /api/datasets/{code}/data` (`dataset_data._dataset_data`) | `parse_filters`/`parse_group_by` reject unknown columns (**Observed**: `BOGUS` → 400) | grouped only: `decide_grouped` + `source_total_gate` for headline series | — | Raw rows have no decision. If `get_aggregation_context` returns `None`, a grouped query falls through to unguarded `SUM` (**Source**). Unknown values give `unavailable/slice_value_missing` on grouped queries | Yes |
| Insights / KPIs | `GET …/insights` (`insights.py`) | internal specs | `ap.decide` | — | | Yes |
| Composer tiles | `dashboard_composer.py` | internal | `ap.decide` | — | Client re-queries `/data` | Yes |
| Home headlines | `headlines.py` | internal | `ap.decide` | — | | Yes |
| Place profiles | `/api/places/…`, `/place/…` (`place_service.py`) | slug lookup | `agg.decide` | — | Approximations shown (Cluj unemployment); Bucharest gets **no KPIs** (see findings) | Yes |
| Population reference | `GET /api/reference/population` | level enum | none — `SUM` over all dims of `POP105A_*_grupe` | — | Correct only because `_grupe` is a complete partition with no total rows; no definition/period/generation in the response. Client per-capita uses nearest-year fallback (`dashboard-v2.js:1167`) | Yes (used by per-capita) |
| Comparison | `compare.js` (client) on `/data` | via `/data` | via `/data` | — | Independent latest period per dataset; Pearson on constant axis = 0 (A06) | Yes |
| CSV/XLSX download | `GET …/download` | `parse_filters` | n/a (raw) | — | Complete-or-413 (FIX-04) | Yes |
| SDMX data | `GET /sdmx/2.1/data/…` | registry key parse | n/a (raw) | — | Complete-or-413 | Yes |
| Catalog/search/related | `/api/datasets`, `/related`, `/api/categories*` | query params | n/a | — | Relatedness "100%" across definitions (A11) | Yes |
| Ask | `POST /api/ask` (`agent.py`) | **none on tool inputs** (A02) | `decide_grouped(…, allow_approximation=True)` | — | Hosted off by default, but any request carrying `api_key` passes (`ask.py`: `not ASK_ENABLED and not byok` → 404). Raw-query "strip Total and retry" broadens the slice silently | **No — exclude** (route must reject BYOK too) |
| Dev MCP | `tools/tempo-dev-mcp/server.py` | none | none — own SUM/AVG (A01) | — | `_sample_parquet` interpolates literals (A08) | Internal only |
| Static | `llms.txt`, `/view-profiles`, `/docs`, `/openapi.json` | — | — | — | `/docs` + `/openapi.json` are public by default | Decide in PA-04 |

## Findings new in PA-00

1. **Stage 6 drops every "Total" option**, so the corpus has no county
   all-activities net earnings (FOM106E) and no both-sexes unemployment rate
   (SOM103A/B). INS does publish those cells (it answered the national ones on
   2026-10-05). Q2 and Q3 are therefore blocked on source shape, not on code.
2. `place_kpi_config.json` says SOM103A has "no both-sexes row" and FOM106E "no
   all-activities total row". Both are artefacts of our fetch, not INS facts.
3. The Bucharest place profile (`county/municipiul-bucuresti`) returns 0 KPIs,
   all `no_data`, while the data has `Municipiul Bucuresti`. Likely the
   diacritic in the place name. Breaks Q1–Q3 portability to Bucharest.
4. `kpi_total_checks` records POP105A national 2025 as `match` although ours is
   19,036,031 and the INS cell is 19,043,151 (Δ 7,120). The 0.5 % tolerance is
   too loose for counts; the cause (revision vs. data) is unknown.
5. INS was unreachable on 2026-10-11 (`statistici.insse.ro:8077`: connection
   reset, also outside the sandbox). No fresh oracle could be fetched today.
6. `/api/health` cannot report the generation of an unstaged corpus.

Items 1–4 and 6 are added to [BACKLOG](../../../BACKLOG.md); item 1 is the
prerequisite in the answer records.

## Reproduction

```bash
source ~/devbox/envs/240826/bin/activate
cd ../tempo-alpha
G=/Users/pax/devbox/gov2/tempo-gen-20261005/data
python scripts/build-generation-manifest.py --data-dir $G --out /tmp/m.json --no-grain
python scripts/audit-corpus.py --data-dir $G --json-out /tmp/audit.json
python -m pytest tests -q
TEMPO_DATA_DIR=$G python -m pytest tests -q -m corpus
# evals: import tools/tempo-dev-mcp/server.py with TEMPO_DATA_DIR=$G and
# TEMPO_REPO_ROOT=$PWD, call tempo_eval_chart_selector() and tempo_eval_agent()
```

Outputs from this run (scratch, not tracked): recomputed manifest, audit JSON and
both eval reports. Re-running reproduces them; nothing here writes the corpus.
