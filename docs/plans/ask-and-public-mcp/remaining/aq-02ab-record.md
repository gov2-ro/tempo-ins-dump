# AQ-02 completion record: steps 02A (task set) and 02B (offline runner)

**Status (2026-10-17): 02A and 02B implemented and verified locally on branch `aq/02-task-eval`.**
Offline replay only. Not pushed, not merged, not deployed. **02C (live-provider mode) was not built**,
and no model, hosted connector, ChatGPT or Claude client was used: every pass below is a statement
about the deterministic system with a scripted provider, never about live-model quality.

| | |
|---|---|
| Baseline | `ce472e9` (AT-05 + the remaining/ specs), full suite 1,175 passed / 73 skipped |
| Code | 02A `79a9542` (task set, fixtures, validation tests); 02B is the commit that contains this record (runner and its tests) |
| Task set | `data/eval/ask_tasks.json`, `ask-tasks/1`, version `2026-10-17.1` |
| Generation (synthetic) | `gen-at01-fixture` (built per run, thrown away) |
| Generation (copied, read-only) | `9b3e065d…` at `/Users/pax/devbox/gov2/tempo-gen-20261012/data`; no file of the copy was modified (`find -mmin` over the copy: none) |
| Corpus / tables / baselines changed | none. `data/eval/*baseline*`, search and chart baselines untouched |

## 02A: the versioned task set

**Files.** `data/eval/ask_tasks.json` (new, not a baseline), `tests/aq02_env.py` (the synthetic
generation), `tests/aq02_tasks.py` (loader, validator, number/text helpers, shared with the runner),
`tests/test_aq02_tasks.py`.

