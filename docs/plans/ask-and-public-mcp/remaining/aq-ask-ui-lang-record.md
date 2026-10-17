# AQ-UI-LANG completion record: the site's language as a signal for the Ask turn

Owner decision of 2026-10-17, implemented on branch `aq/ask-ui-lang` (worktree `.worktrees/aq-ask-ui-lang`).
No package of the `remaining/` plan; it follows the AQ-04C record (localized tool messages), which made the language of a
turn matter on the page.

- Baseline: `9afa711` (`fix/ask-answer-quality`).
- Code commit: `2153b82`. This record is added by the next commit; the code is unchanged by it.
- No corpus change, no baseline rebuild, no deployment, no provider call, no limit change, no new dependency, no new tool.
  Contract `tempo-tools/2` unchanged. `compare_periods`, `period_changes.py`, `tools/changes.py` and every `messages.py` entry
  are untouched (another agent owns them).

## Decision

Tool prose stays Romanian by default: `lang` defaults to `ro` in every tool, in MCP and in REST, and still does. What changes is
how the Ask turn picks its own language (`_Run.lang`, which drives the `lang` given to tools the model called without one, the
agent's warnings, the budget notices, the captions and table prose of `ask_present`):

| The question | The request's `lang` (the site's language) | The turn is |
|---|---|---|
| shows a language: a Romanian letter, or more Romanian than English hint words, or the reverse | any | that language (`lang_source: question`) |
| shows none (a tie, hint words absent included: "PIB Cluj 2023") | `ro` / `en` | the site's (`lang_source: site`) |
| shows none | absent | `ro` (`lang_source: default`) |

Before, the same tie read **English** (`guess_lang` returned `'en'` unless Romanian hints outnumbered English ones). With no site
language sent the turn is now Romanian, which is the owner's default; an old client (no `lang`) therefore sees Romanian
captions on a tie where it saw English. A question that shows its language is resolved exactly as before.

## Status

| State | Result |
|---|---|
| Code-ready | Yes. Targeted, AQ-02 runner and both full-suite runs below |
| Validated on synthetic data | Yes: resolver table, router, loop with a scripted provider, metrics, debug event; Chromium at 320, 390 and 1280 px through the real router, agent and tools with only the model scripted |
| Validated on a real corpus | The AQ-02 runner and the whole suite on `/Users/pax/devbox/gov2/tempo-gen-20261012/data` (read-only). No new corpus-marked behaviour |
| Model-validated (live provider) | `not_run`. The system-prompt line below is unmeasured with a real model |
| Deployed | No |

## What changed

| File | Change |
|---|---|
| `app/services/answer_check.py` | `lang_signal(text)` (`ro` / `en` / `None` on a tie), `guess_lang(text, default=None)` (unchanged answers unless a default is passed) and `resolve_lang(question, site)` returning `(language, source)`. Upper-case Romanian letters ("CÂȚI") now count as diacritics (they did not: only the hint tokens were lower-cased) |
| `app/services/agent.py` | `run_agent(..., site_lang=None)`; `_Run.lang, lang_source = resolve_lang(...)`; the dead `_guess_lang` wrapper removed; `AgentResult.lang`; `lang`/`lang_source` in the content-free `metrics` and the debug `start` event; one system-prompt line when the site decided (below) |
| `app/routers/ask.py` | `AskRequest.lang: Literal["ro","en"] | None` (anything else: 422 before any provider work, like the other field limits); passed to the agent; `site_lang` in the request metrics (also on 4xx/5xx paths); `lang` in the response |
| `app/services/ask_guard.py` | `site_lang`, `lang`, `lang_source` join the `METRIC_SCALARS` whitelist (short strings, truncated to 80) |
| `app/static/js/ask.js`, `app/static/ask.html` | `siteLang()` (`?lang=`, then `lens_lang`, default `ro`: the rule of `utils.currentLang`, `ui-preferences.js` and `site-chrome.js`) sent as `lang` with **every** question (one `body` object serves `/api/ask` and `/api/ask/stream`; follow-ups included, read at submit time); the captions, badges and outcome labels of an answer follow the response's `lang` (`turnLang`), the page's own text and errors follow the site; the debug step list shows `lang (source)`; `ask.js?v=7` -> `v=8` |
| `scripts/eval-ask-tasks.py` | the direct surface passes the task variant's language as `site_lang` (below) |
| `tests/test_aqlang_ask.py` (new, 52 tests), `tests/test_aqlang_browser.py` (new, 15 tests) | below |

Callers of `guess_lang`: one, `agent._guess_lang`, now replaced by `resolve_lang`; nothing else in `app/`, `scripts/`, `tools/`
or `tests/` used it. Callers of `run_agent`: `routers/ask.py` and the AQ-02 runner.

## How it works

