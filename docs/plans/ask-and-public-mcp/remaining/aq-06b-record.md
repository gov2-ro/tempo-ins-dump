# AQ-06B completion record: reproducible local release candidate

Step 06B of [06-client-and-release.md](06-client-and-release.md) only. 06C (external
clients, onboarding draft) is not started. Run 2026-10-25 on branch `aq/06b-release-candidate`.

**Result: the local candidate passes every gate that can run on this Mac. The image, the
Linux 512 MiB profile, hosted clients and live model quality are `not_run`. This is not a
release approval.** Nothing was deployed, uploaded or published. DNS, `fly.toml` and
production settings were not touched, no model provider was called and the corpus was not
written.

## Candidate identity

| What | Value |
|---|---|
| Code | `a6f41a1` (clean tree). `app/` and `app/static/` are byte-identical in the later commits on this branch, which only add a `release-check.py --static` report line, tests and docs |
| Base | `fix/ask-answer-quality` `78fef36` (AT-05, AQ-01A…05A, AQ-06A) |
| Generation | `9b3e065d2fe9bb1df9bae2131b7bdeae9be3426f3c82b9a9954f7e6dc8f45550`, built 2026-10-14T21:28:30Z, latest source observation 2026-10-02 |
| Source corpus (read-only) | `/Users/pax/devbox/gov2/tempo-gen-20261012/data/corpus` |
| Scratch stage | `/Users/pax/devbox/gov2/tempo-rc-06b/deploy-data` (8,223 files, 971 MB). The repository's `deploy-data/` was not touched |
| Static build | `/Users/pax/devbox/gov2/tempo-rc-06b/static`: commit `a6f41a1`, built 2026-10-24T23:41:56Z, 3,376 datasets, 46,078 files, 666 MB, `api_origin` `https://api-ins.gov2.ro` |
| Task set | `ask-tasks/1`, set `2026-10-17.1`, file sha256 `af89bde0b1ccc41d…`, system prompt `03831146ca72a687…`, contract `tempo-tools/2` |
| Image | none on 2026-10-25 (no container runtime). Built and smoked on 2026-10-27 under Colima: see [aq-01b-linux-run-record.md](aq-01b-linux-run-record.md) |
| Host | macOS 15.8.1 arm64, Python 3.12.15, mcp 1.27.0, FastAPI 0.133.1, DuckDB 1.4.2, uvicorn 0.44.0 |

## What changed in code

- `scripts/release-check.py --local`: serves this checkout against `--stage` with the
  Dockerfile's uvicorn command (one worker, proxy headers) and `fly.toml`'s `[env]`. The
  caller's `TEMPO_*` switches and every `*_API_KEY` are dropped, so no provider can be
  reached. It then runs the same checks the Docker smoke now shares:
  - **Default switches:** FTS; the staged generation is the one served; `/mcp` 404 and
    `mcp.enabled: false`; `/api/ask/config` `available: false`; a search and a data call.
  - **MCP on** (`TEMPO_MCP_ENABLED`, local-test origin), with the production shape of a
    separate site (`TEMPO_PUBLIC_SITE_URL` and `TEMPO_CORS_ORIGINS` set to a stand-in site
    origin):
    - the stdlib `mcp_probe`, and the official SDK client listing the eight tools;
    - `run_recipe` for every reviewed recipe (a refusal is a warning);
    - `get_evidence_links` on the first recipe that runs: its ZIP returns 200 at the cited
      generation; another generation gets 409 on the ZIP and `generation_changed` from the tool;
    - page links on the site origin, API links on the API origin;
    - CORS: the listed site is allowed, a foreign site is refused, `/mcp` gets none;
    - Ask stays off.
- `--docker` now refuses a `--stage` other than the repository's `deploy-data/`, because the
  Dockerfile copies only that directory and would build an image of other data.
- `release-check.py --static` reports where the Ask page sends questions (`api_origin`), or
  that the site has no Ask. It fails on an `api_origin` that is not a bare https origin.
- `tests/test_aq06b_release_check.py`: env scrubbing and the image-like command, the MCP run's
  switches, and the `--docker` stage guard.

## Gates (AT-04 table)

