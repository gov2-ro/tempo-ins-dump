# FIX-08 — Ask request budgets and explicit persistence

Status: not started. Priority: P2; complete before enabling a funded public Ask
service. Owner: Ask/agent/chat UI. Dependencies: FIX-01 validation and FIX-02 safe
data-tool semantics. No paid model calls are needed to implement acceptance tests.

## Problem and entry points

AskRequest.history is an unbounded list of arbitrary dictionaries. Provider/model
are unrestricted. ASK_MAX_TOOL_CALLS limits loop iterations but every response
may dispatch several tools. No application-level request/concurrency budget exists.
Fly config enables logging questions, answers and tool traces. API keys persist in
localStorage on a page loading third-party scripts; current UI should explicitly
explain persistence rather than imply a session-only secret.

Read ask.py, agent.py, llm_client.py, config.py, fly.toml, ask.html, ask.js,
ask-models.json and docs/agent-setup.md.

## Required behavior

1. Validate bounded history turns, content size/total request size, permitted roles
   and supported scalar/block structures. Clients cannot inject system/developer
   turns or arbitrary internal tool messages. Use server-owned conversation state
   if tool history is needed; otherwise accept only the user/assistant contract.
2. Validate provider/model against a documented configurable allowlist. Keep BYOK
   functional and separate user-key calls from server-funded calls. Unknown
   providers must not silently fall through to another provider.
3. Budget total dispatched tools, model iterations, elapsed request time and
   concurrent agent requests independently. Count every tool in a multi-tool
   response. Stop cleanly before the next forbidden call; return a useful bounded
   partial/unavailable result. Expose configurable defaults tested under the
   deployment memory envelope; do not add a distributed queue without evidence.
4. Use explicit provider timeouts/retry limits. Return stable errors without raw
   provider exceptions or secrets. Prefer 429/503 with a clear retry signal when
   a request/concurrency budget is exhausted. Preserve valid conversation behavior.
5. Default keys to session/in-memory storage; persistent storage requires an
   explicit opt-in with clear text and a working clear action. Do not migrate
   previously stored keys into logs or expose them in DOM diagnostics. Tell users
   keys transit the server for provider calls; do not claim they stay browser-only.
6. Default chat content logging off. If enabled, disclose the behavior before
   submission and document storage/retention/access. Keep operational metrics
   separate from questions/answers/tool payloads, redact credentials recursively,
   and avoid putting keys or sensitive provider headers in errors/traces.
7. Consume FIX-02's tool outcomes so unavailable/approximate data is reflected in
   the answer and citations. A model answer without a valid query must not claim
   an observed value. Keep deterministic tool validation outside model prompts.

## Acceptance tests

- Reject oversized/invalid history, forbidden roles and unsupported providers
  before any mocked provider request. Valid RO/EN multi-turn/BYOK cases still work.
- Mock one response with many tool calls; total tools never exceed the budget.
  Mock stalls/retries and concurrent requests; deadlines and concurrency bounds
  terminate/reject predictably without resource leaks.
- Capture logs and errors containing a sentinel fake key nested in tool/provider
  data; no sentinel appears. Content logging is off by default and opt-in behavior
  matches the documented retention/storage contract.
- Browser default submission does not persist keys in localStorage; explicit
  opt-in persists, clearing removes old entries, and disclosure is visible.
- Mock unsafe/approximate data results; the final response preserves warnings and
  does not silently relabel an approximation as an official statistic.

## Completion evidence

Provide mocked provider/tool tests, browser persistence tests, configuration docs
and a clear migration policy for existing localStorage keys. Do not test with a
real key, enable Ask funding, or deploy the service as part of this package.
