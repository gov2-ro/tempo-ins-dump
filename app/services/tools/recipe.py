"""`run_recipe`: a reviewed cross-dataset recipe through the shared tool contract.

The arithmetic, the unit/year/duplicate rules and the choice between INS's
published totals and a reconstruction all stay in `recipes.run`; this module
only translates its result into the `tempo-tools/2` envelope. It never
recomputes a value, never sends raw `inputs` or the reconstruction tables
(they travel in the evidence bundle) and never switches the requested year or
matches an area name loosely.

A result with excluded areas is `partial`: the ranking then covers only the
eligible areas, and the scope, exclusion counts and a bounded sample say so.
"""
from __future__ import annotations

import logging
import re
from collections import Counter

from app.services import recipes
from app.services.tools import contract as C

log = logging.getLogger(__name__)

MAX_EXCLUDED_SAMPLE = 20      # excluded areas listed (counts always cover all of them)
MAX_AGGREGATES = 20           # published non-county cells (country, regions)
MAX_YEARS = 60                # most recent years listed
MAX_RECIPE_IDS = 20

ROW_KEYS = ("rank", "geo_id", "label", "value", "stays", "population", "intensity",
            "weight_total", "cells", "count_total", "base_total", "reconstructed")
RECIPE_KEYS = ("id", "version", "kind", "name", "definition", "formula", "value_source", "unit",
               "status", "missing_policy", "display_decimals", "reconstruction_formula")

# Warning texts are English in every tool (contract.shrink_rows does the same).
PREVIEW_SHORTENED = ("The preview was shortened to fit the response budget (exclusion sample, "
                     "aggregate cells or ranking rows); the exclusion counts and the canonical "
                     "selection give the complete result.")

