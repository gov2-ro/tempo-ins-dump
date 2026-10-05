# FIX-04 — Complete exports and explicit delivery limits

Status: implemented on fix/04-complete-exports and merged to audit-fixes (CSV streaming, XLSX policy, SDMX complete-or-reject, UI preflight); not deployed. Priority: P1. Owner: download/SDMX endpoints.
Dependencies: FIX-01 request validation; coordinate common query-boundary changes.

## Problem

`download_dataset()` applies MAX_DATA_ROWS (a chart cap) to CSV and XLSX without
warning. Live POP107A returns 50,000 rows from 485,825. SDMX has an unconditional
LIMIT 50000. A successfully downloaded file therefore appears complete when it is
not. Chart windowing and dropping incomplete edge periods cannot solve raw exports.

Read `dataset_data.py`, `sdmx.py`, `query_builder.py`, download handlers in
`explore-app.js` and `dashboard-v2.js`, and API filter/language behavior.

## Required behavior

- CSV means all raw observations matching the validated explicit filters. It does
  not inherit automatic chart windows or drop edge periods. Stream batches with
  bounded memory, deterministic ordering and proper CSV escaping/Unicode.
- Keep existing download URLs and filenames. Return completeness metadata such
  as dataset generation, matching row count and exported row count where known.
  Do not rely on a header alone to disguise a capped file as a complete export.
- XLSX uses a write-only workbook/temp file with bounded memory. Respect Excel's
  worksheet capacity (1,048,576 rows including header). If a dataset exceeds the
  supported XLSX policy, reject before sending headers with a clear 4xx and offer
  complete CSV. Do not quietly discard rows to fit a sheet. Document cleanup and
  client-disconnect behavior for temporary files.
- SDMX either delivers the complete explicitly requested selection or rejects an
  over-budget request before returning a misleading complete-looking document.
  Preserve lastN/start/end/key filters. FIX-01 owns the code/DSD contract.
- Separate chart query limits from export limits. If synchronous full CSV cannot
  fit the service's measured resource envelope, add an explicit complete-file
  artifact/pagination flow; do not introduce a fake full-download button. Explain
  any new flow before implementation and keep ordinary small downloads simple.
- Export values/headers retain canonical schema and validated language semantics.
  Define handling of strings starting with Excel formula characters for spreadsheet
  safety without silently altering canonical raw numeric observations. Missing
  datasets/filters receive useful 4xx responses, not query/path exceptions.

## Acceptance tests

1. A temporary fixture with >50,000 observations exports every matching row as
   CSV and supported XLSX. Parse the files and compare row counts, keys and values
   to the source selection; test filters and multiple periods, not just file size.
2. Validate quoted/newline/Unicode labels, NULL values and numeric types. Confirm
   legitimate translation changes labels without changing row identity/count.
3. Test exact worksheet boundary and overflow with a streaming/generated fixture;
   assert the documented rejection or sheet policy, with no silent truncation.
4. Read batches and measure bounded memory on a representative large fixture.
   Disconnect/error cleanup must release cursors and temporary files.
5. SDMX handles a >50k selection by the documented complete/reject contract, and
   small selections remain valid and consistent with their DSD.
6. UI download actions communicate the export selection, completeness and any
   rejection. Active chart sampling does not change the raw export accidentally.

Read-only real check: export filtered POP107A and compare to source SQL, then
measure a complete local export. Do not run concurrent large-download load tests
against production. Test the implementation under the deployed memory envelope
before changing the configured limit.

## Completion evidence

Document supported formats, limits and completeness fields in CURRENT_STATE.md
and SDMX-API.md. Provide source/export counts and peak-memory evidence. Leave chart
row caps in place; fixing export completeness does not authorize unbounded charts.
