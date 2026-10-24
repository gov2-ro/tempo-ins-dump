# AQ-06A completion record: Ask on a separate origin

Step 06A of [06-client-and-release.md](06-client-and-release.md) only. 06B (local release
candidate) and 06C (external clients, onboarding) are not started.
Implemented 2026-10-25 on branch `aq/06a-separate-origin`.

- Baseline: `be17677` (`fix/ask-answer-quality` head).
- No corpus change, no deployment, no DNS/hosting/production-setting change (`fly.toml` is
  untouched), no provider call, no new dependency, no limit change.

## What changed

| Area | Files | Behaviour |
|---|---|---|
| CORS | `app/config.py`, `app/main.py` | `TEMPO_CORS_ORIGINS`: comma list of bare http(s) origins; a wildcard, path, query or credential fails at startup. Unset: only local development origins (`localhost`, `127.0.0.1`, `[::1]`, any port) — the deliberate local-dev behaviour. A list replaces that default. Methods GET/HEAD/POST/OPTIONS, request header `Content-Type`, no credentials, exposes `Retry-After` and `Content-Disposition`, preflight cached 600 s. `/mcp` still bypasses CORS (its own Host/Origin gate is unchanged). Replaces `allow_origins=["*"]`. |
| Link origins | `app/services/tools/contract.py` | `public_url`: `/api/`, `/sdmx/`, `/mcp` paths stay on `TEMPO_PUBLIC_BASE_URL` (the API host, which MCP already requires); page paths go to the new `TEMPO_PUBLIC_SITE_URL` when set, else the same base. Unset both: root-relative as before. |
| Static build | `scripts/build-static.py`, `app/static/js/config.js` | `--api-origin https://…` writes `api_origin` into the build's `config.js` (bare https origin; http only for localhost; anything else is an argparse error). Omitted: the static site has no Ask, as before. |
| Ask page | `app/static/js/ask.js` (`?v=9`) | `ASK_ORIGIN` comes only from `config.js` `api_origin` (else this page's origin); a malformed value switches Ask off instead of falling back. Config, submit and the debug NDJSON stream go to `ASK_ORIGIN` with `credentials: 'omit'`; the request key is sent nowhere else (not from `?api_origin=`, chat or tool results). Relative `/api/`, `/sdmx/` links resolve on the API origin, page links on the site. A cross-origin config that cannot be read shows "service cannot be reached" with a retry; a failed/refused request, a cut stream or an unreadable body becomes `data-outcome="interrupted"`: question kept in the box, retry button, no browser error text. |
| Test app | `tests/fix08_browser_app.py` | Adds the app's own CORS middleware (from `TEMPO_CORS_ORIGINS`) and a provider call counter. Same-origin tests are unaffected. |

Two tests pinned the old behaviour and were updated with it:
`test_at03_mcp.py::test_the_apps_development_cors_never_applies_to_mcp` (asserted `*` for any
origin; now a local origin) and `test_at02_browser.py::test_busy_and_network_errors…` (asserted
the text "Network error"; now the interrupted state with its retry).

## Validation

New: `tests/test_aq06a_origins.py` (25 tests: origin parsing and refusals, default local-only
CORS on the real app, a listed site's preflight/POST/`Retry-After`, foreign sites and
look-alike hosts refused, `/mcp` excluded, link-origin split, static `--api-origin`).

New: `tests/test_aq06a_browser.py` (7 Playwright tests, Chromium). Three local origins: the API
(`127.0.0.1:8096`, the real Ask router, mocked provider, `TEMPO_CORS_ORIGINS=127.0.0.1:8095`,
`TEMPO_ASK_DEBUG=1`), the site (`:8095`) and a foreign site (`:8094`), both plain
`http.server` on a copy of `app/static` whose `config.js` names the API.

- Config, submit and follow-up (history sent, provider reached with the key) at 320/390/1280 px;
  the key appears only in the two POSTs to `:8096/api/ask`, never in a URL, the DOM or any
  request to the site; `?api_origin=` is ignored; no horizontal scroll; no console errors or
  warnings.
- Debug stream: `POST :8096/api/ask/stream`, debug panel rendered, no console errors.
- Evidence links: relative `/api/…` links open on `:8096`, `/dataset-v2.html` on `:8095`, absolute
  links unchanged.
- Foreign site: the config fetch and the POST preflight are refused by the browser, the provider
  counter does not move (the POST never ran), nothing goes to the foreign site's own `/api`, the
  page shows the unreachable notice and the interrupted message with the question kept.
  Console (expected, recorded): `ERR_CONNECTION_REFUSED` (the CDN, mapped to a closed port),
  "blocked by CORS policy: No 'Access-Control-Allow-Origin' header" for `/api/ask/config`,
  "Response to preflight request doesn't pass access control check" for `/api/ask`, and two
  `ERR_FAILED`.
- Malformed `api_origin` (`javascript:alert(1)`): Ask off, input disabled, no `/api/` request.
- Screenshots of the foreign-site states at 320 and 1280 px checked by eye (scratch, not kept).

Test-harness finding: with Playwright request interception on, Chromium's CORS preflight is
answered by Playwright and the POST reaches the server (only the response is hidden). The
foreign-site test therefore routes nothing (CDN blocked by host mapping instead) so the real
preflight decides.

`cancel`: the page has no user stop button; cancellation is the client deadline
(`AbortController`, covered by `test_a_timeout_stops_the_spinner…`) and a dropped connection,
which the server treats as a disconnect (AT-02). No new cancel control was added.

Full suite (`python -m pytest tests -q`, documented virtualenv): 2076 passed, 89 skipped (corpus/optional) in 897 s. The offline Ask task runner was not rerun: no discovery, answer-check or tool-result change, and links are identical while `TEMPO_PUBLIC_SITE_URL` is unset.

## Configuration for the planned split (not applied)

```text
Fly (api-ins.gov2.ro):  TEMPO_CORS_ORIGINS=https://ins.gov2.ro
                        TEMPO_PUBLIC_BASE_URL=https://api-ins.gov2.ro
                        TEMPO_PUBLIC_SITE_URL=https://ins.gov2.ro
Static build:           build-static.py ... --api-origin https://api-ins.gov2.ro
```

Deploying this code **without** `TEMPO_CORS_ORIGINS` ends cross-origin browser access to the
whole API (previously `*`), except from local development origins. Server-to-server and
same-origin use are unaffected. If third-party browser apps should read the public REST API,
list their origins (there is no wildcard).

## Rollback

Revert the branch's commits. Operationally: unset `TEMPO_CORS_ORIGINS`/`TEMPO_PUBLIC_SITE_URL`
and rebuild the static site without `--api-origin` (its Ask page then says Ask is unavailable).

## Remaining gates

06B (scratch-generation release candidate, Docker smoke: no Docker on this Mac → `not_run`),
06C (hosted ChatGPT/Claude clients, needs an authorized endpoint/account), AQ-01B 512 MiB run,
AQ-02 live-quality run, owner approval of production settings.