_TX = {
    "en": {
        "ok": "Recipe {id}, {year}: {n} areas ranked.",
        "partial": "Recipe {id}, {year}: {n} of {universe} eligible areas ranked; {k} excluded. The "
                   "ranking covers only the eligible areas (see exclusion_counts and excluded).",
        "none_ranked": "Recipe {id}, {year}: no area could be ranked ({k} excluded: "
                       "{reasons}). Nothing was computed for them.",
        "r_all_areas": "Run the recipe for every area to see the names the data uses.",
        "r_area": "Look up the exact label the source uses for {area!r}; the recipe matches areas "
                  "by exact label (accents, case and spacing aside), never by a similar name.",
        "scope_ranked": "{n} of {universe} eligible areas ranked for {year}",
        "scope_excluded": "; {k} excluded ({reasons})",
        "scope_all": ". Every area of the recipe's universe was considered.",
        "scope_subset": ". Requested areas only: ranks are within this selection, not a "
                        "national ranking.",
        "lim_excluded": "{k} area(s) have no value and are not ranked: {reasons}.",
        "lim_subset": "{k} area(s) were requested; ranks are positions within them only.",
        "no_check": "Only INS's published value is served for {year}: the reconstruction "
                    "cross-check is not available for it (see check).",
        "no_published": "INS's published totals are not loaded in this generation: the values "
                        "are reconstructions from published parts and can differ from INS's "
                        "own total by rounding.",
        "gen_changed": "The served data generation changed while this recipe ran; nothing "
                       "from it is reported. Run the request again.",
        "retry": "Run the same request again on the new generation.",
        "failed": "The recipe's sources could not be read (reference {ref}); nothing was computed.",
        "e_unknown_recipe": "There is no recipe {id!r}. Available recipes: {ids}. Use "
                            "discover_indicators to find the right one.",
        "e_year": "Recipe {id} has no data for {year} in every source (years available: {years}). "
                  "The year was not changed; choose one of those years.",
        "e_no_common_year": "The sources of recipe {id} share no year, so nothing was computed.",
        "e_no_published_data": "INS's published values for recipe {id} contain no county data; "
                               "nothing was computed.",
        "e_source_unavailable": "A source of recipe {id} was refused by the shared aggregation "
                                "and data-quality policy{why}; the recipe cannot be computed "
                                "from it.",
        "e_source_incomplete": "A source of recipe {id} exceeds the query cap and would be "
                               "incomplete; a partial source is never ranked.",
        "e_source_approximation": "A source of recipe {id} would need an approximation; recipes "
                                  "never use approximations.",
        "e_duplicate_key": "A source of recipe {id} has more than one row for the same area and "
                           "year; no value was picked or summed.",
        "e_unsupported_unit": "A source of recipe {id} has a unit ({unit}) without a declared "
                              "conversion; nothing was computed.",
        "e_unsupported_period": "A source of recipe {id} is not annual; recipes compare annual "
                                "values only.",
        "e_other": "Recipe {id} could not produce a result ({reason}).",
        "r_unknown": "Find the right recipe by concept.",
        "r_year": "Run the recipe for the latest year every source has.",
        "r_source": "Read this source's quality, grain status and notes.",
    },
    "ro": {
        "ok": "Rețeta {id}, {year}: {n} zone clasate.",
        "partial": "Rețeta {id}, {year}: {n} din {universe} zone eligibile clasate; {k} excluse. "
                   "Clasamentul acoperă doar zonele eligibile (vezi exclusion_counts și excluded).",
        "none_ranked": "Rețeta {id}, {year}: nicio zonă nu a putut fi clasată ({k} excluse: "
                       "{reasons}). Pentru ele nu s-a calculat nimic.",
        "r_all_areas": "Rulează rețeta pentru toate zonele ca să vezi numele folosite de date.",
        "r_area": "Caută eticheta exactă pe care o folosește sursa pentru {area!r}; rețeta potrivește "
                  "zonele după eticheta exactă (fără diferențe de diacritice, majuscule sau spații), "
                  "niciodată după un nume asemănător.",
        "scope_ranked": "{n} din {universe} zone eligibile clasate pentru {year}",
        "scope_excluded": "; {k} excluse ({reasons})",
        "scope_all": ". Au fost luate în calcul toate zonele din universul rețetei.",
        "scope_subset": ". Doar zonele cerute: pozițiile sunt în cadrul acestei selecții, nu un "
                        "clasament național.",
        "lim_excluded": "{k} zonă(zone) nu au valoare și nu sunt clasate: {reasons}.",
        "lim_subset": "Au fost cerute {k} zonă(zone); pozițiile sunt doar între ele.",
        "no_check": "Pentru {year} se servește doar valoarea publicată de INS: verificarea "
                    "prin reconstituire nu este disponibilă (vezi check).",
        "no_published": "Totalurile publicate de INS nu sunt încărcate în această generație: "
                        "valorile sunt reconstituiri din părți publicate și pot diferi de "
                        "totalul INS din rotunjire.",
        "gen_changed": "Generația de date servită s-a schimbat cât a rulat rețeta; nimic din ea "
                       "nu este raportat. Repetă cererea.",
        "retry": "Repetă aceeași cerere pe noua generație.",
        "failed": "Sursele rețetei nu au putut fi citite (referință {ref}); nu s-a calculat nimic.",
        "e_unknown_recipe": "Nu există rețeta {id!r}. Rețete disponibile: {ids}. Folosește "
                            "discover_indicators pentru a o găsi pe cea potrivită.",
        "e_year": "Rețeta {id} nu are date pentru {year} în toate sursele (ani disponibili: "
                  "{years}). Anul nu a fost schimbat; alege unul dintre ei.",
        "e_no_common_year": "Sursele rețetei {id} nu au niciun an comun; nu s-a calculat nimic.",
        "e_no_published_data": "Valorile publicate de INS pentru rețeta {id} nu conțin date pe "
                               "județe; nu s-a calculat nimic.",
        "e_source_unavailable": "O sursă a rețetei {id} a fost refuzată de politica comună de "
                                "agregare și calitate{why}; rețeta nu poate fi calculată din ea.",
        "e_source_incomplete": "O sursă a rețetei {id} depășește limita interogării și ar fi "
                               "incompletă; o sursă parțială nu este niciodată clasată.",
        "e_source_approximation": "O sursă a rețetei {id} ar necesita o aproximare; rețetele nu "
                                  "folosesc aproximări.",
        "e_duplicate_key": "O sursă a rețetei {id} are mai multe rânduri pentru aceeași zonă și "
                           "an; nicio valoare nu a fost aleasă sau însumată.",
        "e_unsupported_unit": "O sursă a rețetei {id} are o unitate ({unit}) fără conversie "
                              "declarată; nu s-a calculat nimic.",
        "e_unsupported_period": "O sursă a rețetei {id} nu este anuală; rețetele compară doar "
                                "valori anuale.",
        "e_other": "Rețeta {id} nu a putut produce un rezultat ({reason}).",
        "r_unknown": "Găsește rețeta potrivită după concept.",
        "r_year": "Rulează rețeta pentru ultimul an pe care îl au toate sursele.",
        "r_source": "Citește calitatea, starea granularității și notele acestei surse.",
    },
}


