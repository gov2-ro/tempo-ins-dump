# Shared analytical tool contract

## Status and scope

**AT-00: proposed `tempo-tools/1`, 2026-10-15; implemented by AT-01 with the amendments listed in [at-01-record.md](at-01-record.md).** This is a transport-neutral contract for
the new analytical tools. Preserve the existing `tempo-query/1` REST response;
carry its aggregation/quality/selection evidence inside the new envelope rather
than renaming existing fields. Both Ask and public MCP use the same tool service.
Python types/Pydantic models may enforce it; do not require a new framework.

## Tool inputs and result envelope

Expose exactly these seven logical tool names in public MCP v1:

| Name | Purpose | Required inputs | Optional inputs/defaults |
|---|---|---|---|
| `discover_indicators` | Concept-first discovery and alternatives | `query` | `lang=ro`, `limit=5` |
| `describe_dataset` | Compact schema, scope, actual period bounds and quality | `dataset` | `lang=ro` |
| `find_dimension_values` | Search/page actual values | `dataset`, `column` | `query=""`, `limit=20`, `offset=0` |
| `query_data` | One validated, bounded data selection | `dataset` | `filters={}`, `group_by=[]`, `limit=100`, `approximate=false`, `lang=ro` |
| `compare_periods` | Per-entity changes and rankings for explicit intervals | `dataset`, `entity_columns`, `intervals` | `filters={}`, `metric=absolute`, `order=asc`, `top_k=20`, `lang=ro` |
| `run_recipe` | Run an existing reviewed recipe | `recipe` | `year=null`, `areas=null`, `lang=ro` |
| `get_evidence_links` | Exact selection/evidence/share links | `selection`, `generation_id` | `lang=ro` |

Typed objects/arrays go over the wire; callers must not JSON-encode filters into
strings. Use `additionalProperties: false` on tool argument objects where the
model library supports it; validate unknown keys in the service regardless.

Input bounds (initial defaults, tunable downward for production):

- `lang`: `ro|en`; `query`: at most 200 characters.
- `dataset`: an existing corpus code, at most 128 characters; reject path syntax,
  NULs and traversal. Resolve files by code within the configured corpus root.
- `filters`: at most 16 existing dimension columns, at most 100 string values per
  column, at most 1,000 values overall. Empty lists impose no filter, matching the
  current shared service; provenance must report that normalization explicitly.
- `group_by`/`entity_columns`: unique existing dimension columns, at most 8.
  The observation-value column is never a dimension or filter identifier.
- `limit`: query 1–200, discovery 1–10, option search 1–100; booleans are not ints.
  Option offset is nonnegative. `top_k` is 1–100; intervals number 1–4.
- `year`: an exact four-digit year or null; no implicit nearest-year fallback.
- `areas`: null or up to 60 exact supported area values. Do not fuzzily join them.
- Logical tool arguments: maximum 16 KiB UTF-8 JSON. Enforce before expensive
  metadata/DB work, independently of transport body limits.

Every invocation returns the envelope below, including failures. Fields named
here are required unless marked nullable; tool-specific fields live in `data`.
Never serialize NaN/Infinity. JSON null means unavailable, never zero.

```json
{
  "contract": "tempo-tools/1",
  "tool": "query_data",
  "status": "ok",
  "reason": null,
  "message": "Selection returned",
  "data": {"columns": ["REF_AREA", "OBS_VALUE"], "rows": [["A", 100]]},
  "provenance": {
    "generation": {"id": "fixture-generation", "status": "present"},
    "sources": [{"dataset": "COUNTX", "unit": "persons", "definition": "Fixture population"}],
    "selection": {"kind": "dataset", "dataset": "COUNTX", "filters": {"TIME_PERIOD": ["2024"]}, "group_by": ["REF_AREA"], "approximate": false},
    "effective_selection": {"filters": {"TIME_PERIOD": ["2024"]}, "levels": {}},
    "aggregation": {},
    "quality": {},
    "scope": {"description": "All ages", "domain_complete": true, "limitations": []}
  },
  "limits": {
    "returned_rows": 1,
    "total_rows": 1,
    "preview_truncated": false,
    "source_complete": true,
    "time_windowed": false,
    "partial_period_dropped": null
  },
  "warnings": [],
  "recovery": []
}
```

`provenance` is present with empty sources/null selection when the tool has no
data source yet (e.g. invalid input). Describe the generation as missing/stale
when that is the actual state; do not invent an id or claim certification.
Definition/unit/period/completeness fields cannot be omitted just to fit a budget.
Source entries also include the metric name, source update date when known,
app dataset URL, and any definition/coverage/break notes affecting interpretation.
Definitions may be faithful short summaries with a link to the full source text.
`warnings` contains `{code, message}` objects (optional `subject`); adapters may
render their messages into the existing Ask string-warning list. `limits` is
present for metadata tools too: `returned_rows=0`, `total_rows=null` and
`source_complete=null` when there is no analytical table to certify.

