"""One-year entity ranking, after the shared query has validated every input row.

Top K limits presentation only. City membership uses the SIRUTA option catalogue
of INS GOS102A, not a substring test on population labels or model arithmetic.
The catalogue resolver (`city_codes`, `classify_cities`) is shared with the
period-change tool (AQ-05A): both classify full entity keys the same way.
"""
from __future__ import annotations

import math
import re

from app.services import data_query, dataset_meta, period_changes
from app.services.tools import contract as C
from app.services.tools import messages as M
from app.services.tools import recipe as recipe_tool

CITY_CATALOGUE = "GOS102A"
QUERY_PREVIEW = 100          # the query_data limit its refusal plan builds candidate calls with


def _refuse(reason, message, provenance=None, recovery=()):
    raise C.ToolFailure("unavailable", reason, message, provenance=provenance, recovery=list(recovery))


def city_codes(conn, lang: str = "ro") -> dict[str, str]:
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
                _refuse("identity_ambiguous", M.t(lang, "rank.identity_ambiguous_labels"))
            out[key] = label.strip()
    if not out:
        _refuse("classification_unavailable", M.t(lang, "rank.catalogue_unavailable"))
    return out


def _siruta(value):
    m = re.match(r"^(\d+)\s+\S", str(value).strip())
    return str(int(m[1])) if m else None


def classification_entry() -> dict:
    """provenance.classification of a city-class result (rankings and period changes)."""
    return {"dataset": CITY_CATALOGUE, "key": "SIRUTA", "class": "municipalities_and_towns",
            "temporal_status": "catalogue_not_historical"}


def classify_cities(keys, key_cols, catalogue: dict, aggregates=frozenset(), lang: str = "ro") -> dict:
    """Classify full entity keys against the city catalogue: {key: (SIRUTA or None, class)} with
    class "member" (a municipality or town of the catalogue), "outside_class" (any other place,
    e.g. a commune) or "aggregate_row" (a total among its parts). Membership is the exact SIRUTA
    key of the locality value, never its name. A locality value without one, or one SIRUTA under
    two entities, refuses with `identity_ambiguous` (the caller attaches provenance)."""
    out, owner = {}, {}
    for key in keys:
        if key in aggregates:
            out[key] = (None, "aggregate_row")
            continue
        siruta = _siruta(dict(zip(key_cols, key))["REF_AREA_2"])
        if siruta is None:
            raise C.ToolFailure("unavailable", "identity_ambiguous", M.t(lang, "rank.siruta_required"))
        if siruta not in catalogue:
            out[key] = (siruta, "outside_class")
            continue
        if siruta in owner:
            raise C.ToolFailure("unavailable", "identity_ambiguous", M.t(lang, "rank.siruta_repeated"))
        owner[siruta] = key
        out[key] = (siruta, "member")
    return out


def members_of(classes: dict) -> dict:
    """{key: SIRUTA} of the members in a `classify_cities` result."""
    return {k: s for k, (s, c) in classes.items() if c == "member"}


def _published_ranking(ctx, code: str, keys: list, filters: dict, res: dict):
    """INS's published Total cells for a one-year ranking the shared query refused only because the
    Total option is not in the download (AQ-13); None otherwise. The entities are the labels the
    dataset itself has, and every value is INS's own cell: nothing from the data file is mixed in."""
    from app.services import recipes
    from app.services.tools import query as query_tool
    if keys != ["REF_AREA"] or query_tool.refusal_reason(res, code) not in query_tool.PUBLISHED_REFUSALS:
        return None
    if recipe_tool.published_recipe_for(ctx.conn, code):
        return None                       # a reviewed recipe already serves this dataset's published values
    if len(_area_levels(ctx.conn, code)) > 1:
        return None                       # counties, regions and macroregions never share one ranking
    try:
        universe = data_query.dimension_values(ctx.conn, code, "REF_AREA", limit=500)["values"]
        return recipes.published_selection(ctx.conn, code, filters, ["REF_AREA", "TIME_PERIOD"], universe=universe)
    except Exception:
        return None


def _area_levels(conn, code: str) -> set:
    """Parsed geographic levels of the dataset's REF_AREA options, without the country (it goes
    to `aggregates`). A split parent holds several; its split children hold one each."""
    try:
        rows = conn.execute(
            "SELECT DISTINCT p.geo_level FROM dimensions d JOIN dimension_options o USING (dimension_id) "
            "JOIN dimension_options_parsed p USING (nom_item_id) "
            "WHERE d.matrix_code = ? AND d.dim_column_name = 'REF_AREA' AND p.geo_level IS NOT NULL", [code]).fetchall()
    except Exception:
        return {"unknown", "levels"}      # cannot prove one level: keep the refusal
    return {r[0] for r in rows} - {"national"}