def _tx(lang: str) -> dict:
    return _TX.get(lang, _TX["ro"])


# ------------------------------------------------------------------ area lookup

def area_dataset(recipe_id: str) -> str | None:
    """The dataset whose REF_AREA labels a recipe's `areas` are matched against: the first
    source of a published or non-ratio recipe, the denominator of a reconstructed ratio (it
    defines the universe). Its labels are what find_dimension_values lists exactly."""
    r = recipes.load_recipes().get(recipe_id)
    if not r:
        return None
    specs = recipes.source_specs(r)
    ratio = r.get("kind", "ratio") == "ratio" and not r.get("published")
    return specs[1]["dataset"] if ratio else specs[0]["dataset"]


def lookup_query(area: str, labels=None) -> str:
    """The substring to search the source's REF_AREA labels with for `area`: the whole text, or
    (given the labels) its longest word that some label contains, so 'Cluj-Napoca' finds 'Cluj'.
    It only chooses what to search for; the lookup lists labels and never picks one."""
    text = " ".join(str(area or "").split())
    if labels:
        from app.services.concept_search import fold
        folded = [fold(v) for v in labels]
        for w in sorted(re.findall(r"\w+", text), key=len, reverse=True):
            if len(w) > 2 and any(fold(w) in v for v in folded):
                return w[:200]
    return text[:200]


def _area_labels(conn, recipe_id: str) -> list | None:
    """Every REF_AREA label of the recipe's area dataset, or None when they cannot be listed."""
    from app.services import data_query
    ds = area_dataset(recipe_id)
    try:
        res = data_query.dimension_values(conn, ds, "REF_AREA", limit=500) if ds else None
    except data_query.QueryError:
        return None
    return res["values"] if res and res["total"] <= len(res["values"]) else None


def area_lookup_recovery(recipe_id: str, area: str, tx: dict, labels=None) -> dict | None:
    ds = area_dataset(recipe_id)
    return C.recovery("tool_call", tx["r_area"].format(area=" ".join(str(area).split())[:100]),
                      "find_dimension_values", {"dataset": ds, "column": "REF_AREA",
                                                "query": lookup_query(area, labels), "limit": 20}) if ds else None


# ------------------------------------------------------------------ refusals

def _source_dataset(recipe_id: str, role: str | None) -> str | None:
    """The dataset behind a source role of a recipe (None when unknown)."""
    r = recipes.load_recipes().get(recipe_id)
    if not r or not role:
        return None
    if role == "published" and r.get("published"):
        return r["published"]["matrix"]
    return next((s["dataset"] for s in recipes.source_specs(r) if s.get("role") == role), None)