Tool-specific `data` fields are the adapter-facing minimum below. Reuse native
substructures where possible, retaining the names listed here; compatible
additional fields are allowed within the budget.

| Tool | Minimum `data` shape |
|---|---|
| `discover_indicators` | `interpretation` (parsed place/level/period/latest and ambiguities), `concepts` (id/name/definition/unit/coverage/recipe/candidate datasets), `families`, `choices` when clarification is needed |
| `describe_dataset` | `dataset`, `name`, `definition`, `measure`, `unit`, `time` (column/first/last/frequency), `dimensions` (column/label/type/option_count/examples/values_truncated/lookup arguments), `parent`, `splits`, `notes` |
| `find_dimension_values` | `dataset`, `column`, `values` (exact value plus label), `offset`, `next_offset`, `total` (nullable), `values_truncated`, `period_bounds` (nullable) |
| `query_data` | `columns`, `rows` (arrays matching column order), `column_labels`, `selection` (native empty/missing-values diagnostics, nullable) |
| `compare_periods` | `dataset`, `entity_columns`, `metric`, `order`, `intervals` (from/to/rows/eligible_count/excluded_count/excluded/exclusions_truncated); rows use entity/from_value/to_value/absolute/percent/rank |
| `run_recipe` | `recipe` (id/version/name/definition/formula/value_source), actual `year`, bounded `rows`, `excluded`, `exclusion_counts`, `exclusions_truncated`, bounded `check`; no raw inputs |
| `get_evidence_links` | normalized `selection`, `links` (kind/url/description/generation_mode), with `generation_mode=live_rerun|expected_generation` |

Arrays may be empty on a refusal. Optional unknown facts use null, not guessed
defaults. Exact JSON/Python output models and representative fixtures are an
AT-01 deliverable before the adapters are wired. Resolve native shape differences
once in the shared service, not separately in Ask and MCP.

Status meanings:

| Status | Meaning |
|---|---|
| `ok` | The requested supported operation succeeded with its scope and limits stated |
| `partial` | A result is usable only for an explicitly narrower domain or eligible subset; exclusions/limitations are visible |
| `needs_clarification` | A definition/place/period choice affects the answer; return choices, no guessed headline |
| `unavailable` | Statistically unsafe, unsupported, over-budget or stale-generation operation; return no invented value |
| `error` | Malformed input, unknown identifier or execution/provider failure, with a stable public reason |

Presentation truncation alone need not make an analytically complete requested
top-K answer partial. A preview of a capped raw result never establishes a total
or an exhaustive ranking. `total_rows` is null if unknown; do not run an unbounded
COUNT merely to fill it. Retain native `truncated`, time-window and dropped-period
flags when adapting `tempo-query/1`.

## Statistical and identity invariants

1. All data selections use `data_query.run_query`; all collapsed dimensions use
   aggregation policy and `grain_guard`. Never select SUM/AVG in an adapter.
2. Refused/conflicting/duplicate-key inputs cannot be recovered by downloading
   raw rows and summing them in Python or asking the model to do so.
3. Registered versus ILO unemployment, resident versus domicile population,
   reference dates, city versus county, and unit/price bases remain distinct.
   Ambiguous natural-language discovery must present the consequential choices.
4. Source Total cells remain authoritative where the existing recipe serves
   them; reconstructed values are labelled cross-checks. Do not replace the
   published value because a reconstruction happens to look more convenient.
5. Statistical disjointness does not prove exhaustive population coverage.
   Derive/report child scope from source metadata, actual values and verified
   levels. A 0–84-only child cannot satisfy an all-ages population request. If
   exhaustiveness cannot be established, `domain_complete` is null and discovery
   must not promote it as a verified all-population total.
6. Pin to one verified hierarchy/age level. Preserve effective pins and levels.
   A known source-total contradiction must not be hidden by changing interface.
   Apply source checks only to the generation/period/scope they actually verify;
   a matrix-wide latest check cannot certify every historical filtered slice.
7. Explicit periods/places are never silently replaced, widened or imputed.
   Missing, zero, suppressed and excluded are distinct states. Approximation is
   off unless explicitly requested, and must remain labelled in every adapter.
8. Comparisons use the same source definition, unit, geography key and period
   frequency. Group/join by the full entity key, not just a locality display name.
   Expose known administrative/series breaks; do not assert boundary continuity
   from matching labels alone. Unresolved identity collisions are refused.
9. Generation is captured before execution and checked again before return.
   A generation change invalidates the calculation/cache and returns
   `generation_changed`; no mixing inputs from two generations. Public certified
   analytical answers require present generation evidence. Missing/stale evidence
   can still permit metadata discovery, with its actual quality status.
10. Client-supplied result/context objects never establish a verification verdict,
    source value, authorization or approximation consent. Revalidate requests.