- **Resolver** (`answer_check.resolve_lang`): a pure function, so the table is the test. A Romanian letter (any case, comma or
  cedilla forms) is `ro`; otherwise hint words are counted per language; equal counts (including none) are a tie. An unknown site
  value (`fr`, `EN`) is treated as absent by the resolver; the router already rejects it with 422.
- **The model** is told the language only when the site decided it: a `## Language` section ("The question does not show its
  language; the user reads the site in English. Answer in English and pass `lang` "en" to the tools.") is added to the system
  prompt of every model call of the turn, final turn and repairs included. Without it the page's warnings would follow the site
  while the model's own prose followed its guess ("PIB Cluj" on an English site would still be answered in Romanian). It is not
  added when the question or the default decided. This changes what the model sees on tie turns; **it is unmeasured with a live
  model** and is one constant (`agent.LANG_NOTE`) to remove.
- **A language the model chose** in a tool call is still respected over the turn's (AQ-04C behaviour, tested again).
- **Response**: `lang` is additive (`"ro"` | `"en"`). The page uses it so that one answer is one language: the server's warnings
  and scope text, and the page's own captions for that answer ("3 of 233 eligible entities, ranked", the `partial` badge, the
  outcome banner, link labels). Chrome that is not part of an answer (errors such as "Error 503", "Search the data directly",
  "New conversation") follows the site. An older response without `lang` falls back to the site.
- **Metrics** (`ASK_METRICS`, no content): `site_lang` (what the client sent, absent when it sent none), `lang`, `lang_source`.
  A failed request still logs `site_lang`. Asking "how many clients send it" is a log query.
- **Static build / separate API origin.** `ask.js` calls the relative `/api/ask` and `/api/ask/stream`. There is no `askApiBase`
  in the code yet (it is a task of `05-hosting-and-cutover.md` section A), and a static build answers `/ask/config` with
  `available: false`, so the page there sends nothing. The body is built once in `sendMessage` and both `fetch` calls take it, so
  an `askApiBase` change only has to replace the URL: `lang` travels in the body, not in the URL (a cross-origin POST with the
  existing `Content-Type: application/json` is unchanged). Nothing to change now; keep the browser test when it lands.
- **The AQ-02 runner.** `scripts/eval-ask-tasks.py` now passes the variant's language as the site language (each variant is `ro`
  or `en`, and the simulated user is on that site). Two prompts of the task file show no language: T13 en ("List every value in
  BIGLONG.") and T16 ro ("Acum pentru 2020."). The run passes either way (142/142 with and without the argument, controls
  unchanged), so this is fidelity rather than a fix: without the argument T13 en would fall to the Romanian default (the old
  rule read it English), and T16 ro reads Romanian either way (the old rule read it English, which was wrong for a Romanian
  site). With it each variant resolves to the language of the simulated site, as in a browser.

## Known limitation (decision for the owner)

A question in English that names a Romanian place with diacritics ("How many people live in Iași?") reads as **Romanian**,
whatever the site says: the Romanian letters are checked first, as they always were. The hint lists cannot be allowed to outvote
them (`are` is an English hint and the commonest Romanian verb: "Câți locuitori are Cluj?" would read English). Four prompts of
the task file are of this kind (T16 and T17 en "The same for Iași.", X01 pinned en, X10 en); none changes (the old code did the same) and
none fails. A proper fix is to let a diacritic count only in a word that is not a capitalized name mid-sentence; that is a
resolver change with its own table, left out because the owner's table says "RO diacritics". `test_an_english_question_that_names_a_place_with_diacritics_reads_as_romanian`
pins today's answer so a change is deliberate. An ambiguous *follow-up* ("2023") is resolved per turn from the site, not from the
earlier turns.

Also seen, not changed: the Ask page has no language switcher of its own (the visitor switches on another page and
`lens_lang` carries over), and the static text of `ask.html` (placeholder, "Conversație nouă / New conversation") is not localized.
`docs/agent-setup.md` still lists a pre-AT request/response shape; the `lang` request field and `lang` response field are
documented here only.

## Tests

| File | Covers |
|---|---|
| `test_aqlang_ask.py` (52) | the resolver table (RO diacritics incl. upper case and cedilla, Romanian hint majority, English words, tie + site `en`, tie + site `ro`, tie + none -> `ro`, English question on a Romanian site stays English, unknown site value, empty text); `guess_lang` keeps its old answers; the request field (`ro`, `en`, absent, `null` accepted; `fr`, `EN`, `""`, `ro-RO`, `1`, `["en"]`, `true` are 422 and nothing reaches the provider; the stream endpoint takes it too); the response's `lang`; a tool called without `lang` gets the resolved language (5 cases) and an explicit one still wins; warnings, scope text and the budget notice in the resolved language; a follow-up is resolved per turn; the model is told only when the site decided (every call, final turn included); metrics and the debug start event carry `lang`/`lang_source`/`site_lang`, no question or answer text; a failed turn still logs `site_lang`; the runner sends each variant's language |
| `test_aqlang_browser.py` (15 = 5 x 3 widths) | real page, real router/agent/tools, scripted model: an ambiguous question on an English site -> English warnings, scope, caption and badge; the follow-up sends `lang` and history; switching `lens_lang` and asking again gives Romanian and back (earlier answers are not rewritten); `?lang=` beats storage, `?lang=fr` reads as the default, nothing stored means Romanian; an English question on a Romanian site keeps an English answer while the page's own error text stays Romanian (and the reverse); the debug streaming path sends `lang` and shows `en (site)`. No console error, no horizontal scroll at 320, 390 and 1280 px (server port 8191) |

