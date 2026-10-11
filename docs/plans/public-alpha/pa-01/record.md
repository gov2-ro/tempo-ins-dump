# PA-01 implementation record

Branch `pa/00-baseline` (worktree `../tempo-alpha`), based on audited commit
`6a727a2`. Generation `a6737a263a34bf83b69dde1c8a0366f584396d28a78a716f0ce55563fdbdbb90`
(copy `tempo-gen-20261005`). Recorded 2026-10-11. Not deployed.

## Increments

| Commit | Scope | Audit |
|---|---|---|
| `bc7c509` | PA-01a: `app/services/data_query.run_query` is the one `/data` query; Ask tool and MCP `tempo_query` are adapters; transport-neutral filter validation; opt-in approximation everywhere; explicit empty selections; bound MCP samples | A01, A02, A08 |
| `9d14ea5` | PA-01b: `grain_guard` refuses aggregations over repeated observation keys on every aggregating path; `generation` identity in `/api/health` and each result (`contract: tempo-query/1`); no unguarded SUM without context; manifest records `grain_findings` | A04 |
| `94d8d27` | PA-01c: dashboard selection versions; Ask chart series identity; compare latest-common-period alignment, exclusions, undefined r; v2 citation links + `/dataset.html` redirect | A03, A05, A06, A09 (partly) |
| `ab4edc2` | `TEMPO_ASK_BYOK_ENABLED` (default off) closes own-key Ask; Ask page shows an unavailable state | launch boundary |

## Before → after (real generation, observed)

| Case | Before (6a727a2) | After |
|---|---|---|
| MCP `tempo_query(POP107A, TIME_PERIOD=2025, group_by=TIME_PERIOD)` | SUM 129,072,774 | `unavailable`, `overlapping_levels`, `AGE` (same as REST) |
| Ask `filters={TIME_PERIOD:[2025], BOGUS:[Cluj]}` | national 19,036,031, `ok` | `error: Invalid filters: unknown column 'BOGUS'` |
| Ask grouped rate without weights | unweighted mean, `approximation` | `unavailable/missing_weights` unless `approximate: true` |
| MCP sample with `Cluj' OR '1'='1` | literal interpolated | bound; 0 rows |
| `/data` TUR105E_judet by REF_AREA, 2024 | sum over 311 conflicting keys | `unavailable/conflicting_grain`, slice evidence 311 keys |
| Insights TUR105E_judet | latest KPI and ranking from conflicting rows | suppressed (`conflicting_grain`) |
| FOM106F slider, older response delayed | 2022 values under 2023 label | 2023 values (`tests/browser/audit_pa01_races.py`) |
| Compare POP105A_judete_grupe vs TUR105D_judete | 2025 vs 2024 implicitly | 2024 (latest common), r = 0.66, "association, not causation" |
| `/dataset.html?code=X` | 404 | 301 → `/dataset-v2.html?code=X` |
| Q1 Cluj via REST/Ask/MCP | 697,030 (2025) | unchanged, `quality.grain = unique` |

## Data change on the copy

`tempo-gen-20261005/data/corpus/generation-manifest.json` was rebuilt with the new
`audit.grain_findings` (177 duplicate-key files, 174 conflicting). The generation
id and every other field are byte-for-byte the same as before. Previous file kept
at `tempo-gen-20261005/snapshots/generation-manifest.pre-pa01b.json`
(sha256 `c295f7c9…`; new `4de50be4…`). The staged `deploy-data/` still carries the
old manifest. Restage before any release (PA-04). Without `grain_findings`, the
app treats unlisted files as `unverified` and checks slices at query time.

## Verification

- `python -m pytest tests -q`: **514 passed, 23 skipped** (all skips
  corpus-marked). New: `test_pa01_query_parity.py` (18), `test_pa01_grain_guard.py`
  (10), `test_pa01_frontend.py` (11), `test_fetch_ins_reference_cells.py` (4), BYOK
  switch (2). Changed on purpose: `test_fix02b_agent.py` approximations now opt
  in; fix08 Ask fixtures enable BYOK explicitly.
- Corpus-marked tests against the copy: 23 passed (unchanged).
- Chart-selector and search evals: identical to the PA-00 baseline (39/143/2,124;
  13/4). No expected difference: no chart or search code changed.
- Browser smoke on :8097 with the copy (1400px and 390px): v2 POP105A_judete_grupe,
  FOM106F, SOM103A_judete, POP107A, TUR105E_judet; v1; place Cluj; compare;
  Ask. No page errors, no 4xx/5xx responses. Ask at 320px shows the unavailable
  state.

## Remaining restrictions

- Ask stays excluded: A07, A13 and A14 are open, and no provider runs were made.
- Citations open the dataset, not the exact query slice.
- `normalizePerCapita` still uses the nearest population year (PA-03).
- A page whose tiles are all refused says "no visualization has data" without
  the reason (backlog).
- Grain evidence is file-level from the manifest; flagged files get a bounded
  query-time slice check (≤1M rows unfiltered, else `grain_unverified`).
- The DB/manifest binding is a size check, not a hash.

## Rollback

Each increment is a separate commit; revert in reverse order. Reverting
`9d14ea5` or `bc7c509` would reopen known unsafe paths (A01/A04), so per the
plan prefer disabling the affected capability. To restore the copy's manifest,
copy the `snapshots/` file back; the app then treats files as `unverified` and
checks slices at query time.
