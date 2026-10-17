"""One-year entity ranking, after the shared query has validated every input row.

Top K limits presentation only. City membership uses the SIRUTA option catalogue
of INS GOS102A, not a substring test on population labels or model arithmetic.
"""
from __future__ import annotations

import math
import re

from app.services import data_query, dataset_meta, period_changes
from app.services.tools import contract as C

CITY_CATALOGUE = "GOS102A"


def _refuse(reason, message, provenance=None):
    raise C.ToolFailure("unavailable", reason, message, provenance=provenance)


def city_codes(conn) -> dict[str, str]:
    rows = conn.execute("""
        SELECT dopt.option_label FROM dimensions d JOIN dimension_options dopt USING (dimension_id)
        WHERE d.matrix_code = ? AND d.dim_column_name = 'REF_AREA_2'
    """, [CITY_CATALOGUE]).fetchall()
    out = {}
    for (label,) in rows:
        m = re.fullmatch(r"\s*(\d+)\s+((?:MUNICIPIUL|ORAS(?:UL)?)\s+.+)", label, re.I)
        if m:
            key = str(int(m[1]))
            if key in out and out[key] != label.strip():
                _refuse("identity_ambiguous", "The city catalogue repeats a SIRUTA key with different labels.")
            out[key] = label.strip()
    if not out:
        _refuse("classification_unavailable", "INS GOS102A's SIRUTA municipality/town catalogue is unavailable.")
    return out


def _siruta(value):
    m = re.match(r"^(\d+)\s+\S", str(value).strip())
    return str(int(m[1])) if m else None


