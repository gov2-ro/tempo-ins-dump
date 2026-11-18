# AQ-08 — Chart hints and chart links in tool results (brief)

Owner decisions, 2026-11-18:
- Tool results carry a **chart hint**. MCP clients (Claude Desktop, ChatGPT) and the site's Ask
  page draw the chart from it. The server never renders images.
- The **chart link** opens the existing dataset page (`dataset-v2.html`) with the selection
  preselected. It re-computes real data, so it also works on the static site.
- No page draws numbers carried in its URL: anyone could craft such a link with invented figures
  on our domain.
- Out of scope: MCP Apps (interactive UI inside the client; backlog), the three Ask failures of
  2026-11-18 (backlog), any deploy.

Read first: `AGENTS.md`, `docs/plans/ask-and-public-mcp/00-tool-contract.md`,
`app/services/tools/contract.py` (`envelope`, `dataset_page`, `public_url`),
`app/services/tools/links.py`, `app/services/ask_present.py`, `app/services/agent.py`
(`_chart_spec`), `app/static/js/ask.js` (`renderChart`, `chartSeries`).

## 1. Chart hint: `data.chart`

Add an optional `data.chart` object to the `ok` and `partial` results of `query_data`,
`rank_entities`, `compare_periods` and the recipe tool. It is `null` or absent when no honest
chart exists. Proposed shape (adjust names to the contract style, and record what you chose):

```json
{"type": "bar", "x": "<field>", "y": "<field>", "series": null, "sort": "desc",
 "unit": "Numar persoane", "title": "<RO or EN, from messages.py>",
 "url": "<chart link, section 2>"}
```

- `x`, `y` and `series` name fields that already exist in the result rows. The hint never copies
  rows, so it stays small. Describe how a client reads nested fields, for example the
  `entity` object in `rank_entities` and `compare_periods` rows.
- Rules:
  - `rank_entities` → `bar`; `x` = the entity label; `y` = the ranked value; `sort` = the
    requested order.
  - `compare_periods` → `bar`; `y` = the requested metric (`percent` or `absolute`).
    With more than one interval, use one series per interval or return null. Choose one and
    record the choice.
  - `query_data` with more than one period and at most one other varying column → `line`
    (`x` = `TIME_PERIOD`; `series` = that other column, or null). One period and one
    entity column → `bar`. Anything else → null. Keep the rule in `ask_present.py`
    ("two geographic series are never merged").
  - Recipe tool: `bar` per area when the result is one value per area; otherwise null.
- Do not add a chart to a refused or unavailable result.
- The result must stay under the 32 KiB cap. Measure the added bytes on the largest case.
- Prose strings (title, any note) come from `tools/messages.py` in RO and EN. Codes and field
  names never change with `lang`.

## 2. Chart link: `data.chart.url`

The link is `contract.dataset_page(code, lang, filters)`, with the selection's filters.
Include the period: the single year for `rank_entities`, the end year of the interval for
`compare_periods`. Add the levels (`g=`) when the selection pins a level.

- Check whether `dataset-v2.html` can open a bar view in a stable way. Tile ids are built at
  run time, so a `t=` preset may be fragile. If no stable way exists, ship the link with filters
  only and report that.
- The description must say what the page shows. For `compare_periods`, the page shows the
  values for the year, not the computed change.
- Follow the `links.py` rules: trusted origin only, never shortened, refused over 4 KiB.

## 3. Ask page

- `agent.py`/`ask_present.py`: when the displayed result has `data.chart`, the chart comes from
  it. Today only a `query_data` table gets a chart (`chart_dataset`). Keep the current
  `query_data` chart unless the hint covers it as well. Explain any difference.
- `ask.js`: draw a bar chart from the hint, with entity labels on the axis and sorted as the
  hint says. Add the link under the chart, labelled from the UI strings (RO and EN).
- The static site serves `ask.js`, so the static parity tests must still pass.

## 4. Verification

- Unit tests on synthetic fixtures: each tool's hint (type, fields, sort, null cases), the link
  (filters, period, refused when too long) and the result size.
- An Ask presenter test: a ranking trace produces a chart from the hint.
- `python -m pytest tests -q`, the full suite, once. Never run two full suites in parallel.
- Run `scripts/serve-mcp-test.sh` and then `scripts/mcp_probe.py http://127.0.0.1:8090 POP112A_grupe`.
  Also call `rank_entities` once through the MCP and show the hint.
- Smoke `ask.html` locally in a browser with Playwright. If no provider key is available, render
  a recorded ranking response; check the console and the network tab.

## Stop and ask when

- The change needs a contract version bump (`tempo-tools/3`), or an output schema change that is
  not purely additive for MCP clients.
- A rule above produces a misleading chart for a real dataset, for example a sum where
  `grain_guard` or the aggregation policy refuses one.
- Anything outside `app/services/tools/`, `app/services/ask_present.py`, `app/services/agent.py`,
  `app/static/js/ask.js`, `app/static/css/` (Ask styles), `tests/` and this plan folder.

## Deliverables

Code, tests, `docs/plans/ask-and-public-mcp/remaining/aq-08-record.md` (what you measured, chose
and assumed), and an entry in `docs/activity-history.md`. Commit on the branch. Do not deploy.
