# AQ-06 — Client integration and release evidence

**Status: 06A code-ready (2026-10-25, [record](aq-06a-record.md)); 06B local candidate
passed with image/Linux/hosted-client gates `not_run` (2026-10-25, [record](aq-06b-record.md));
06C: onboarding draft ready for owner review ([draft](06c-onboarding-draft.md)); hosted-client
tests `not_run`. External tests and production
exposure remain separate gates.** This decomposes the existing
[AT-04](../04-evaluation-and-release.md) and
[hosting runbook](../05-hosting-and-cutover.md), rather than replacing them.

## 06A — Separate-origin Ask and evidence links

Read `app/static/js/ask.js`, `app/main.py`, `app/config.py`, the generated
`config.js` path in `scripts/build-static.py`, `ask_present.py`, `tools/links.py`
and Ask browser tests. Verify current code first: do not redo changes already
landed since this specification.

Add a deployment-configured API origin with same-origin fallback. Resolve Ask
config, JSON submission and NDJSON streaming against it; resolve relative API
evidence/replay links against the API origin and site pages against their intended
site origin. Keys must never be sent to a URL supplied by a model/tool result or
an arbitrary chat/query parameter. Preserve the independent MCP Host/Origin gate.

Make allowed web origins explicit configuration instead of unrestricted production
CORS; include required preflight headers/methods and retain deliberate local-dev
behavior. A failed preflight/stream interruption must become a clear recoverable
UI state without exposing the request key or silently falling back elsewhere.

Acceptance: two local origins in Playwright, mocked provider and real request
paths; config/submit/stream/cancel/follow-up/evidence work; allowed origin passes,
foreign origin fails; credential-redaction tests pass; same-origin behavior is
unchanged. Exercise 320/390/1280 px and record console/network errors. No DNS,
hosting upload or production setting changes in this step.

## 06B — Reproducible local release candidate

Run the repository release checks against a scratch staged generation and exact
candidate code. Do not overwrite a live staging snapshot merely to test. Run
Docker smoke when available, `mcp_probe.py` with the eight-tool surface, native
SDK checks, generation-bound evidence and disable/rollback paths. Include AQ-01's
actual Linux resource profile, not only the synthetic resource-control tests.

Record image/code/task/generation identity, switches, tested limits, unresolved
gates and secret-free commands. Ask availability, public MCP availability and
static-site generation must agree with what the candidate actually contains.
No deploy/upload command belongs in an automatically executed local validation
step. Missing Docker is `not_run`, not a reason to fabricate a release pass.

## 06C — External clients and onboarding draft

Prepare a Romanian-first setup/help draft, supported examples and the exact
candidate MCP endpoint. Explain that the chat client supplies inference and INS+
serves requested data/calculations; no model key is required by the MCP server.
Disclose limitations and actual input/log retention. Do not claim INS+ receives
no conversational text: discovery can contain the full user question.

At implementation time verify official client/plugin documentation and current
account capabilities. Do not copy old guessed manifest fields or promise all
free accounts support custom connectors. A plugin/package draft is optional;
manual MCP setup is enough for the first pilot. No directory submission here.

Using an explicitly authorized reachable test endpoint/account, test ChatGPT and
Claude separately: initialize/list; one fact; tourism recipe; city rank or its
honest resource refusal; definition clarification; unsafe aggregation refusal;
follow-up; evidence link; disconnect/reconnect; cold start and timeout. Record
product/account surface, date, transport, latency and each outcome. Native Python
SDK success alone does not establish hosted-client compatibility.

## Exposure checklist and stopping point

All engineering can finish before exposure approval. Keep these distinct:

- Local code/tests and exact candidate image validated.
- AQ-01 Linux memory/deadline/mixed-load gate passed for the selected profile.
- AQ-02 live-quality gate passed for any Ask model being exposed; replay alone
  does not qualify server-funded or BYOK Ask for release.
- Hosted-client interoperability recorded for each advertised client.
- Domain, contact/privacy/retention copy and operator settings reviewed.
- Owner explicitly authorizes production settings/deployment/publication.

If an external prerequisite is absent, finish the code, draft and local evidence;
leave that gate pending and state exactly what is needed. Do not enable paid
Ask, enlarge hosting, publish a tunnel, alter DNS or submit a listing implicitly.
Prepare a rollback that disables MCP/Ask independently and restores the previous
image/static release without modifying the corpus.
