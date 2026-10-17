# AT-05: Ask answer quality and entity rankings

Implementation plan, 2026-10-16. Baseline: AT-02/03 `22d9d4d`.

1. Discovery preserves the full question: ratio denominator, requested geography,
   latest period and ranking intent. Equivalent RO/EN tourism phrases reach the
   reviewed recipe; unsupported units/operations are stated rather than silently
   replaced. Generic population can use an explicit, disclosed default only where
   the requested coverage supports it; explicit definitions are never replaced.
2. Claims retain number, entity, period and unit. Detect explicit contradictory
   units/periods, including a raw count presented per resident, and withhold that
   prose. This bounded deterministic check is not a general natural-language
   entailment proof. Unknown-domain sums are partial with a machine-readable warning.
3. Add `rank_entities` under `tempo-tools/2` (eight shared tools). Inputs:
   dataset, entity_columns, year (null = latest actual annual period), filters,
   entity_class (all/cities), order, top_k, lang. Reuse the shared query and policy;
   query all eligible entities before sorting, refuse truncated/windowed sources,
   duplicate keys, mixed levels, missing identity and approximation. Cities use
   SIRUTA keys from INS GOS102A's municipality/town catalogue, with that reference
   cited. Class membership is a catalogue classification, not historical status.
   No cross-dataset arithmetic or density is added in this package.
4. Preserve rankings through MCP limits, Ask context, claim binding, presentation
   and generation-bound links. Show readable table headings and explicit preview
   captions; an unranked preview must not be displayed as the requested ranking.
5. Validate with synthetic numerical fixtures (winner beyond 200 rows, communes
   excluded, duplicate/truncated input refused, exact year, ties), paraphrases and
   deliberately wrong claims, then copied-corpus probes and browser smoke. Run the
   repository suite and search/static parity checks; report live-provider and
   production limits separately. No corpus migration or deployment.

Contract migration: envelope identifier changes to `tempo-tools/2`; existing seven
input shapes stay compatible. Existing REST `tempo-query/1` is unchanged. Stored
Ask context has no envelope version and is revalidated. Deploy adapters and tools
as one version; rollback is the previous checkout, with no data migration.


## Implementation and acceptance — 2026-10-17

Implemented in `.worktrees/ask-answer-quality` (`fix/ask-answer-quality`) from
`22d9d4d`. No corpus writes, baseline rebuilds, deployment or paid provider calls.
The default for unspecified population is resident population; city rankings use
explicitly labelled domicile population because that is the reviewed locality series.
Explicit resident population at city level is unavailable, never silently replaced.

The numerical checks cover a ranking winner beyond row 200, a larger commune that
must be excluded, exact/latest years, ties, duplicate/capped inputs, MCP scan admission,
generation-bound replay and Ask follow-up context. Claim tests include count-as-ratio,
wrong year/percentage, municipality identity, mixed units in one sentence, withholding
contradictory prose, and refusing to present an unranked preview as a ranking.

Read-only probes on generation `9b3e065d…`:

- Full question “Câte înnoptări revin la un locuitor în Brașov, în 2025?” now selects
  the tourism-intensity recipe: `2,751,439 / 560,277 = 4.910854809317534` overnight
  stays per resident. The table and claim checker use the recipe unit.
- Current top-30 cities resolves to 2026 domicile population. It ranks every
  eligible catalogue-matched city before taking 30 and excludes communes. The result
  remains `partial/unverified_total` because collapsed-domain completeness is unverified.
- `POP201E` and `POP201D` retain their 2023 values, 164,004 and 168,079, respectively;
  both now return `partial/unverified_total`, rather than implying verified complete totals.
- Explicit resident-population city rankings, density/correlation and city-only change
  requests return a limitation. GOS102A is used only as an identity/classification catalogue;
  its built-up area is not treated as administrative area for density.

Catalog search (all 17 evaluation questions) and chart-selector output are byte-for-byte
JSON-equivalent to the starting commit on the same copied corpus. The committed search
baseline already differs on all questions (13 top-set and four order changes); the chart
baseline also predates corpus additions and has existing drift. Neither was rebuilt.
The discovery changes themselves are covered by paraphrase/default regression tests.

Public MCP limitation: the default admission estimate counts the whole source file.
The locality population file in this generation has 3,898,870 rows, exceeding the
1,000,000-row public limit. The new ranking works through the native MCP client on
synthetic data and directly through the shared tool on the copied corpus, but this
national query is still refused by default public MCP. Raising that limit requires
memory/latency evidence on the deployment target; no safety limit was bypassed here.

Claim binding is deliberately bounded: a match means value/entity evidence with no
recognized explicit unit/year conflict, not a proof of every sentence's meaning.
Native-provider task evaluation and ChatGPT/Claude connector evaluation remain open.
Ranking evidence is generation-bound JSON, not a recomputation ZIP like period changes.

Validation:

- Full suite: 1,171 passed, 73 skipped; two failures were stale MCP assertions that
  still expected seven tools. Updated those assertions; the complete MCP resource
  suite plus the new ranking browser checks then passed (24 tests, no skips).
- Chromium smoke includes the ranking headings/caption at 320, 390 and 1280 px,
  with console-error and horizontal-overflow checks. Existing Ask browser scenarios
  and synthetic static/server parity tests ran in the full suite.
- Copied-corpus discovery/query/integration probes: 13 passed. The expected status
  of the full-age locality sum was updated to preserve `unverified_total` for the
  other unchecked dimensions; its numerical result is unchanged.
- Final claim/ranking/Ask-loop and existing agent regression checks: 83 passed.
- `git diff --check`: clean. Existing FastAPI deprecations and openpyxl cleanup
  warnings remain outside this package.


## Remaining implementation handoff

[Remaining-work specifications](remaining/README.md), written 2026-10-17, split
capacity, task evaluation, claim checks, discovery/messages, analytical extensions
and client/release work into independently verifiable steps. They preserve this
implemented baseline and clearly separate ready tasks from measurement/design
prerequisites. Writing those specs did not implement them or change the runtime.


## Pre-commit verification — 2026-10-17

The final complete repository suite passed: **1,175 passed, 73 skipped**, with
seven existing FastAPI/openpyxl warnings. Command: virtualenv activated,
Node 22 on PATH, `PYTHONDONTWRITEBYTECODE=1 python -m pytest tests -q -p no:cacheprovider --tb=short`.
Local socket access was enabled for real-server/browser checks. This supersedes
the earlier full-run result with stale tool-count assertions.

Commit review also caught a translation-function naming collision in the
truncated-table footer. Renamed the row variable and added a browser regression
at all three viewport widths. The new test was added after full-suite collection
and passed separately: **3 passed**, one each at 320/390/1280 px, with no skips
or console errors. The implementation and handoff specs are saved
together on `fix/ask-answer-quality`; no deployment or corpus change is included.