def _failure(e: recipes.RecipeError, args, ctx) -> C.ToolFailure:
    tx, rid, d = _tx(ctx.lang), args.recipe, e.detail
    reason = e.reason
    if reason == "unknown_recipe" and rid not in recipes.load_recipes():
        ids = sorted(recipes.load_recipes())[:MAX_RECIPE_IDS]
        return C.ToolFailure(
            "error", "unknown_recipe", tx["e_unknown_recipe"].format(id=rid, ids=", ".join(ids)),
            data={"available_recipes": ids},
            recovery=[C.recovery("tool_call", tx["r_unknown"], "discover_indicators",
                                 {"query": rid.replace("_", " ")[:200], "lang": ctx.lang})])
    if reason == "year_unavailable":
        years = sorted(str(y) for y in d.get("years_available") or [])
        shown = years[-MAX_YEARS:]
        rec = []
        if years:
            nxt = {"recipe": rid, "year": years[-1], "lang": ctx.lang}
            if args.areas is not None:
                nxt["areas"] = args.areas
            rec.append(C.recovery("tool_call", tx["r_year"], "run_recipe", nxt))
        return C.ToolFailure(
            "unavailable", "period_unavailable",
            tx["e_year"].format(id=rid, year=args.year or "?", years=", ".join(shown) or "-"),
            data={"requested_year": args.year, "years_available": shown,
                  "years_available_truncated": len(years) > len(shown)},
            recovery=rec)
    if reason == "source_failed":
        # a source dataset could not be read: log the cause, never show it
        log.warning("recipe source failed recipe=%s request=%s detail=%s", rid, ctx.request_id,
                    e.message)
        return C.ToolFailure("error", "execution_failed",
                             tx["failed"].format(ref=ctx.request_id))
    known = {"no_common_year", "no_published_data", "source_unavailable", "source_incomplete",
             "source_approximation", "duplicate_key", "unsupported_unit", "unsupported_period"}
    data = {"source": d.get("source")} if d.get("source") else {}
    if reason in known:
        why = f" ({d['source_reason']})" if reason == "source_unavailable" and d.get("source_reason") else ""
        if reason == "source_unavailable" and d.get("source_reason"):
            data["source_reason"] = str(d["source_reason"])[:64]
        if reason == "unsupported_unit":
            data["unit"] = d.get("unit")
        if reason == "no_common_year":
            data["years_numerator"] = [str(y) for y in (d.get("years_numerator") or [])][-MAX_YEARS:]
            data["years_denominator"] = [str(y) for y in (d.get("years_denominator") or [])][-MAX_YEARS:]
        message = tx["e_" + reason].format(id=rid, why=why, unit=d.get("unit"))
    else:
        reason = reason if isinstance(reason, str) and reason.replace("_", "").isalnum() \
            else "execution_failed"
        message = tx["e_other"].format(id=rid, reason=reason)
    rec = []
    dataset = _source_dataset(rid, d.get("source"))
    if dataset:
        rec.append(C.recovery("tool_call", tx["r_source"], "describe_dataset",
                              {"dataset": dataset, "lang": ctx.lang}))
    return C.ToolFailure("unavailable", reason, message, data=data, recovery=rec)


# ------------------------------------------------------------------ result parts

def _sources(ctx, native: list[dict]) -> list[dict]:
    """One role-tagged `source_entry` per recipe source. The recipe's own reading
    wins where it is more specific (published cells carry their unit and INS's
    update date)."""
    out = []
    for s in native:
        e = {"role": s.get("role"), **C.source_entry(ctx.conn, s["dataset"], ctx.lang)}
        e["reference"] = s.get("reference")
        if s.get("concept"):
            e["concept"] = s["concept"]
        if s.get("title"):
            e["metric"] = s["title"]
        for k in ("unit", "source_updated"):
            if s.get(k):
                e[k] = s[k]
        out.append(e)
    return out


