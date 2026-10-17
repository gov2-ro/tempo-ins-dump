"""`get_evidence_links`: exact links for a selection, bound to the generation it
was computed on.

Nothing is executed: the selection is validated against the dataset's recorded
columns (the allowed set `data_query.run_query` uses), the recipe catalogue or
the period-changes request, and the links are built from the validated values.
Every link is relative to the configured trusted origin (`contract.public_url`),
never to a caller-supplied URL or a request header. A selection whose links
would not fit 4 KiB is refused (`link_too_long`); filters are never dropped to
shorten a link. If the served generation is not the one the result was
computed on, no link is produced: a link would show current data as if it were
the cited answer.

Live links (`dataset`, `live_selection`, `csv`) re-run on whatever data the
site serves when they are opened. The `evidence` link carries
`expected_generation`, so the bundle is refused (409) unless the served data is
still that generation, both before it is built and before it is sent.
"""
from __future__ import annotations

from urllib.parse import quote, urlencode

from app.services import data_query as dq
from app.services import recipes
from app.services.query_builder import resolve_parquet_schema
from app.services.request_validation import InvalidRequest, validate_filters, validate_group_by
from app.services.tools import contract as C

MAX_URL_BYTES = 4096
# /api/recipes/{id}[/evidence] accept `areas` up to this many characters
RECIPE_AREAS_MAX_CHARS = 2000

_TX = {
    "en": {
        "ok": "{n} links for this selection, bound to generation {gid}.",
        "scope": "Links to the selection; no data was queried to create them.",
        "dataset": "Dataset page with this selection's filters (live view of the data served "
                   "when the link is opened).",
        "live_dataset": "JSON of this selection from the API. Live re-run on the data served when "
                        "the link is opened; it can differ from the cited answer if the source "
                        "was revised.",
        "csv": "CSV of the raw observations matching the filters (live re-run on current data). "
               "Not the aggregated result, and no aggregation pins are applied.",
        "recipe_page": "Recipe comparison page for this year and these areas (live view of the "
                       "data served when the link is opened).",
        "live_recipe": "JSON of the recipe result from the API. Live re-run on the data served "
                       "when the link is opened; it can differ from the cited answer if the "
                       "source was revised.",
        "period_page": "Dataset page with this selection's filters (live view of the data "
                       "served when the link is opened).",
        "live_period": "JSON of the per-entity changes from the API. Live re-run on the data "
                       "served when the link is opened; it can differ from the cited answer if "
                       "the source was revised.",
        "evidence": "Evidence bundle (ZIP) for this selection. Snapshot checked against "
                    "generation {gid}: it is refused with 409 generation_changed unless the "
                    "served data is still that generation.",
        "changed": "The data generation changed: this result was computed on {expected} but the "
                   "site now serves {served}. No links were created, because they would show "
                   "current data as if it were the cited answer. Re-run the selection to cite "
                   "the current data.",
        "retry": "Re-run the original query on the current generation, then request links with "
                 "that result's generation id.",
        "too_long": "The links for this selection are up to {n} bytes; the limit is {max}. "
                    "Filters are never shortened or dropped to fit.",
        "areas_long": "The areas list is {n} characters as JSON; the recipe routes accept at "
                      "most {max}. Areas are never dropped to fit.",
        "narrow": "Select fewer filter values, columns or areas, or cite several smaller "
                  "selections.",
        "no_time": "Dataset {code} has no TIME_PERIOD column, so periods cannot be compared.",
        "unknown_recipe": "There is no recipe {id!r}. Available recipes: {ids}.",
        "r_unknown": "Find the right recipe by concept.",
        "empty": "Filters with an empty value list impose no constraint and are left out of the "
                 "normalized selection and the links.",
        "empty_areas": "An empty areas list means every area and is normalized to null.",
        "describe": "Read the dataset's columns, values and sub-datasets.",
    },
    "ro": {
        "ok": "{n} linkuri pentru această selecție, legate de generația {gid}.",
        "scope": "Linkuri către selecție; pentru a le crea nu s-au interogat date.",
        "dataset": "Pagina setului de date cu filtrele acestei selecții (vedere live a datelor "
                   "servite la deschiderea linkului).",
        "live_dataset": "JSON al acestei selecții din API. Reexecutare live pe datele servite la "
                        "deschiderea linkului; poate diferi de răspunsul citat dacă sursa a fost "
                        "revizuită.",
        "csv": "CSV cu observațiile brute care respectă filtrele (reexecutare live pe datele "
               "curente). Nu este rezultatul agregat și nu se aplică fixări de agregare.",
        "recipe_page": "Pagina de comparare a rețetei pentru acest an și aceste zone (vedere "
                       "live a datelor servite la deschiderea linkului).",
        "live_recipe": "JSON al rezultatului rețetei din API. Reexecutare live pe datele servite "
                       "la deschiderea linkului; poate diferi de răspunsul citat dacă sursa a "
                       "fost revizuită.",
        "period_page": "Pagina setului de date cu filtrele acestei selecții (vedere live a "
                       "datelor servite la deschiderea linkului).",
        "live_period": "JSON al schimbărilor pe entitate din API. Reexecutare live pe datele "
                       "servite la deschiderea linkului; poate diferi de răspunsul citat dacă "
                       "sursa a fost revizuită.",
        "evidence": "Pachet de dovezi (ZIP) pentru această selecție. Instantaneu verificat față "
                    "de generația {gid}: este refuzat cu 409 generation_changed dacă datele "
                    "servite nu mai sunt acea generație.",
        "changed": "Generația datelor s-a schimbat: rezultatul a fost calculat pe {expected}, "
                   "dar site-ul servește acum {served}. Nu s-a creat niciun link, pentru că ar "
                   "arăta datele curente ca pe răspunsul citat. Reexecută selecția pentru a "
                   "cita datele curente.",
        "retry": "Reexecută interogarea inițială pe generația curentă, apoi cere linkuri cu "
                 "identificatorul de generație al acelui rezultat.",
        "too_long": "Linkurile acestei selecții ajung la {n} octeți; limita este {max}. "
                    "Filtrele nu sunt niciodată scurtate sau eliminate ca să încapă.",
        "areas_long": "Lista de zone are {n} caractere ca JSON; rutele rețetelor acceptă cel "
                      "mult {max}. Zonele nu sunt niciodată eliminate ca să încapă.",
        "narrow": "Alege mai puține valori de filtru, coloane sau zone, sau citează mai multe "
                  "selecții mai mici.",
        "no_time": "Setul {code} nu are coloana TIME_PERIOD, deci perioadele nu pot fi comparate.",
        "unknown_recipe": "Nu există rețeta {id!r}. Rețete disponibile: {ids}.",
        "r_unknown": "Găsește rețeta potrivită după concept.",
        "empty": "Filtrele cu o listă goală de valori nu impun nicio constrângere și sunt omise "
                 "din selecția normalizată și din linkuri.",
        "empty_areas": "O listă goală de zone înseamnă toate zonele și este normalizată la null.",
        "describe": "Citește coloanele, valorile și subseturile setului de date.",
    },
}