| Gate | Status | Code/generation/date | Command/client | Evidence/limitations |
|---|---|---|---|---|
| AT-01 tool contract + numerical fixtures | pass | a6f41a1 / synthetic / 2026-10-25 | full pytest (inside the stage gate) | 2079 passed, 89 skipped |
| AT-02 Ask replay/UI/privacy | pass (scripted) | a6f41a1 / 9b3e065d | `eval-ask-tasks.py` on the stage; browser suites in pytest | 144/144 positives on both surfaces, 0 secret leaks, 0 numerical deviations. Exit 3: the 2 known T11 controls (`ages_0_2_as_total`, AQ-03 limitation). The tool choice is scripted, not a live model |
| AT-03 SDK transport/resource-bound tests | pass | a6f41a1 / 9b3e065d | pytest + `release-check.py --local` | In-process SDK tests; the official SDK client against a separate uvicorn process serving the stage |
| Existing full pytest + static parity | pass | a6f41a1 | stage gate; `-m corpus` with `TEMPO_DATA_DIR` = stage | 2079 passed / 89 skipped (synthetic run; corpus tests skip there). The corpus-marked tests on the stage: 88 passed. Static API parity 1017/1017 |
| Stage gate (strict) | pass | a6f41a1 / 9b3e065d | `release-check.py --require-clean-audit --accept-restriction conflicting_grain --local` | Manifest = 8,223 files; FTS; 3,376 canonical matrices covered; generation manifest consistent; staged DBs = source; restriction `conflicting_grain` (160 files) enforced by `grain_guard`. Warnings: 734 non-canonical parquets copied for fallbacks, and the recipe below |
| Local candidate smoke | pass, 1 warning | a6f41a1 / 9b3e065d | `--local` | All checks above. **`registered_unemployment_county` is refused on the public MCP** (`unavailable/query_budget`: estimate 1,369,357 rows > 1,000,000), even with a year and one area. Backlog P1 |
| Stage rollback | pass | 2026-10-25 | `prepare-deploy-data.sh` again, `release-check.py --rollback` twice | Restaged (.prev = the first stage), rolled back, re-validated under the strict gate, rolled forward. Same generation both times, so only `staged_at` differs |
| Static build gate | pass | a6f41a1 / 9b3e065d | `release-check.py --static … --api-cases` | Hashes, no stray files, no file > 15 MB, all 3,376 datasets complete, FTS exported, 3 recipes recorded, API parity 1017/1017 (5 browser-budget refusals, as designed), Ask → `https://api-ins.gov2.ro` |
| Static browser smoke | pass | a6f41a1 | Playwright on `tools/static-engine/serve.py`, `api-ins.gov2.ro` blocked | `/`, `/dataset-v2.html?code=POP108D`, `/places`, `/ask.html` at 320/390/1280 px: no horizontal scroll, no console errors other than the blocked API host, 0 `/api` requests to the static host. The Ask page shows "cannot be reached" with a retry |
| Pinned copied-generation task checks | pass (scripted) | as AT-02 row | | Same run |
| Separately authorized live-provider tasks | not_run | | | Needs AQ-02C authorization and budget |
| ChatGPT / Claude interoperability | not_run | | | 06C. Needs a reachable test endpoint and accounts |
| Linux image/memory/mixed-load gate | measured, above 75 % on amd64 | f88924c / 9b3e065d, 2026-10-27 | `benchmark-mcp.py --mode container` under Colima | No OOM or restart, no unexpected 4xx/5xx, slot frees. Peak 73 % of 512 MiB on arm64, 76–77 % on amd64 (Fly's architecture), with the default or a 5M scan cap. Per-tool worst cases not run. [aq-01b-linux-run-record.md](aq-01b-linux-run-record.md) |
| Docker image build + smoke | pass after a fix | f88924c / 9b3e065d, 2026-10-27 | `release-check.py --docker` (strict stage flags) | The first build exited at import: `sdmx_labels.py` was not copied into the image (fixed, with a test). Then every `--local` check also passed on the image (arm64) |
| Plugin package validation and real help links | not_run | | | 06C |
| Owner exposure/publication approval | pending | | | |

## Switches and limits the candidate was tested with

- **Default run:** `fly.toml` `[env]` (`TEMPO_DEBUG=false`, `TEMPO_ASK_LOG_CHATS=false`), with
  `TEMPO_DATA_DIR` = the stage. Ask off (`TEMPO_ASK_ENABLED` and `TEMPO_ASK_BYOK_ENABLED`
  unset), MCP off, CORS for local origins only.
- **MCP run:** as above, plus `TEMPO_MCP_ENABLED=true`, `TEMPO_MCP_LOCAL_TEST=true`,
  `TEMPO_PUBLIC_BASE_URL=http://127.0.0.1:<port>`,
  `TEMPO_PUBLIC_SITE_URL=TEMPO_CORS_ORIGINS=https://site.example`.
- **MCP limits (defaults, unchanged):** body 65,536 B; 1 operation at a time; 10 s deadline;
  120 calls/min; 600 requests/min; scan 1,000,000 rows; cache 4 MiB, 128 entries, 300 s.
- **Ask:** not exposed. The limits are AT-02's, unchanged.

## Commands (secret-free)

```bash
source ~/devbox/envs/240826/bin/activate
G=/Users/pax/devbox/gov2/tempo-gen-20261012/data; S=/Users/pax/devbox/gov2/tempo-rc-06b
TEMPO_CORPUS_SRC=$G/corpus TEMPO_DEPLOY_OUT=$S/deploy-data bash scripts/prepare-deploy-data.sh --no-tarball
python scripts/release-check.py --stage $S/deploy-data --source $G/corpus \
    --require-clean-audit --accept-restriction conflicting_grain --local --port 8195
TEMPO_DATA_DIR=$S/deploy-data python -m pytest tests -q -m corpus
TEMPO_DATA_DIR=$S/deploy-data python scripts/eval-ask-tasks.py --report-dir $S/ask-tasks --quiet
TEMPO_DATA_DIR=$G python scripts/build-static.py --out $S/static --base-url https://ins.gov2.ro \
    --api-origin https://api-ins.gov2.ro                                   # 20 min
TEMPO_DATA_DIR=$G python scripts/gen-api-cases.py --out $S/api-cases.jsonl --n 300
python scripts/release-check.py --static $S/static --source $G/corpus --api-cases $S/api-cases.jsonl --skip-tests
# rollback exercise
TEMPO_CORPUS_SRC=$G/corpus TEMPO_DEPLOY_OUT=$S/deploy-data bash scripts/prepare-deploy-data.sh --no-tarball
python scripts/release-check.py --stage $S/deploy-data --rollback      # and again to roll forward
```

The logs and reports are in `/Users/pax/devbox/gov2/tempo-rc-06b/`: `gate-stage.log`,
`corpus-tests.log`, `ask-tasks/`, `static-build.log`, `api-cases.log`, `gate-static.log`,
`stage-1.log` and `stage-2.log`. They are outside the repository and contain no keys.

## Findings

1. **County unemployment recipe refused on the public MCP** (P1 in `docs/BACKLOG.md`).
   Discovery's reviewed default for a county unemployment question leads MCP clients to a
   refusal, while Ask answers it. The cap was not changed: that needs the AQ-01B Linux run or
   a reviewed design.
2. **`--docker` with a scratch stage would have built the wrong data.** It is now refused, as
   described above.
3. **The ART124A insights binder errors** still appear during the static build (known backlog
   item). The build and its gate pass.
4. **Cutover order.** The static build points Ask at `api-ins.gov2.ro`, which still runs the old
   code (no `/api/ask/config`, CORS `*`). Until Fly runs this candidate with
   `TEMPO_CORS_ORIGINS=https://ins.gov2.ro`, the static Ask page shows "cannot be reached".
   Deploy Fly before switching DNS. Ask stays unavailable either way while both Ask switches
   are off.

## Rollback

- **Code:** revert this branch. `--local` and the guard are additive.
- **Stage:** `release-check.py --rollback` (exercised above).
- **Deployed image:** `fly releases`, then redeploy the previous image.
- **Static site:** repoint `current` at the previous release (`docs/DEPLOY-STATIC.md`).
- **MCP and Ask:** each is disabled independently by unsetting its switch. The default run
  above proves both are off by default. No step changes the corpus.

## Remaining gates before exposure

AQ-01B (Linux 512 MiB / mixed load, with a container runtime), AQ-02C (live-model quality, if
Ask is to be exposed), 06C (hosted ChatGPT/Claude), the recipe refusal above, the review of
the privacy, retention and contact copy, and your authorization of the production settings
and deployment.
