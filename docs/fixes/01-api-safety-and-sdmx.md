# FIX-01 — Safe request boundaries and consistent SDMX

Status: phase 1 (safety, items 1-4) implemented on fix/01-api-safety and merged to audit-fixes; phase 2 (items 5-7, SDMX code registry/DSD consistency) implemented on branch fix/01b-sdmx-registry, pending review/merge. Export completeness stays with FIX-04. Priority: P0 SQL injection; P1 SDMX consistency; P2 malformed
request handling. Owner: backend API. Dependencies: coordinate export policy with
FIX-04. Deliver safety and SDMX contract work as separate commits if needed.

## Problem and entry points

`app/routers/sdmx.py` interpolates startPeriod/endPeriod into SQL on an independent
DuckDB connection. Local TestClient: `/sdmx/2.1/data/INS,AMG157G?startPeriod=9999`
returned zero observations; the same parameter with `9999' OR '1'='1` returned
1,614. Only a harmless local predicate was used in the audit.

`datasets.py` accepts negative limits; `dataset_data.py` parses JSON without
validating filter values. `limit=-1` produced a live 500; filters `null`, `[1]`,
and `{"TIME_PERIOD":1}` produced local 500s. Raw query errors reach clients.

DSD IDs replace spaces with underscores and truncate labels, whereas data and
keys use parquet strings. AMG157G's last-period response had 12 dimension values
outside its declared codelists. DSD codelists are capped at 500 values and data
still uses metadata column names directly rather than the shared schema resolver.

Read `query_builder.py`, `dataset_meta.py`, `datasets.py`, `dataset_data.py`,
`sdmx.py`, `db.py`, and callers in `agent.py` and the dev MCP server.

## Required behavior

1. Parameterize user values and file paths. Resolve dataset IDs through metadata
   or a validated catalog before constructing a path. SQL identifiers must come
   from the resolved schema and use identifier quoting; never accept arbitrary
   SQL operators/functions from a request.
2. Validate annual (`YYYY`), quarterly (`YYYY-Q1`..`Q4`) and monthly (`YYYY-MM`,
   month 01..12) bounds. Reject malformed bounds and reversed ranges with 4xx.
   Keep existing legitimate period comparisons working. Define handling of
   mixed granularity explicitly; do not silently reinterpret period strings.
3. Add positive lower bounds to list/data/related/lastN limits. Validate filters
   as an object of column names to arrays of supported scalar values. Reject
   wrong shapes, non-scalar values, unsupported columns and malformed group_by
   rather than silently ignoring a user's constraint. Preserve valid clients.
4. Keep connections within configured resource limits and close request-owned
   cursors/connections in all success/error paths. Log internal exceptions with
   context; return stable error codes/messages without SQL or absolute paths.
5. Define a single SDMX code registry for data, keys and DSD. Use stable IDs derived
   from canonical codes/metadata, not lossy truncated labels. Labels remain
   separate multilingual text. TIME_PERIOD uses normalized periods and must be
   represented consistently as a time dimension; emitted enumerated values must
   exist in their declared codelists. Validate actual SDMX structure/element types
   with a schema or a standards-aware parser, not only string assertions.
6. Handle all dimensions without a 500-value cutoff; prevent code collisions.
   Build XML through an XML serializer with proper escaping. Reuse
   resolve_parquet_schema/adapt_to_parquet for metadata column drift.
7. Preserve `/sdmx/2.1/` routes and existing valid label-key requests where mapping
   is unambiguous. Prefer canonical code keys in docs; reject ambiguous legacy
   keys explicitly. Do not rename stored parquet values merely to fix the DSD.

## Acceptance tests

- Injection predicates in both period parameters never alter query meaning;
  malformed inputs return 4xx. Do not probe production with attack payloads.
- Apostrophes in legitimate filter values work as literals; metadata values with
  quotes and XML special characters round-trip without corrupting SQL/XML.
- Every invalid example above returns a documented 4xx, including zero/negative
  limits and object-valued filter members. Unknown datasets return 404.
- A synthetic dataset with spaces, punctuation, long colliding labels, >500
  options, monthly periods and stale metadata columns produces consistent DSD and
  data. Parsing the DSD then querying an emitted key returns the matching rows.
- Connections are closed on failure; ordinary API output does not leak paths.
- Existing callers and no-key wildcard requests remain functional. SDMX export
  completeness is accepted under FIX-04, not silently considered solved here.

## Scope and completion evidence

Do not add authentication or change statistical aggregation in this package.
Document the canonical/legacy key compatibility policy and new 4xx responses in
SDMX-API.md and CURRENT_STATE.md. Provide focused test output and a local contract
round-trip before marking complete. The safety commit must not wait for the full
code-registry migration.