def _url(path: str, params: list[tuple[str, str]]) -> str:
    return C.public_url(f"{path}?{urlencode(params, quote_via=quote)}")


def _link(kind: str, url: str, description: str, mode: str) -> dict:
    return {"kind": kind, "url": url, "description": description, "generation_mode": mode}


# ------------------------------------------------------------------ validation

def _check_dataset(ctx, code: str, *, filters: dict, group_by=(), entities=(),
                   needs_time: bool = False) -> None:
    """The dataset exists, has a data file and knows every named column, by the
    rules `run_query` applies; no query is run."""
    tx = _TX[ctx.lang]
    conn = ctx.conn
    if not conn.execute("SELECT 1 FROM matrices WHERE matrix_code = ?", [code]).fetchone():
        raise C.query_failure(dq.QueryError(404, f"Dataset {code} not found"), ctx, code)
    if not (dq.PARQUET_DIR / f"{code}.parquet").exists():
        raise C.query_failure(dq.QueryError(
            404, f"Dataset {code} has no data file; it may be published as sub-datasets."),
            ctx, code)
    dims = [{"dim_column_name": r[0]} for r in conn.execute(
        "SELECT dim_column_name FROM dimensions WHERE matrix_code = ? ORDER BY dim_code",
        [code]).fetchall()]
    allowed = dq._allowed_columns(dims, resolve_parquet_schema(conn, code))
    try:
        validate_filters(filters, allowed)
        validate_group_by(list(group_by), allowed)
        validate_group_by(list(entities), allowed)
    except InvalidRequest as e:
        raise C.query_failure(dq.QueryError(400, str(e)), ctx, code)
    if needs_time and "TIME_PERIOD" not in allowed:
        raise C.ToolFailure(
            "error", "unknown_column", tx["no_time"].format(code=code),
            recovery=[C.recovery("tool_call", tx["describe"], "describe_dataset",
                                 {"dataset": code, "lang": ctx.lang})])