**Fixture.** One synthetic generation, composed from the existing builders (`build_countx`,
`build_core` + `RECIPES`, `at02_env`'s POPC, `test_at05_ranking.build` for CITYX/GOS102A,
`test_at01_discovery._build`, `test_at01_query`'s PARENTX/CHILDX family) plus a few datasets of its own
(raw values in `aq02_env.py`: POPD, UNEMR, UNEMI, BIRTHA/B, MONTHX, DUPL, NOTOT, BIGLONG,
POP107D_grupe_localitate, BIGSCAN with 1,000,100 rows) and a concept/recipe catalogue for them. The
declared dataset list in the task file must equal the built `matrices`; a test checks it.

**Tasks (42).** T01-T20 of AT-04 and X01-X12, the spec's minimum extra cases in its order, plus siblings
that need their own scripted conversation: T02B (generic unemployment), T10B (conflicting key), T14B/T14C
(second empty answer, content filter), T17B (stale evidence), T20B (provider timeout), T20C (MCP busy),
X03B (explicit-year golden on the copied generation), X04B (explicit domicile city ranking), X10B
(sign/endpoints). Every prompt and scripted answer exists in RO and EN; their figures are checked to agree.

| Key | Meaning |
|---|---|
| `id`, `title`, `category`, `fixture`, `surfaces` | stable ID (`[TX]dd[A-Z]?`), synthetic or copied fixture, `direct` (Ask loop over the real tools in process) and/or `mcp` (SDK client over Streamable HTTP, default public gate) |
| `prompt`, `steps`, `answer` / `turns` | the scripted conversation: `tool`+`arguments` (`$PROMPT` = the question), `follow` (tool and arguments taken from an earlier result, e.g. discovery's own `next_call` or a `recovery` entry), `provider`/`raise`/`cancel` faults, `hold` (keeps an MCP call running), `before` (advance the generation) |
| `expect` | `outcome`/`reasons`/`verification`, expected `tools` (scripted), `calls` (status, reason, warning codes, pointer equalities, absent paths), `numbers` (JSON pointer, value, **derivation** such as `120 / 60`), `evidence` (datasets, unit, periods, keys, generation, scope), `qualifications`, `forbidden` (claims and figures), `limits`, `context`, `table`, `mcp` |
| `negatives` | intentionally wrong answers, each with `detect`: the checks that must fail, the app's expected verdict (`withheld`, `flagged`, `accepted`) and, for `accepted`, a documented `known_limitation` and the hard categories |
| `known_failure` | a current app limitation of a supported task (package, categories, variants, note) |
| `pinned` / copied-fixture task | the same case on the read-only copied generation, with its own expectation block |

**Independent expectations.** `tests/test_aq02_tasks.py::test_every_expected_number_is_recomputed_from_raw_cells`
recomputes every expected number from the generated Parquet files with plain DuckDB and Python
arithmetic (no tool, no app code) and fails on a number without a recomputation or an unused one.
Worked examples: 120 stays / 60 residents = 2; the winner among 231 locality rows is row 230 (329 =
229 + 100) after row 200, and the larger 9999 COMMUNE (999,999) must stay out; COUNTX B 1992->2002 =
150 - 200 = -50 and D 2010->2020 = 0 - 90 = -90 (percent -100, -33.33…, -16.67…, C excluded: zero
baseline); POPX single-year level 2025 = 5 ages x 2 sexes x 11 = 110, the double count 220 is the
forbidden figure; births 80 + 50 + 34 = 164 against 82 + 52 + 34 = 168 (332 and 166 forbidden).
Copied generation (recomputed from its Parquet, `corpus`-marked, skips individually): Brasov 2025
2,751,439 / 560,277 = 4.910854809317534; births 2023 164,004 (POP201E) and 168,079 (POP201D); county
change 2012->2021 Prahova -58,119 (761,699 -> 703,580), Municipiul Bucuresti -58,085, Teleorman
-53,623, Olt -47,904, Buzau -45,281 over 42 counties; city populations 2026 (319 catalogue cities,
Bucuresti 2,108,049 ... 30th Tulcea 77,647) and, as an explicit-year golden, 2025 (2,124,150 ...
Tulcea 78,862: the historical experiment's figures). "Current" resolves 2026 and is asserted
separately from the pinned 2025 golden; no expectation was changed to fit a run.

**Static wiring.** Each correct answer states exactly its expected figures (and no other), holds its
mandatory statements and none of its forbidden claims; each wrong answer really trips the check it
declares (a pattern/figure present, a statement absent, a figure not stated, a stray figure), without
running the app.

## 02B: the offline runner

**Files.** `scripts/eval-ask-tasks.py` (new), `tests/test_aq02_runner.py`, `tests/test_aq02_pinned.py`.

```bash
source ~/devbox/envs/240826/bin/activate
python scripts/eval-ask-tasks.py                        # all tasks, RO+EN, direct+mcp, with wrong-answer controls
python scripts/eval-ask-tasks.py --task T06 --lang en --surface direct
TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-gen-20261012/data python scripts/eval-ask-tasks.py   # + copied-generation cases
python scripts/eval-ask-tasks.py --list | --validate-only | --no-controls
```

Exit codes: 0 pass; 1 any failure; 2 usage/task-file error; **3 only documented known limitations
remain** (the run cannot claim "zero unsafe accepted claims" yet).

- **Offline by default and only.** `--mode live` does not exist (02C). The provider is a `Script`
  patched in through `at02_env.scripted`; every result and the report carry `"tool_choice":
  "scripted"` and `"live_model_quality": "not_measured"`.
- **Real everything else.** `agent.run_agent` with its budgets, context compaction, caches and claim
  verification over the real tools; follow-ups pass through `ask_context.validate` like the router's.
  The MCP surface uses the SDK client against the app built with the **default public gate** and
  asserts the structured/text parity, the wire bound, released slots and **zero provider calls**.
- **Checks.** Outcome/reason/verification, scripted tool order, envelope status/reason/warnings,
  hand-checked figures (located in the real result, stated in the answer, optionally bound to a
  matched claim), evidence (source, unit, periods, key, generation, scope), mandatory statements and
  tool-side qualifications, forbidden claims, budgets (dispatches/executions/cache hits/attempts/
  retries/compaction), context hints and entries, table links, secrets; invariants on every Ask turn
  (within budget, call/result pairing, non-empty answer, slot released). Prose is not judged: tasks
  with a `review` note go to a `human_review` queue; no LLM judge.
- **Hard failures** (never averaged): `unsafe_claim_accepted` (a forbidden claim still in the answer
  the app does not flag), `numerical_deviation` (a tool value off the hand-checked number, or an
  unexpected figure the app accepts), `secret_leak` (a canary in the answer, error, events, logs,
  trace or the report file; the report itself is scanned and redacted).
- **Wrong answers.** Each `negatives` entry is replayed; a control is `detected`,
  `known_limitation` (accepted today, documented), `resolved` (a documented limitation the app now
  contains: an improvement, not a failure) or `mismatch` (failed run).
- **Report** (`ask-task-report/1`, written **outside the repository**, default
  `<system temp>/tempo-ask-task-eval/`; refused inside the repo): run metadata (task-set version and file
  hash, system-prompt hash, tool contract, git head and dirty-code hash, Ask budgets, the MCP gate
  settings, Python), and per result: surface, variant, outcome/reason/verdict, evidence, checks,
  generation, dispatch/execution/cache/attempt counts, bytes, latency, tokens (`known:false` unless the
  script reports usage), cost (`usd:null`, "unknown"), skips and failure categories. The summary
  excludes skips and controls from the denominator and lists legitimate refusals apart from hard
  failures. Metadata only: no prompt, answer or trace unless `--retain-content
  --consent-content-retention`, then redacted into a separate `.jsonl`.

## Results

Virtualenv `~/devbox/envs/240826`, Node 22, `PYTHONDONTWRITEBYTECODE=1 python -m pytest ... -q -p no:cacheprovider`.
Ports 8121-8125 were not needed: the runner starts no server (the MCP surface is the SDK client over an
in-process ASGI transport).

| Command | Result |
|---|---|
| `tests/test_aq02_tasks.py` | 15 passed, 1 skipped (the copied-generation recomputation: no corpus) |
| same, `TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-gen-20261012/data` | 16 passed (the pinned numbers equal the copy's own Parquet sums) |
| `tests/test_aq02_runner.py` | 24 passed (about 22 s) |
| `tests/test_aq02_pinned.py` | skipped without the copy; 1 passed with it (10 pinned + 2 X03B results; the only non-pass is the documented X03B/en known failure) |
| `tests` (full) | **1,217 passed, 75 skipped** (1,292 collected = 1,251 existing + 41 new); baseline 1,175 passed / 73 skipped plus the 3 browser tests added later; the 2 new skips are the corpus-marked tests |
| `python scripts/eval-ask-tasks.py` (no copy) | 130 executed: 124 passed, 0 failed, 6 known failures; 12 skipped (the six pinned tasks, individually, `prerequisite_missing`); controls 42: 28 detected, 14 known limitations, 0 mismatch; exit 3 (`blocked_by_known_limitations`) |
| same with the copy (generation `9b3e065d…`) | 142 executed: 135 passed, 0 failed, 7 known failures; 0 skipped; controls as above; 8 legitimate refusals/clarifications; 0 secret leaks; exit 3 |

The first full run failed 308 tests in unrelated files: my `test_a_model_call_from_the_mcp_surface...`
patched `registry.call_tool` with its own monkeypatch while the runner's MCP turn also re-set it through
the module-scoped MonkeyPatch, whose later undo re-installed the test's wrapper. The runner now swaps
`call_tool` by direct assignment restored in `finally`; the full suite above is the rerun. The copied
generation was only read: nothing under it was modified (`find ... -mmin -60`: none).

Report files (metadata only, outside the repo): `<system temp>/tempo-ask-task-eval/ask-task-report-*.json`
(for example the copy run `ask-task-report-20261017T160506Z.json`, task file hash `7f7a26f3671be8f5`,
system-prompt hash `05798a696d30576e`, tool contract `tempo-tools/2`, dirty code hash recorded). The
scratchpad directory named in the assignment was no longer available, so the default location was used.

What the 14 control `known_limitation` results mean: the runner replayed a wrong answer, flagged it for
the declared reason (a forbidden claim or figure present, a statement missing) and the Ask app labelled
it verified/accepted. They are listed under hard failures with `known: true`, so the run can never read
as "zero unsafe accepted claims" while they exist. All other wrong answers (28) were withheld or flagged
by the app for the declared reason: count presented per resident (T06, X01), wrong unit (X10), wrong year
in its own sentence (X10), swapped entities in separate sentences (X10), the 2015 question answered with
a 2021 value (T05), merged namesakes (T09), double-counted ages (T10), a guessed Total (T12), a series
sum (X07), a forecast with invented percentages (X12), 1100 instead of 1010 (T01), the reconstruction as
the published value (T07), an invented total of an oversized preview (T13).

## Findings: what the runner shows about the current app

Task IDs the orchestrator should expect to change when AQ-03/AQ-04A are merged (recorded as known,
not papered over; they flip to `known_failures_resolved` / `resolved` instead of failing the run):

| ID | Surface | Limitation (current app) | Package |
|---|---|---|---|
| T06 ro/en | direct | the ratio `2` gets no claim (small integers are skipped): "verified" with zero claims | AQ-03B |
| T07 ro/en | direct | the cross-check value 9.9 (`rows[].reconstructed`) is not a citable leaf: a correct sentence ends `partial/unverified_numbers` | AQ-03A |
| X04B en, X03B en | direct, mcp | English "domicile population ... cities" is treated as explicit (`explicit_population`) but the city branch tests the Romanian stem `domicili`: `level_unavailable` | AQ-04A |
| T01 `figure_off_by_one` | direct | a stated 1011 is matched to the cell 1010 (tolerance `max(half unit, 0.5 %)` applies to exact integers): `numerical_deviation` accepted | AQ-03 |
| T11 `ages_0_2_as_total` | direct | a 0-2 age slice presented as "total population" is accepted (the number is real) | AQ-03 |
| X03 `domicile_relabelled_resident` | direct | domicile figures called "resident population" are accepted | AQ-03 |
| X10 `wrong_year_in_a_two_year_sentence`, `swapped_entities_in_one_sentence` | direct | two years / two entities in one sentence cannot be told apart | AQ-03B |
| X10B `increase_for_a_decrease`, `endpoints_swapped` | direct | direction and endpoint years are not bound (`abs(c) == abs(v)`; sign not compared) | AQ-03A/B |

Observations that did not become failures: Ask labels a turn that ends after a discovery refusal
(`level_unavailable`, `unsupported_operation`; X04, X05) `answered`, reason `null`, because only data
tools count toward `refused` (the expectation allows `answered` or `refused`; the refusal itself is
checked on the discovery result and the answer); recipe row components (`stays`, `population`) and
`eligible_count` are not citable figures, so a natural sentence that states them is flagged
`unverified_numbers` (kept out of the scripted answers; a candidate for 03A).

## Code-ready versus validated

| Item | Status |
|---|---|
| 02A task set, fixtures, independent arithmetic | code-ready and validated locally (tests above) |
| 02B runner, report, controls, MCP and Ask loop surfaces | code-ready and validated offline |
| Copied-generation cases | run once, read-only, generation `9b3e065d…`: see Results |
| 02C live-provider mode, spend ceilings, 3-repetition runs | **not built, not run** (needs explicit provider/model/budget authorization) |
| ChatGPT/Claude client, Fly 512 MiB, browser | not run (outside this package) |

## Configuration and rollback

No setting, limit, default or dependency changed. The runner records the Ask budgets (8 model calls,
12 dispatches, 90 s, 64,000 output tokens, 96 KiB context) and the default public gate (1 concurrent
operation, 10 s, 1,000,000 scan rows) it ran under. Rollback is deleting the seven new files
(`git revert` of the two commits); no corpus or schema migration, no app code changed.

## Remaining gates

02C (budgeted live adapter and runs), the owner's decisions on the known limitations above (AQ-03,
AQ-04A), re-running this runner after those merge (expect the listed `known_failures_resolved` /
`resolved` entries, then remove the declarations from the task file), and the unchanged AT-04 release
gates.