def _sample(excluded: list[dict]) -> list[dict]:
    """At most MAX_EXCLUDED_SAMPLE exclusions, every reason represented (round
    robin in order of first appearance), listed in their original order."""
    if len(excluded) <= MAX_EXCLUDED_SAMPLE:
        return excluded
    by_reason: dict[str, list[int]] = {}
    for i, e in enumerate(excluded):
        by_reason.setdefault(e["reason"], []).append(i)
    picked: list[int] = []
    queues = [list(ix) for ix in by_reason.values()]
    while len(picked) < MAX_EXCLUDED_SAMPLE and any(queues):
        for q in queues:
            if q and len(picked) < MAX_EXCLUDED_SAMPLE:
                picked.append(q.pop(0))
    return [excluded[i] for i in sorted(picked)]


def _exclusions(res: dict, areas) -> list[dict]:
    """Native exclusions; an area the data lacks is named as the caller wrote it."""
    asked = {recipes.geo_id(a): a for a in areas or []}
    out = []
    for e in res["excluded"]:
        e = dict(e)
        if e.get("reason") == "not_in_data" and e.get("geo_id") in asked:
            e["label"] = asked[e["geo_id"]]
        out.append(e)
    return out


def _reasons(counts: Counter) -> str:
    return ", ".join(f"{r}: {n}" for r, n in sorted(counts.items()))