def rank_entities(args, ctx):
    from app import config
    from app.services.query_builder import resolve_parquet_schema, to_sdmx_name

    ctx.require_present_generation("rank_entities")
    code = args.dataset
    actx = dataset_meta.get_aggregation_context(ctx.conn, code)
    if actx is None:
        raise C.query_failure(data_query.QueryError(404, f"Dataset {code} not found"), ctx, code)
    dims = {d["dim_column_name"]: d for d in actx["dimensions"]}
    if actx.get("measure") != "additive":
        _refuse("unsupported_measure", "This ranking supports additive measures only; use a reviewed recipe for rates.")
    if "TIME_PERIOD" not in dims or dims["TIME_PERIOD"].get("dim_type") != "time":
        _refuse("unsupported_frequency", "An annual observation period is required.")
    schema = resolve_parquet_schema(ctx.conn, code)
    if any(to_sdmx_name(schema, c) == "TIME_PERIOD" for c in args.filters):
        raise C.ToolFailure("error", "invalid_input", "Use year instead of a time filter.")
    if any(c not in dims or c == "TIME_PERIOD" for c in args.entity_columns):
        raise C.ToolFailure("error", "invalid_input", "entity_columns must name existing non-time dimensions.")
    keys, _ = period_changes._key_columns(actx, args.entity_columns)
    if len(keys) > 8:
        raise C.ToolFailure("error", "invalid_input", "The full entity key exceeds eight columns.")
    if args.entity_class == "cities" and "REF_AREA_2" not in keys:
        raise C.ToolFailure("error", "invalid_input", "Cities require REF_AREA_2 with SIRUTA locality keys.")
    periods, _ = period_changes._periods(ctx.conn, code, "TIME_PERIOD", ctx)
    year = args.year or max(periods)
    if year not in periods:
        _refuse("period_unavailable", f"No observations for {year}; no nearby year was substituted.")
    filters = {c: list(v) for c, v in args.filters.items() if v}
    filters["TIME_PERIOD"] = [periods[year]]
    query = {"dataset": code, "filters": filters, "group_by": keys + ["TIME_PERIOD"], "approximate": False}
    try:
        res = data_query.run_query(ctx.conn, code, filters, query["group_by"], config.MAX_DATA_ROWS)
    except data_query.QueryError as e:
        raise C.query_failure(e, ctx, code)
    prov = C.query_provenance(ctx, code, query, res)
    selection = {**args.model_dump(), "year": year, "kind": "entity_ranking"}
    prov.update(selection=selection, source_query=query)
    agg = res.get("aggregation") or {}
    if res.get("unavailable"):
        _refuse(agg.get("reason") or "aggregation_unavailable", "The shared query refused the ranking input.", prov)
    if res.get("truncated") or res.get("time_windowed") or res.get("partial_period_dropped") is not None:
        _refuse("source_incomplete", "No ranking was computed from a capped or windowed input; narrow the selection.", prov)
    if agg.get("outcome") == "approximation":
        _refuse("unsupported_measure", "An approximate aggregation is not a ranking input.", prov)
    if any(w.get("code") == "mixed_grain_on_axis" for w in agg.get("warnings") or []):
        _refuse("overlapping_levels", "Choose a single entity level before ranking.", prov)
    cols = res["columns"]
    table = {}
    for row in res["rows"]:
        key = tuple(row[cols.index(c)] for c in keys)
        if any(v is None or not str(v).strip() for v in key):
            _refuse("identity_ambiguous", "An entity has an empty key; no ranking was computed.", prov)
        if key in table:
            _refuse("duplicate_keys", "More than one value exists for an entity; no ranking was computed.", prov)
        table[key] = row[cols.index("OBS_VALUE")]
    aggregates = period_changes._aggregate_keys({(k, year): v for k, v in table.items()}, keys, actx)
    catalogue = city_codes(ctx.conn) if args.entity_class == "cities" else None
    if catalogue:
        prov["sources"].append({**C.source_entry(ctx.conn, CITY_CATALOGUE, ctx.lang), "role": "entity_classification"})
        prov["classification"] = {"dataset": CITY_CATALOGUE, "key": "SIRUTA", "class": "municipalities_and_towns",
                                  "temporal_status": "catalogue_not_historical"}
    rows, excluded, outside_class, seen_ids = [], [], 0, set()
    for key, value in table.items():
        entity = dict(zip(keys, key))
        if key in aggregates:
            outside_class += 1
            continue
        if catalogue:
            siruta = _siruta(entity["REF_AREA_2"])
            if siruta is None:
                _refuse("identity_ambiguous", "Locality values must carry exact SIRUTA keys; names are not joined.", prov)
            if siruta not in catalogue:
                outside_class += 1
                continue
            if siruta in seen_ids:
                _refuse("identity_ambiguous", "One city SIRUTA key appears under multiple entities.", prov)
            seen_ids.add(siruta)
        if value is None or not math.isfinite(float(value)):
            excluded.append({"entity": entity, "reason": "value_missing"})
            continue
        rows.append({"entity": entity, "value": float(value)})
    # A national city query discloses catalogue cities with no observation. With
    # an entity filter we cannot infer their county from a locality-only catalogue.
    if catalogue and not any(filters.get(k) for k in keys):
        excluded += [{"entity": {"REF_AREA_2": catalogue[k]}, "reason": "no_observation"}
                     for k in sorted(set(catalogue) - seen_ids)]
    rows.sort(key=lambda r: ((-1 if args.order == "desc" else 1) * r["value"],
                             tuple(str(r["entity"][k]) for k in keys)))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    scope = prov["scope"]
    warnings = []
    if catalogue:
        warnings.append(C.warning("classification_reference", "Cities are municipalities and towns in INS GOS102A's SIRUTA catalogue; historical changes of UAT class are not tracked."))
    if excluded:
        warnings.append(C.warning("entities_excluded", f"{len(excluded)} entities lack a finite observation; they were not assigned zero."))
    if scope.get("domain_complete") is not True:
        warnings.append(C.warning("incomplete_domain" if scope.get("domain_complete") is False else "unverified_total",
                                  scope.get("description") or "The collapsed domain's completeness is unverified; do not claim an official complete total."))
    partial = bool(excluded) or scope.get("domain_complete") is not True
    status = "partial" if partial else "ok"
    reason = "incomplete_domain" if scope.get("domain_complete") is False else "unverified_total" if scope.get("domain_complete") is None else None
    if not rows:
        status, reason = "unavailable", "no_eligible_entities"
    data = {"dataset": code, "entity_columns": keys, "year": year, "requested_year": args.year,
            "unit": prov["sources"][0].get("unit"), "entity_class": args.entity_class,
            "order": args.order, "top_k": args.top_k, "rows": rows[:args.top_k],
            "eligible_count": len(rows), "excluded_count": len(excluded), "excluded": excluded[:20],
            "exclusions_truncated": len(excluded) > 20, "outside_class_count": outside_class}
    return C.envelope("rank_entities", ctx, status=status, reason=reason,
                      message=f"Top {min(args.top_k, len(rows))} of {len(rows)} eligible entities in {year}; ranked before limiting output. {scope.get('description', '')}",
                      data=data, provenance=prov, warnings=warnings,
                      limits={"returned_rows": len(data["rows"]), "total_rows": len(rows),
                              "source_complete": True, "preview_truncated": False})