Do the tests detect the old behaviour? Mutations, each caught: the body without `lang` (all 15 browser tests fail), captions
following the site instead of the answer (3), storage only without `?lang=` (3), the resolver ignoring the site (18), a tie
reading English (7), the router not passing `site_lang` (4), no system-prompt line (3), the site overriding the question (12).

## Validation

Every command in the worktree, `source ~/devbox/envs/240826/bin/activate`, provider keys unset
(`env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY`), `PYTHONDONTWRITEBYTECODE=1`. Logs and screenshots are in
`.worktrees/aq-reports/ask-ui-lang/`.

| Check | Command | Result |
|---|---|---|
| Baseline suite (before the change), synthetic | `python -m pytest tests -q -p no:cacheprovider` | 1,812 passed, 85 skipped (as given) |
| AQ-02 runner, baseline `9afa711` | `TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-gen-20261012/data python scripts/eval-ask-tasks.py --quiet --report-dir <scratch>/runner-baseline` | 142 executed, 142 passed, 0 failed; controls 42 total: 30 detected, 2 known limitation, 10 resolved, 0 mismatch; verdict `blocked_by_known_limitations` |
| AQ-02 runner, after | same command | identical: 142/142, controls 30 / 2 / 0 mismatch (also identical with the runner's `site_lang` removed) |
| New tests | `python -m pytest tests/test_aqlang_ask.py tests/test_aqlang_browser.py -q` | 52 + 15 passed |
| Full suite, synthetic, after | `python -m pytest tests -q` | **1,879 passed, 85 skipped** (1,812 + the 67 new; same skips) |
| Full suite, real corpus copy, after | `TEMPO_DATA_DIR=/Users/pax/devbox/gov2/tempo-gen-20261012/data python -m pytest tests -q` | **1,963 passed, 1 skipped** (1,896 + 67) |

No existing test needed a change: none asserted English wording on an ambiguous question.

### Browser results (Chromium headless, `tests/test_aqlang_browser.py`, 5 tests per width)

| Width | Result |
|---|---|
| 320 x 640 | 5 passed: English site -> English warnings/scope/caption/badge; switch to Romanian and ask again -> Romanian; `?lang=` beats storage; English question on a Romanian site keeps English captions while errors stay Romanian; streaming path sends `lang`. No console error, no horizontal scroll |
| 390 x 800 | 5 passed, same checks |
| 1280 x 900 | 5 passed, same checks |

Screenshots of the three situations (English site + ambiguous question, Romanian site + ambiguous question, Romanian site +
English question) at the three widths: `.worktrees/aq-reports/ask-ui-lang/shots/`.

The model scripted in the browser test says nothing of any caveat, so every warning, scope line and caption comes from the tool
results and the page. What is *not* validated: a real model's answer language on a tie turn, and a hosted connector.

## Rollback

`git revert` the code commit. The request field is optional and pydantic ignores unknown fields, so a rolled-back server accepts
the new page and a rolled-back page works with the new server; either way a tie then reads English again (the old rule) or
Romanian (new server, old page). No data, no schema, no stored state. `ask.js?v=8` makes browsers fetch the new script; reverting
to `v=7` makes them fetch the old one.

## Proposed activity-history entry

See the task report; the orchestrator owns `docs/activity-history.md`.

## Follow-up — 2026-10-18: place names no longer decide the language

Owner: "How many people live in Iași?" is obviously English. `answer_check.lang_signal` now votes
instead of letting any Romanian letter win: each hint word counts one, each word written with a
Romanian letter counts two for Romanian, except a capitalized name (`Iași`, `Brașov`; an all-caps
word still counts). Hint lists are folded and slightly larger (EN: people, live, number, county,
list, every, values…; RO: locuitori, pentru, acum, orașe…). A name alone ("Iași 2023") is a tie,
so the site decides. Every AQ-02 task prompt (72, RO and EN) now resolves to its own language
without the site (`test_every_task_prompt_shows_its_own_language`); the pinned limitation test
became a table of place-name cases. AQ-02 runner on the copy: 142/142, controls 30/2/0.
Remaining limitation: a lower-case place name ("live in iași") still votes Romanian.