def run_recipe(args, ctx):
    ctx.require_present_generation("run_recipe")
    tx = _tx(ctx.lang)
    try:
        res = recipes.run(ctx.conn, args.recipe, year=args.year, areas=args.areas, lang=ctx.lang)
    except recipes.RecipeError as e:
        raise _failure(e, args, ctx)
    native_gen = res.get("generation") or {}
    if native_gen.get("id") != ctx.generation.get("id"):
        raise C.ToolFailure("unavailable", "generation_changed", tx["gen_changed"],
                            recovery=[C.recovery("retry", tx["retry"])])

    info = res["recipe"]
    year = str(res["year"])
    all_rows = res["rows"]
    rows = [{k: r[k] for k in ROW_KEYS if k in r} for r in all_rows[:C.MAX_TABLE_ROWS]]
    excluded = _exclusions(res, args.areas)
    counts = Counter(e["reason"] for e in excluded)
    sample = _sample(excluded)
    years = [str(y) for y in res.get("years_available") or []]
    aggregates = list(res.get("aggregates") or [])
    check = res.get("check")
    if check is not None:
        check = {**check, "decimals": info.get("display_decimals")}
    universe = res.get("universe")

    data = {
        "recipe": {k: info[k] for k in RECIPE_KEYS if info.get(k) is not None},
        "year": year,
        "requested_year": args.year,
        "rows": rows,
        "excluded": sample,
        "exclusion_counts": dict(sorted(counts.items())),
        "exclusions_truncated": len(sample) < len(excluded),
        "check": check,
        "aggregates": aggregates[:MAX_AGGREGATES],
        "aggregates_truncated": len(aggregates) > MAX_AGGREGATES,
        "universe": universe,
        "years_available": years[-MAX_YEARS:],
        "years_available_truncated": len(years) > MAX_YEARS,
    }

    n_excl = len(excluded)
    if n_excl:
        domain_complete = False
    elif all_rows and universe == len(all_rows):
        domain_complete = True
    else:
        domain_complete = None
    description = tx["scope_ranked"].format(n=len(all_rows), universe=universe, year=year)
    if n_excl:
        description += tx["scope_excluded"].format(k=n_excl, reasons=_reasons(counts))
    description += tx["scope_subset"] if args.areas else tx["scope_all"]
    limitations = []
    if n_excl:
        limitations.append({"code": "areas_excluded", "count": n_excl,
                            "reasons": dict(sorted(counts.items())),
                            "message": tx["lim_excluded"].format(k=n_excl, reasons=_reasons(counts))})
    if args.areas:
        limitations.append({"code": "areas_subset", "requested": len(args.areas),
                            "message": tx["lim_subset"].format(k=len(args.areas))})

    native_sources = res["sources"]
    provenance = {
        "sources": _sources(ctx, native_sources),
        # canonical: the implicit latest year is resolved before anything cites it
        "selection": {"kind": "recipe", "recipe": args.recipe, "year": year,
                      "areas": args.areas or None},
        "requested_selection": {"year": args.year, "areas": args.areas},
        "effective_selection": {"source_queries": {s["role"]: s.get("query") for s in native_sources}},
        "aggregation": {"sources": {s["role"]: s.get("aggregation") for s in native_sources}},
        "quality": {s["role"]: s["quality"] for s in native_sources if s.get("quality") is not None},
        "scope": {"description": description, "domain_complete": domain_complete,
                  "limitations": limitations},
    }

    warnings = []
    declared = recipes.load_recipes().get(args.recipe) or {}
    if declared.get("published") and info.get("value_source") != "ins_published":
        warnings.append(C.warning("published_totals_unavailable", tx["no_published"],
                                  args.recipe))
    if info.get("value_source") == "ins_published" and len(native_sources) == 1:
        # the reconstruction could not be built for this year (e.g. a source starts later)
        warnings.append(C.warning("check_unavailable", tx["no_check"].format(year=year), args.recipe))
    if len(all_rows) > len(rows):
        warnings.append(C.warning("preview_shortened", PREVIEW_SHORTENED))

    recovery = []
    if not all_rows:
        # nothing could be ranked: no usable result, only the reasons
        status, reason = "unavailable", "incomplete_domain"
        message = tx["none_ranked"].format(id=args.recipe, year=year, k=n_excl,
                                           reasons=_reasons(counts))
        if args.areas:
            recovery.append(C.recovery("tool_call", tx["r_all_areas"], "run_recipe",
                                       {"recipe": args.recipe, "year": year, "lang": ctx.lang}))
    elif n_excl:
        status, reason = "partial", "incomplete_domain"
        message = tx["partial"].format(id=args.recipe, year=year, n=len(all_rows),
                                       universe=universe, k=n_excl)
    else:
        status, reason = "ok", None
        message = tx["ok"].format(id=args.recipe, year=year, n=len(all_rows))
    # an area the source has no label for: how to look up the label it does use (at most two)
    missing = [e["label"] for e in excluded if e["reason"] == "not_in_data"][:2]
    labels = _area_labels(ctx.conn, args.recipe) if missing else None
    recovery += [r for r in (area_lookup_recovery(args.recipe, a, tx, labels) for a in missing) if r]
    return C.envelope(
        "run_recipe", ctx, status=status, reason=reason, message=message, data=data,
        provenance=provenance, warnings=warnings, recovery=recovery,
        limits={"returned_rows": len(rows), "total_rows": len(all_rows),
                "preview_truncated": len(all_rows) > len(rows), "source_complete": True,
                "time_windowed": False, "partial_period_dropped": None})


# ------------------------------------------------------------------ budget

def _shortened(env: dict) -> None:
    if not any(w.get("code") == "preview_shortened" for w in env["warnings"]):
        env["warnings"].append(C.warning("preview_shortened", PREVIEW_SHORTENED))


def shrink(env: dict) -> bool:
    """Fit the 32 KiB budget: cut the exclusion sample, then the published
    aggregate cells, then halve the ranking rows. Counts, flags, provenance and
    the canonical selection are never cut. False when nothing is left to cut."""
    d = env["data"]
    if d.get("excluded"):
        d["excluded"] = []
        d["exclusions_truncated"] = True       # the counts still cover every exclusion
        _shortened(env)
        return True
    if d.get("aggregates"):
        d["aggregates"] = []
        d["aggregates_truncated"] = True
        _shortened(env)
        return True
    if not d.get("rows"):
        return False
    _shortened(env)
    return C.shrink_rows(env)