def _non_empty(filters: dict) -> tuple[dict, list[str]]:
    """Filters that constrain something, and the columns whose empty list was dropped."""
    return ({c: list(v) for c, v in filters.items() if v},
            [c for c, v in filters.items() if not v])


# ------------------------------------------------------------------ per kind

def _dataset(ctx, sel, gid: str):
    tx, lang = _TX[ctx.lang], ctx.lang
    _check_dataset(ctx, sel.dataset, filters=sel.filters, group_by=sel.group_by)
    filters, dropped = _non_empty(sel.filters)
    norm = {"kind": "dataset", "dataset": sel.dataset, "filters": filters,
            "group_by": list(sel.group_by), "approximate": sel.approximate}
    fj, gj = C.dumps(filters), C.dumps(norm["group_by"])
    code = quote(sel.dataset, safe="")
    en = [("lang", "en")] if lang == "en" else []
    links = [
        _link("dataset", C.dataset_page(sel.dataset, lang, filters or None), tx["dataset"],
              "live_rerun"),
        _link("live_selection", _url(f"/api/datasets/{code}/data", [
            ("filters", fj), ("group_by", gj), ("approximate", "1" if sel.approximate else "0")]),
              tx["live_dataset"], "live_rerun"),
        _link("csv", _url(f"/api/datasets/{code}/download", [("format", "csv"), ("filters", fj)]
                          + en), tx["csv"], "live_rerun"),
        _link("evidence", _url(f"/api/datasets/{code}/evidence", [
            ("filters", fj), ("group_by", gj), ("approximate", "1" if sel.approximate else "0"),
            *en, ("expected_generation", gid)]), tx["evidence"].format(gid=gid),
              "expected_generation"),
    ]
    warnings = [C.warning("empty_filter_ignored", tx["empty"], ",".join(dropped))] if dropped else []
    return norm, links, [(None, sel.dataset)], warnings


def _period_changes(ctx, sel, gid: str):
    tx, lang = _TX[ctx.lang], ctx.lang
    _check_dataset(ctx, sel.dataset, filters=sel.filters, entities=sel.entity_columns,
                   needs_time=True)
    filters, dropped = _non_empty(sel.filters)
    norm = sel.model_dump(by_alias=True)
    norm["filters"] = filters
    params = [("dataset", sel.dataset), ("entity_columns", C.dumps(norm["entity_columns"])),
              ("intervals", C.dumps(norm["intervals"])), ("filters", C.dumps(filters)),
              ("metric", sel.metric), ("order", sel.order), ("top_k", str(sel.top_k))]
    if sel.entity_class != "all":           # the default class adds nothing to a link
        params.append(("entity_class", sel.entity_class))
    if lang == "en":
        params.append(("lang", "en"))
    links = [
        _link("dataset", C.dataset_page(sel.dataset, lang, filters or None), tx["period_page"],
              "live_rerun"),
        _link("live_selection", _url("/api/period-changes", params), tx["live_period"],
              "live_rerun"),
        _link("evidence", _url("/api/period-changes/evidence",
                               params + [("expected_generation", gid)]),
              tx["evidence"].format(gid=gid), "expected_generation"),
    ]
    warnings = [C.warning("empty_filter_ignored", tx["empty"], ",".join(dropped))] if dropped else []
    specs = [(None, sel.dataset)]
    if sel.entity_class == "cities":        # the catalogue the class was taken from is a cited source
        specs.append(("entity_classification", "GOS102A"))
    return norm, links, specs, warnings


