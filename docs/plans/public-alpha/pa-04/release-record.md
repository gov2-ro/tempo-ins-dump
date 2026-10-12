# PA-04 release record (candidate, NOT released)

Recorded 2026-10-11. **Decision: not ready to deploy.** Engineering checks pass
on the local candidate. Four gates remain unperformed or blocked (see
[Open gates](#open-gates)). Nothing has been deployed, and no user sessions have run.

## Candidate

| Item | Value |
|---|---|
| Code | branch `pa/00-baseline`, worktree `../tempo-alpha`; candidate = HEAD after the PA-04 commits (`76d8e7b` + this record) |
| Generation | `a6737a263a34bf83b69dde1c8a0366f584396d28a78a716f0ce55563fdbdbb90` (copy `tempo-gen-20261005`) |
| Generation manifest | rebuilt 2026-10-11 with `audit.grain_findings`, same id; previous kept in `tempo-gen-20261005/snapshots/generation-manifest.pre-pa01b.json` |
| Staged artifact | `tempo-gen-20261005/deploy-data`, staged 2026-10-11T14:09:08Z (8,223 files, 770 MB). Previous stage (2026-10-05T15:43:19Z) kept as `deploy-data.prev` |
| Search index | FTS loads; covers all 3,376 canonical matrices |
| Image | **not built** (no Docker on this machine) |
| Exposure | Web app; Ask hosted and own-key both off (`/api/ask` → 404 for both); dev MCP not in the image (`Dockerfile` copies `app/` only); `/docs` + `/openapi.json` public (deliberate: API users) |

## Gates

| Gate | Command | Result |
|---|---|---|
| Strict release check | `release-check.py --stage …/deploy-data --source …/data/corpus --require-clean-audit --accept-restriction conflicting_grain` | **PASSED**: hashes for 8,223 files, FTS, generation consistent; restriction accepted (160 files refused for aggregation by `grain_guard`); 582 tests passed |
| Synthetic suite | `python -m pytest tests -q` | 582 passed, 46 skipped (all corpus-marked) |
| Corpus suite | `TEMPO_DATA_DIR=<copy> pytest -m corpus` | 46 passed |
| Reviewed answers | PA-00 Q1/Q4 candidate values, PA-02 judgments (22), PA-03 Q4 equality (42 counties) | pass, but Q1–Q4 are **not INS-verified** (see Open gates) |
| Adapter parity | `tests/test_pa01_query_parity.py`, `test_pa01_grain_guard.py` | pass |
| Evals | chart-selector, search | identical to the PA-00 baseline (39/143/2,124; 13/4); no rebaseline |
| Browser smoke | 17 pages × RO/EN × 1280/390/320 px on the staged data | no page errors, no 4xx/5xx, no overflow (raw `sitemap.xml` XML view excepted) |
| Rollback | `release-check.py --rollback` twice | previous stage passes the check, serves the same generation with FTS, and the swap back restores the candidate. The previous stage's manifest lacks `grain_findings`, so the app falls back to query-time slice checks |
| Image + resource limits | `release-check.py --docker` + workload under 512 MiB | **not performed** (no Docker) |

## Workload (unconstrained local, NOT the resource gate)

`scripts/alpha-workload.py --clients 5 --duration 600` against uvicorn (1
worker) on the staged data, macOS arm64 with 8 cores, warm. No memory limit was
enforced, so this does not satisfy the 512 MiB gate.

| Kind | n | p50 s | p95 s | max s |
|---|---|---|---|---|
| search | 6,982 | 0.075 | 0.158 | 0.461 |
| query | 7,092 | 0.029 | 0.075 | 0.325 |
| recipe | 2,690 | 0.074 | 0.143 | 0.417 |
| page | 1,768 | 0.013 | 0.053 | 0.239 |
| place | 859 | 0.892 | 2.320 | 3.199 |
| evidence | 1,750 (790 × 200, 960 × 503 busy) | 0.022 | 0.099 | 0.292 |
| export | 1,693 (774 × 200, 919 × 503 busy) | 0.053 | 2.605 | 4.782 |

22,834 requests: 0 unexpected 5xx, 0 corrupt exports, 0 differing bodies for
identical requests. The 503s are the documented export concurrency limit (2),
with `Retry-After`. Search/query p95 is well under the 2 s target; place
profiles' p95 is 2.3 s, slightly over.

**Memory: peak RSS 1,215 MiB** (idle 66–69 MiB). Five clients searching
`/api/datasets?q=` alone reach about 1 GiB, and the audited base commit did the
same. DuckDB's own accounting stays small (about 20 MB). Tighter DuckDB budgets
and thread counts did not change RSS, so the growth is allocator retention
outside DuckDB's buffer pool (macOS malloc). Linux/jemalloc may behave
differently. This must be measured in the real image under a 512 MiB limit
before any release. The budgets are now configurable
(`TEMPO_DB_MEMORY`, `TEMPO_SEARCH_MEMORY`, `TEMPO_SCRATCH_MEMORY`).

Fixed during the workload:
- Grouped queries returned rows in scan order, so identical requests produced
  different bodies. They are now deterministic.
- A 64 MB FTS budget made search silently fall back to name matching under
  load (5 OOMs). It is now 192 MB, with zero fallbacks.

## Restrictions accepted for the candidate

| Restriction | Enforced by | Evidence |
|---|---|---|
| 160 served files with conflicting observation keys (177 with any repeated key): no totals, rankings, KPIs, headlines, place KPIs or recipes over affected slices; raw rows labelled | `app/services/grain_guard.py` on every aggregating path | `test_pa01_grain_guard.py`; real TUR105E_judet refused with 311 conflicting keys |
| County net earnings (Q2) and both-sexes unemployment rate (Q3): no total; unweighted means only on explicit request, labelled | aggregation policy (`missing_weights`), PA-01 opt-in | API/UI show "rată/medie/indice fără ponderi" |
| Ask excluded | `TEMPO_ASK_ENABLED`, `TEMPO_ASK_BYOK_ENABLED` off; route 404 | `test_fix08_validation.py::test_byok_switched_off_rejects_own_key_calls` |
| Dev MCP internal | not copied into the image | `Dockerfile` |

## Open gates

1. ~~**INS reference cells**~~ — **closed 2026-10-12:** Q1–Q4 verified against INS
   cells and owner-reviewed. The candidate moves to the refreshed copy
   `tempo-gen-20261012` (see the release update below).
2. **Image and resource gate:** `release-check.py --docker` plus the workload
   under 512 MiB / 1 worker on Linux. The local RSS peak (1.2 GiB) makes this a
   likely blocker until measured.
3. **Formative sessions:** none run. Script: [session-script.md](session-script.md).
   Recruitment is the maintainer's action.
4. **Staged artifact after the last commits:** if code changes again, re-run
   the strict gate. The data stage itself is current.

## Static alternative (2026-10-11)

The site also builds as static files for shared hosting. This removes open
point 2 (image and resource gate) if that path is chosen. Gate:
`release-check.py --static` (manifest, generation, completeness, 991/991 API
parity). Browser smoke: 20 pages × RO/EN × 3 widths, no errors and no `/api`
requests. Not uploaded. See [DEPLOY-STATIC.md](../../../DEPLOY-STATIC.md).
Q2/Q3 are now reconstructed answers (`pa-00/answer-records.md`); only
Bucharest's Q3 value still waits for INS.

## Commands (for later, after the gates)

```bash
# re-stage (keeps previous as deploy-data.prev)
TEMPO_CORPUS_SRC=…/tempo-gen-20261005/data/corpus TEMPO_DEPLOY_OUT=<repo>/deploy-data \
  bash scripts/prepare-deploy-data.sh --no-tarball
python scripts/release-check.py --require-clean-audit --accept-restriction conflicting_grain --docker
# deploy ONLY with explicit authorization:
python scripts/release-check.py --require-clean-audit --accept-restriction conflicting_grain --docker --deploy
# rollback to the previous verified stage:
python scripts/release-check.py --rollback
```

Release notes draft: [release-notes-draft.md](release-notes-draft.md).