Retain native statistical refusal codes. New scope metadata must be shared with
REST consumers where relevant, additively; do not fix an unsafe claim only inside
an MCP-specific formatter. No corpus rewrite is required by this contract.

## Result budgets and provenance

The logical envelope is at most **32 KiB UTF-8 serialized JSON**, with at most
200 model-visible table rows. These are initial budgets, not claims that 200
rows always fit. Remove optional samples/long descriptive text first; shorten
the preview further if needed, preserving required provenance and warnings.
Never cut JSON text mid-string, silently drop entities, or remove a safety note.
If even the required provenance for a large request cannot fit, do not execute
or return a misleading data preview. Return `response_budget` with no data, null
selection, a bounded request summary/hash and a narrowing suggestion. Such a
failure is not a reproducible analytical result and must not offer a shortened
selection as its evidence link.

A shortened result contains explicit preview/completeness flags and a canonical
selection plus full-data/evidence links where supported. Do not add a durable
result store or job system merely for pagination. Pure tools are stateless in
v1: callers can repeat the canonical selection. The Ask adapter may keep bounded
conversation selection state as specified in AT-02.

Internal analytical sources may use the existing 50,000-result-row service cap,
but cannot derive an exhaustive result from `truncated`, `time_windowed` or
`partial_period_dropped` input. Count/scan/runtime budgets are independent of
returned rows; AT-03 sets the public execution gate. Download endpoints retain
their own complete-or-refuse contracts and export concurrency limits.

Canonical selections resolve implicit recipe `year=null` to the actual result
year before creating citations/evidence. Keep the original latest-year intent in
requested-selection metadata, not as an unfixed snapshot coordinate.

Evidence/share links distinguish a live rerun from a snapshot. `generation_id`
is a precondition for preparing evidence, not a promise that an old generation
will remain hosted. If it differs from the served generation, return
`generation_changed` rather than linking current data as if it were the old
answer. Bundle generation must recheck the precondition at download time too.

## Errors and recovery

Errors contain no SQL, filesystem path, stack, key or raw provider exception.
Reuse existing reason codes and add these only where needed:

| Reason | Status | Required recovery |
|---|---|---|
| `ambiguous_definition`, `ambiguous_place` | `needs_clarification` | Bounded labelled choices and explicit selections |
| `invalid_input`, `unknown_dataset`, `unknown_column` | `error` | Exact corrective instruction; no ignored parameter |
| `period_unavailable`, `slice_value_missing` | `unavailable` | Actual bounds/search tool call; preserve requested period |
| `incomplete_domain` | `partial` or `unavailable` | Scope restriction and a validated complete alternative, if available |
| `unsupported_measure`, `unsupported_frequency`, `identity_ambiguous` | `unavailable` | Explain which prerequisite is missing |
| `source_incomplete` | `unavailable` | Narrow selection; never rank a capped input |
| `generation_unverified`, `generation_changed` | `unavailable` | Refresh/re-run; no stale certification |
| `busy`, `query_timeout`, `query_budget`, `response_budget` | `unavailable` | Bounded retry delay or narrower query |
| `link_too_long` | `unavailable` | Narrow the selection; never remove filters from a link silently |
| `execution_failed` | `error` | Request reference for diagnosis, no internals |

`recovery` is an array of at most three objects: `{kind, message, tool, arguments}`.
`kind` is `clarify|tool_call|narrow|retry`; `tool`/`arguments` are null where not
applicable. Tool-call suggestions must validate against tool schemas. A suggested
alternative is a candidate, not an executed or verified answer. Generic advice
to query raw rows is prohibited after a grain/overlap/domain refusal.

Map adapter errors deliberately: malformed MCP argument/protocol requests use
the SDK's protocol errors; valid calls with execution errors use `isError=true`
and the envelope. Statistical `unavailable`/clarification results are ordinary
structured tool outcomes (`isError=false`), not server exceptions. HTTP adapters
keep their documented status codes and include a request id for server faults.

## Acceptance checks

- Validate every tool's input/output against its published schemas, including
  negative/oversized values and unknown keys; no tool executes SQL on rejection.
- The same canonical query yields identical values, effective filters, verdict,
  scope and generation through service/Ask/MCP/REST, allowing transport wrappers
  and declared previews. Test legacy-column translation as well as SDMX files.
- All numerical fixtures in AT-01 pass. Refused inputs never become successful
  totals in another adapter. No-source, empty and zero are observably different.
- A non-ASCII response is bounded by UTF-8 bytes, not Python/JS string length.
  Structured MCP output and its text fallback contain the same complete envelope.
- Replaying a selection against a different generation refuses its old evidence
  precondition. Link generation never fetches arbitrary URLs or executes a query
  to a caller-chosen destination.
- The implementation may add compatible optional fields, but record any proposed
  change to these input/status/limit meanings before integration.