def _published_national(ctx, code: str, keys: list, filters: dict, year: str) -> list:
    """The national value INS publishes for the ranked selection (`aggregates`), or []. It exists
    only when the request pins nothing but the breakdown the cells carry (sex)."""
    from app.services import recipes
    if keys != ["REF_AREA"]:
        return []
    f = {c: v for c, v in filters.items() if c != "REF_AREA"}
    try:
        sel = recipes.published_selection(ctx.conn, code, f, ["TIME_PERIOD"])
    except Exception:
        return []
    if not sel:
        return []
    fetch = (sel["sources"] or [{}])[0]
    return [{"entity": {"REF_AREA": c["area"]}, "year": c["period"], "value": c["value"], "unit": c["unit"],
             "value_source": "ins_published", "query_id": fetch.get("query_id"),
             "ins_updated": fetch.get("ins_updated")} for c in sel["cells"] if c["period"] == year]


def rank_entities(args, ctx):
    from app import config
    from app.services.query_builder import resolve_parquet_schema, to_sdmx_name

    from app.services.tools import query as query_tool
    ctx.require_present_generation("rank_entities")
    lang = ctx.lang
    code = args.dataset
    actx = dataset_meta.get_aggregation_context(ctx.conn, code)
    if actx is None:
        raise C.query_failure(data_query.QueryError(404, f"Dataset {code} not found"), ctx, code)
    dims = {d["dim_column_name"]: d for d in actx["dimensions"]}
    # A rate is ranked only when each entity is one source cell (checked after the query).
    if "TIME_PERIOD" not in dims or dims["TIME_PERIOD"].get("dim_type") != "time":
        _refuse("unsupported_frequency", M.t(lang, "rank.annual_required"))
    schema = resolve_parquet_schema(ctx.conn, code)
    if any(to_sdmx_name(schema, c) == "TIME_PERIOD" for c in args.filters):
        raise C.ToolFailure("error", "invalid_input", M.t(lang, "rank.use_year"))
    if any(c not in dims or c == "TIME_PERIOD" for c in args.entity_columns):
        raise C.ToolFailure("error", "invalid_input", M.t(lang, "rank.entity_columns"))
    keys, _ = period_changes._key_columns(actx, args.entity_columns)
    if len(keys) > 8:
        raise C.ToolFailure("error", "invalid_input", M.t(lang, "rank.key_too_long"))
    if args.entity_class == "cities" and "REF_AREA_2" not in keys:
        raise C.ToolFailure("error", "invalid_input", M.t(lang, "rank.cities_need_locality"))
    periods, _ = period_changes._periods(ctx.conn, code, "TIME_PERIOD", ctx, "rank_entities",
                                         args.model_dump(exclude_none=True))
    year = args.year or max(periods)
    if year not in periods:
        _refuse("period_unavailable", M.t(lang, "rank.no_year", year=year))
    filters = {c: list(v) for c, v in args.filters.items() if v}
    filters["TIME_PERIOD"] = [periods[year]]
    query = {"dataset": code, "filters": filters, "group_by": keys + ["TIME_PERIOD"], "approximate": False}
    try:
        res = data_query.run_query(ctx.conn, code, filters, query["group_by"], config.MAX_DATA_ROWS)
    except data_query.QueryError as e:
        raise C.query_failure(e, ctx, code)
    published = _published_ranking(ctx, code, keys, filters, res) if res.get("unavailable") else None
    if published:
        # the rest of the tool reads this result like any other; its values are INS's cells
        res = {"columns": ["REF_AREA", "TIME_PERIOD", "OBS_VALUE"],
               "rows": [[c["area"], c["period"], c["value"]] for c in published["cells"]],
               "aggregation": {"outcome": "available", "reason": None, "method": "single_row",
                               "source": "ins_published_total", "warnings": []}, "quality": {}}
    prov = C.query_provenance(ctx, code, query, res)
    selection = {**args.model_dump(), "year": year, "kind": "entity_ranking"}
    prov.update(selection=selection, source_query=query)
    if published:
        src = query_tool.published_source(published)
        universe_n = len(data_query.dimension_values(ctx.conn, code, "REF_AREA", limit=500)["values"])
        prov["scope"] = {**query_tool.published_scope(lang, published),
                         "domain_complete": len(published["cells"]) == universe_n}
        prov["sources"][0]["published_total"] = src
        prov["effective_selection"]["published_total"] = src
    agg = res.get("aggregation") or {}
    if res.get("unavailable"):
        # the same explanation and next steps query_data gives for this selection, not a bare refusal
        try:
            why, recs = query_tool.refusal(ctx, code, query, res, QUERY_PREVIEW)
        except Exception:
            why, recs = "", []
        # a related dataset query_data would try is offered as the same ranking there
        recs = [C.recovery("tool_call", r["message"], "rank_entities",
                           {**args.model_dump(exclude_none=True), "dataset": r["arguments"]["dataset"]})
                if r.get("tool") == "query_data" else r for r in recs]
        raise C.ToolFailure("unavailable", (query_tool.refusal_reason(res, code) if agg.get("reason") else None)
                            or "aggregation_unavailable",
                            M.t(lang, "rank.query_refused", why=why).strip(), recovery=recs, provenance=prov)
    if res.get("truncated") or res.get("time_windowed") or res.get("partial_period_dropped") is not None:
        _refuse("source_incomplete", M.t(lang, "rank.source_incomplete"), prov)
    if agg.get("outcome") == "approximation":
        _refuse("unsupported_measure", M.t(lang, "rank.approximation"), prov)
    if period_changes.rate_values_combined(actx, agg):
        rid = recipe_tool.published_recipe_for(ctx.conn, code)
        _refuse("unsupported_measure", M.t(lang, "rank.additive_only"), prov,
                recovery=[recipe_tool.recipe_recovery(rid, lang, M.t(lang, "recipe.published_route", rid=rid))] if rid
                else [C.recovery("narrow", M.t(lang, "rank.rate_recovery"))])
    if any(w.get("code") == "mixed_grain_on_axis" for w in agg.get("warnings") or []):
        _refuse("overlapping_levels", M.t(lang, "rank.mixed_levels"), prov)
    cols = res["columns"]
    table = {}
    for row in res["rows"]:
        key = tuple(row[cols.index(c)] for c in keys)
        if any(v is None or not str(v).strip() for v in key):
            _refuse("identity_ambiguous", M.t(lang, "rank.empty_key"), prov)
        if key in table:
            _refuse("duplicate_keys", M.t(lang, "rank.duplicate_key"), prov)
        table[key] = row[cols.index("OBS_VALUE")]
    aggregates = period_changes._aggregate_keys({(k, year): v for k, v in table.items()}, keys, actx)
    catalogue = city_codes(ctx.conn, lang) if args.entity_class == "cities" else None
    members, outside_class, seen_ids = None, len(aggregates), set()
    if catalogue:
        prov["sources"].append({**C.source_entry(ctx.conn, CITY_CATALOGUE, ctx.lang), "role": "entity_classification"})
        prov["classification"] = classification_entry()
        try:
            classes = classify_cities(table, keys, catalogue, aggregates, lang)
        except C.ToolFailure as f:
            f.provenance = prov
            raise
        members = members_of(classes)
        outside_class, seen_ids = len(classes) - len(members), set(members.values())
    rows, excluded = [], []
    for key, value in table.items():
        entity = dict(zip(keys, key))
        if (key in aggregates) if members is None else (key not in members):
            continue                        # outside the class (counted in outside_class)
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
    period_changes.assign_ranks(rows, lambda r: r["value"])
    scope = prov["scope"]
    warnings = []
    pinned = query_tool.auto_pinned_warning(agg, filters, lang)
    if pinned:
        warnings.append(pinned)
    aggregates = _published_national(ctx, code, keys, filters, year)
    if published:
        warnings.append(query_tool.published_total_warning(lang, published))
    if aggregates:
        warnings.append(C.warning("published_total", M.t(lang, "rank.published_national"), "national"))
    if catalogue:
        warnings.append(C.warning("classification_reference", M.t(lang, "rank.classification")))
    cut = period_changes.tie_cut(rows, args.top_k)
    if cut:
        warnings.append(C.warning("tie_split", M.t(lang, "rank.tie_split", n=cut, rank=rows[args.top_k - 1]["rank"])))
    if excluded:
        warnings.append(C.warning("entities_excluded", M.t(lang, "rank.entities_excluded", n=len(excluded))))
    if scope.get("domain_complete") is not True:
        warnings.append(C.warning("incomplete_domain" if scope.get("domain_complete") is False else "unverified_total",
                                  scope.get("description") or M.t(lang, "rank.unverified_total")))
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
    if aggregates:
        data["aggregates"] = aggregates
    if published:
        data["value_source"] = "ins_published"
    return C.envelope("rank_entities", ctx, status=status, reason=reason,
                      message=M.t(lang, "rank.published_message", n=len(rows), year=year) if published
                      else M.t(lang, "rank.message", k=min(args.top_k, len(rows)), n=len(rows), year=year,
                               scope=scope.get("description", "")),
                      data=data, provenance=prov, warnings=warnings,
                      limits={"returned_rows": len(data["rows"]), "total_rows": len(rows),
                              "source_complete": True, "preview_truncated": False})