def _recipe(ctx, sel, gid: str):
    tx, lang = _TX[ctx.lang], ctx.lang
    catalogue = recipes.load_recipes()
    r = catalogue.get(sel.recipe)
    if r is None:
        ids = sorted(catalogue)[:20]
        raise C.ToolFailure(
            "error", "unknown_recipe", tx["unknown_recipe"].format(id=sel.recipe, ids=", ".join(ids)),
            data={"available_recipes": ids},
            recovery=[C.recovery("tool_call", tx["r_unknown"], "discover_indicators",
                                 {"query": sel.recipe.replace("_", " ")[:200], "lang": lang})])
    areas = sel.areas or None
    norm = {"kind": "recipe", "recipe": sel.recipe, "year": sel.year, "areas": areas}
    warnings = [C.warning("empty_filter_ignored", tx["empty_areas"], "areas")] \
        if sel.areas is not None and not sel.areas else []
    aj = C.dumps(areas) if areas else None
    if aj is not None and len(aj) > RECIPE_AREAS_MAX_CHARS:
        raise C.ToolFailure(
            "unavailable", "link_too_long",
            tx["areas_long"].format(n=len(aj), max=RECIPE_AREAS_MAX_CHARS),
            recovery=[C.recovery("narrow", tx["narrow"])])
    base = [("year", sel.year)] + ([("areas", aj)] if aj else []) + ([("lang", "en")] if lang == "en" else [])
    rid = quote(sel.recipe, safe="")
    links = [
        _link("dataset", _url("/compare.html", [("recipe", sel.recipe), *base]),
              tx["recipe_page"], "live_rerun"),
        _link("live_selection", _url(f"/api/recipes/{rid}", base), tx["live_recipe"], "live_rerun"),
        _link("evidence", _url(f"/api/recipes/{rid}/evidence", base + [("expected_generation", gid)]),
              tx["evidence"].format(gid=gid), "expected_generation"),
    ]
    specs = ([("published", r["published"]["matrix"])] if r.get("published") else []) \
        + [(s.get("role"), s["dataset"]) for s in recipes.source_specs(r)]
    return norm, links, specs, warnings


def _entity_ranking(ctx, sel, served):
    _check_dataset(ctx, sel.dataset, filters=sel.filters, entities=sel.entity_columns, needs_time=True)
    norm = sel.model_dump()
    args = {k: v for k, v in norm.items() if k != "kind"}
    args["lang"] = ctx.lang
    params = {"request": C.dumps(args)}
    path = "/api/entity-rankings?"
    links = [
        {"kind": "dataset", "url": C.dataset_page(sel.dataset, ctx.lang),
         "description": "Source dataset (not the ranking).", "generation_mode": "live_rerun"},
        {"kind": "live_selection", "url": C.public_url(path + urlencode(params)),
         "description": "Re-run this exact ranking, including its scope, class and eligible count.",
         "generation_mode": "live_rerun"},
        {"kind": "evidence", "url": C.public_url(path + urlencode({**params, "expected_generation": served})),
         "description": "Ranking JSON with provenance, refused if the cited generation changed.",
         "generation_mode": "expected_generation"}]
    specs = [(None, sel.dataset)]
    if sel.entity_class == "cities":
        specs.append(("entity_classification", "GOS102A"))
    return norm, links, specs, []


def get_evidence_links(args, ctx):
    ctx.require_present_generation("get_evidence_links")
    tx = _TX[ctx.lang]
    served = ctx.generation["id"]
    if args.generation_id != served:
        raise C.ToolFailure(
            "unavailable", "generation_changed",
            tx["changed"].format(expected=args.generation_id, served=served),
            data={"expected_generation": args.generation_id, "served_generation": served},
            recovery=[C.recovery("retry", tx["retry"])])
    sel = args.selection
    build = {"dataset": _dataset, "period_changes": _period_changes, "recipe": _recipe, "entity_ranking": _entity_ranking}[sel.kind]
    norm, links, specs, warnings = build(ctx, sel, served)

    longest = max(len(link["url"].encode("utf-8")) for link in links)
    if longest > MAX_URL_BYTES:
        raise C.ToolFailure(
            "unavailable", "link_too_long", tx["too_long"].format(n=longest, max=MAX_URL_BYTES),
            recovery=[C.recovery("narrow", tx["narrow"])])

    sources = [{**({"role": role} if role else {}), **C.source_entry(ctx.conn, code, ctx.lang)}
               for role, code in specs]
    return C.envelope(
        "get_evidence_links", ctx, message=tx["ok"].format(n=len(links), gid=served),
        data={"selection": norm, "generation_id": served, "links": links},
        provenance={"sources": sources, "selection": norm,
                    "scope": {"description": tx["scope"], "domain_complete": None,
                              "limitations": []}},
        warnings=warnings)
