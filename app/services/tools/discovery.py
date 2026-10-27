"""Discovery tools of `tempo-tools/2` (AT-01c): discover_indicators,
describe_dataset and find_dimension_values.

They are adapters over the shared statistical services and never decide a
statistic themselves:

  * discovery adapts `concept_search.search` (reviewed concepts, parsed place /
    level / period, ambiguity, family results). It chooses no definition for the
    user: a generic word or a city named like its county returns
    `needs_clarification` with labelled choices and no suggested data call.
    A suggested `query_data` call is only offered for a candidate whose grain
    evidence is not conflicting, whose domain is not known to be incomplete
    and whose proposed grouping the shared aggregation policy allows;
    otherwise the candidate says why and points at `describe_dataset`.
    The scope of a candidate comes from `scope.dataset_restrictions`: only a PROVEN
    gap (`domain.complete` false, e.g. single-age children stop at 84) blocks a
    candidate; `null` means "not verified" and is never presented as complete.
  * the reviewed defaults (resident population for a generic population question, the
    domicile series for a city ranking, the stays-per-resident recipe) are configuration:
    `discovery_policy` applies `app/data/discovery_defaults.json` before the shared search
    runs. A constraint of the question that discovery cannot apply (sex, age, a denominator,
    a county around a city ranking) is reported in `interpretation.unapplied_constraints`
    and a `constraint_not_applied` warning, and no data call that ignores it is suggested.
  * once a definition (or a county) is chosen, the follow-up is the validated call of the card
    that choice leads to: every choice carries `action` (query_data, rank_entities, run_recipe,
    describe_dataset or a find_dimension_values lookup) when its coordinates are known, and keeps
    the discover_indicators restatement (`next_call`) only for what still needs interpreting.
    Known series breaks (dataset_notes) inside a candidate's selection are warnings on it.
  * describe_dataset reads `dataset_meta` (metadata, structure, measure) and the
    ACTUAL values/period bounds of the data file. Metadata option lists and
    metadata year ranges are reported next to the actual ones, never instead.
  * find_dimension_values adapts `data_query.dimension_values`.

Nothing here fetches INS, opens a writer, runs arbitrary SQL, or mutates the
cached objects the shared services return (they are copied before any cut).
"""
from __future__ import annotations

import heapq
import logging
import re
from collections import Counter

from pydantic import ValidationError

from app.services import concept_search as cs
from app.services import data_query, dataset_meta, dataset_notes, dataset_search, grain_guard, recipes, scope
from app.services.chart_selector import TOTAL_RE
from app.services.tools import contract as C
from app.services.tools import discovery_policy as dpol
from app.services.tools import messages as M
from app.services.tools import recipe as recipe_tool
from app.services.tools import schemas as S
from app.services.tools.contract import ToolFailure

log = logging.getLogger(__name__)

MAX_EXAMPLES = 5            # actual example values per dimension
MAX_CHOICES = 5             # choices of a clarification
MAX_FAMILY_MEMBERS = 8      # split children listed per family hit
MAX_SPLITS = 30             # sub-datasets listed by describe_dataset
FIT_BYTES = 30 * 1024       # keep clear of the 32 KiB envelope budget
UNSAFE_GRAIN = ("conflicting", "duplicate_keys")
PERIOD_NOTES = ("period_unavailable", "period_not_single")
RANGE_NOTES = ("period_range_partial", "period_range_single")     # several years asked: a warning, not an ambiguity
GEO_LEVELS = ("county", "region", "macroregion", "national")
ACTION_TOOLS = ("query_data", "rank_entities", "run_recipe", "describe_dataset", "find_dimension_values")
PLACE_NOTES = ("place_not_in_dataset", "place_level_unavailable", "level_differs")
CARRIED_WARNINGS = ("series_break", "constraint_not_applied", "period_unavailable", "period_not_single")
MAX_ACTION_NOTES = 4        # qualifications travelling with a choice's action
ACTION_NOTE_CHARS = 240


# ------------------------------------------------------------------ helpers

def _call(tool: str, **arguments) -> dict | None:
    """A next_call whose arguments validate against that tool's schema (None
    when they would not, so a model is never handed a call that fails)."""
    from app.services.tools import registry
    try:
        registry.TOOLS[tool].args.model_validate(arguments)
    except (ValidationError, KeyError):
        log.error("discovery built an invalid next_call tool=%s", tool)
        return None
    return {"tool": tool, "arguments": arguments}


def _ws(text) -> str:
    return " ".join(str(text if text is not None else "").split())


def _generation_warnings(ctx) -> list:
    status = ctx.generation.get("status")
    if status == "present":
        return []
    return [C.warning("generation_unverified", M.t(ctx.lang, "discover.generation_manifest", status=status))]


def _has_file(code: str) -> bool:
    # looked up on the module at call time, as the query services do
    return (data_query.PARQUET_DIR / f"{code}.parquet").exists()


def _actx(conn, code: str):
    """The shared aggregation context (cached, read-only for us) or None."""
    try:
        return dataset_meta.get_aggregation_context(conn, code)
    except Exception:
        log.exception("aggregation context unavailable dataset=%s", code)
        return None


def _frequency(period: str | None) -> str | None:
    p = str(period or "").strip()
    if re.fullmatch(r"(?:Anul\s+)?\d{4}", p):
        return "annual"
    if re.fullmatch(r"\d{4}-?Q[1-4]", p):
        return "quarterly"
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", p):
        return "monthly"
    return None


def _period_present(conn, code: str, value: str) -> bool | None:
    """Is `value` an exact TIME_PERIOD of the data (None when it cannot be told)?"""
    try:
        r = data_query.dimension_values(conn, code, "TIME_PERIOD", q=value, limit=100)
    except data_query.QueryError:
        return None
    return value in r["values"]


# ------------------------------------------------------------------ domain scope

_DOMAIN_TEXT = {
    "ro": {"verified": "Vârstele sunt acoperite complet (verificat); celelalte dimensiuni nu sunt "
                       "examinate pentru completitudine.",
           "unknown": "Completitudinea domeniului nu este verificată (nu s-a dovedit nicio lipsă; "
                      "nu toate dimensiunile sunt examinate)."},
    "en": {"verified": "Ages are fully covered (verified); other dimensions are not examined "
                       "for completeness.",
           "unknown": "Domain completeness is not verified (no gap was proven; not every "
                      "dimension is examined)."},
}


def _domain(actx, lang: str) -> dict:
    """Scope of one dataset from the shared scope service (age ranges only).

    complete  False   a proven gap: an age dimension whose data lacks part of its
                      domain (single-age children stop at 84);
              True    every age dimension is verified fully covered; other
                      dimensions are not examined (`checked` says which were);
              None    anything else. Unknown is never reported as complete.
    """
    tx = _DOMAIN_TEXT.get(lang, _DOMAIN_TEXT["ro"])
    out = {"complete": None, "restrictions": [], "description": tx["unknown"], "missing": [],
           "checked": []}
    if actx is None:
        return out
    try:
        rs = [dict(r) for r in scope.dataset_restrictions(actx)]
        age_cols = list(dict.fromkeys(
            d["dim_column_name"] for d in actx.get("dimensions") or ()
            if d.get("dim_type") == "age"))
        covs = [scope.dimension_coverage(actx, c) for c in age_cols]
    except Exception:
        log.exception("scope service failed")
        return out
    out["checked"] = age_cols
    if rs:
        block = C.scope_block({"domain_complete": False, "restrictions": rs}, lang)
        out.update(complete=False, restrictions=rs, description=block["description"],
                   missing=[{"column": lim.get("column"), "missing": lim["missing"]}
                            for lim in block["limitations"] if lim.get("missing")])
    elif age_cols and all(c is not None and c["complete"] for c in covs):
        out.update(complete=True, description=tx["verified"])
    return out


def _scope_provenance(domain: dict, lang: str) -> dict:
    block = C.scope_block({"domain_complete": domain["complete"],
                           "restrictions": domain["restrictions"]}, lang)
    return {"description": domain["description"], "domain_complete": domain["complete"],
            "limitations": block["limitations"]}


# ------------------------------------------------------------------ discover: queries

def _base_query(query: str, matched: str | None) -> str:
    """The user's words (folded) without the phrase that matched a concept, so a
    rewording can put the chosen concept's own wording in its place."""
    text = f" {cs.fold(query)} "
    if matched:
        text = text.replace(f" {matched} ", " ")
    return text.strip()


def _concept_aliases(cdef: dict, lang: str) -> list:
    al = cdef.get("aliases") or {}
    other = "en" if lang == "ro" else "ro"
    return list(al.get(lang) or []) + list(al.get(other) or [])


def _specific_query(cid: str, by_id: dict, base_query: str, lang: str) -> str | None:
    """A rewording of the user's question that matches `cid` by a specific (not
    generic) alias, so selecting a definition is a plain discover call. Checked
    with the same matcher the next call will use."""
    cdef = by_id.get(cid)
    if not cdef:
        return None
    for alias in _concept_aliases(cdef, lang):
        for q in (f"{alias} {base_query}".strip()[:200], alias):
            hits = cs.match_concepts(cs.fold(q), lang)
            if hits and hits[0]["concept"]["id"] == cid and not hits[0]["generic"]:
                return q
    return None


def _county_query(matched: str | None, places: list, year, parse_conn) -> str | None:
    """'<alias> județul X [year]' for the named places, checked to parse as plain
    counties (the explicit word removes the city reading)."""
    if not matched or not places:
        return None
    q = f"{matched} " + " ".join(f"județul {p['name']}" for p in places)
    if year:
        q += f" {year}"
    parsed = cs.parse_query(q, parse_conn)
    ok = [p["slug"] for p in parsed["places"]] == [p["slug"] for p in places] \
        and not any(p.get("ambiguous") for p in parsed["places"])
    return q[:200] if ok else None


def _all_counties_query(matched: str | None, year, parse_conn) -> str | None:
    if not matched:
        return None
    q = f"{matched} pe județe" + (f" {year}" if year else "")
    parsed = cs.parse_query(q, parse_conn)
    return q[:200] if parsed["level"] == "county" and not parsed["places"] else None


# ------------------------------------------------------------------ discover: candidates

def _note(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _card_notes(raw: dict, lang: str) -> list:
    """concept_search's place notes; its period note is re-derived per candidate
    (a monthly dataset has a year without having it as one period)."""
    return [_note(code, M.tx(lang).get(f"discover.note.{code}", code)) for code in raw.get("notes") or []
            if code != "period_unavailable"]


def _lookup_periods(code: str, lang: str, year=None) -> dict | None:
    """The call that shows the actual periods when a requested year cannot be
    pinned: bounds and values instead of a silently different year."""
    args = {"dataset": code, "column": "TIME_PERIOD", "limit": 20}
    if year:
        args["query"] = str(year)
    return _call("find_dimension_values", **args)


def _period_state(conn, code: str, facts, year, lang: str) -> tuple:
    """(exact TIME_PERIOD to pin | None, note | None, lookup query | None) for a
    requested year against the ACTUAL periods of `code`."""
    cov = (facts or {}).get("coverage")
    if not year or not cov:
        return None, None, None
    try:
        first, last = int(str(cov["first"])[:4]), int(str(cov["last"])[:4])
    except (TypeError, ValueError):
        return None, None, None
    span = f"{cov['first']}–{cov['last']}"
    if not first <= year <= last:
        return None, _note("period_unavailable",
                           M.t(lang, "discover.period_outside", year=year, code=code, span=span)), None
    if cov.get("frequency") != "annual":
        freq = cov.get("frequency")
        return None, _note("period_not_single", M.t(
            lang, "discover.period_not_single", code=code, year=year, query=str(year),
            frequency=M.tx(lang).get(f"discover.freq.{freq}", freq))), str(year)
    if _period_present(conn, code, str(year)) is False:
        return None, _note("period_unavailable",
                           M.t(lang, "discover.period_gap", year=year, code=code, span=span)), None
    return str(year), None, None


def _periods_state(conn, code: str, wanted: list, lang: str) -> tuple:
    """(the requested years that are actual annual periods of `code` | None, note | None).
    Requested years the data does not have are named, never filled in or swapped."""
    try:
        actual = data_query.dimension_values(conn, code, "TIME_PERIOD", limit=500)["values"]
    except data_query.QueryError:
        actual = []
    asked = _years_text(wanted)
    have = [str(y) for y in wanted if str(y) in actual]
    if not have:
        span = f"{actual[-1]}–{actual[0]}" if actual else "?"
        return None, _note("period_unavailable", M.t(lang, "discover.range_outside", asked=asked, code=code,
                                                     span=span))
    missing = [y for y in wanted if str(y) not in actual]
    if not missing:
        return have, None
    return have, _note("period_range_partial", M.t(
        lang, "discover.range_partial", asked=asked, code=code, n=len(have), missing=_years_text(missing)))


def _years_text(years: list) -> str:
    """'2010–2011, 2014': consecutive years joined as spans."""
    runs = []
    for y in map(int, years):
        if runs and y == runs[-1][1] + 1:
            runs[-1][1] = y
        else:
            runs.append([y, y])
    return ", ".join(str(x) if x == y else f"{x}–{y}" for x, y in runs)


# How a family shows it publishes a geographic level: a split child named for it or the level in its
# title ("... macroregiuni, regiuni de dezvoltare si judete"). The level words are taken out of the
# full-text query, so "how many schools per county" listed the national file first and the county
# ones (SCL101A/B/C) 40th or lower (AQ live test); they are moved up, not added.
LEVEL_POOL = 20                 # families considered for moving up: the plain search's best, not its tail
LEVEL_MARKS = {"county": ("_judete", "_judet", "judete", "judet"),
               "region": ("_regiuni", "regiuni"),
               "macroregion": ("_macroregiuni", "macroregiuni")}


def _has_level(item: dict, level: str) -> bool:
    marks = LEVEL_MARKS[level]
    if any(m["code"].lower().endswith(marks[:2]) for m in item.get("members") or []):
        return True
    words = set(cs.fold(item.get("title") or "").split())
    return any(w in words for w in marks[2:])


def _level_families(fam: dict, level: str | None) -> dict:
    """Family results with those that publish the requested level first, in search order."""
    if level not in LEVEL_MARKS:
        return fam
    items = fam["items"]
    first = [it for it in items if _has_level(it, level)]
    return {**fam, "items": first + [it for it in items if not _has_level(it, level)]}


def _worst_quality(statuses: list) -> str:
    for bad in ("conflicting", "duplicate_keys", "unverified"):
        if bad in statuses:
            return bad
    return "unique"


def _filters_for_call(raw_selection: dict) -> dict:
    out = {}
    for col, v in (raw_selection or {}).items():
        vals = v if isinstance(v, list) else [v]
        out[col] = [str(x) for x in vals]
    return out


def _group_by(columns: set | None, filters: dict, parsed_level, level, relation) -> list:
    """The breakdown to propose: the named place or the level the user asked for
    (every other level variant exists to give its own breakdown), always by period."""
    gb = []
    has = (lambda c: columns is None or c in columns)
    if has("REF_AREA") and ("REF_AREA" in filters or relation == "level_variant"
                            or (parsed_level in GEO_LEVELS and parsed_level == level)):
        gb.append("REF_AREA")
    if has("TIME_PERIOD"):
        gb.append("TIME_PERIOD")
    return gb


def _preflight(actx, group_by: list, filters: dict):
    """(reason, blocking column) when the shared aggregation policy would refuse
    this grouping; None when it is allowed or cannot be judged."""
    if actx is None or not group_by:
        return None
    try:
        d = dataset_meta.decide_grouped(actx, group_by, filters)
    except Exception:
        log.exception("aggregation preflight failed")
        return None
    return None if d.available else (d.reason, d.blocking_dimension)


def _candidate_breaks(ctx, code: str, next_call: dict | None, facts) -> list:
    """Recorded series breaks inside the selection the candidate's data call makes (its pinned
    periods, else all the data it reaches). A lookup or describe call selects nothing yet."""
    if (next_call or {}).get("tool") != "query_data":
        return []
    flt = next_call["arguments"].get("filters") or {}
    cov = (facts or {}).get("coverage") or {}
    span = (cov["first"], cov["last"]) if cov.get("first") and cov.get("last") else None
    return dataset_notes.series_breaks(code, ctx.lang, periods=flt.get("TIME_PERIOD"), span=span,
                                       areas=flt.get("REF_AREA"))


def _attach_breaks(ctx, cards: list):
    """Series breaks of each dataset candidate's FINAL data call (after the ranking and
    unapplied-constraint rewrites): a note and a machine-readable list on the candidate."""
    for card in cards:
        for cand in card["candidates"]:
            if cand.get("kind") != "dataset":
                continue
            breaks = _candidate_breaks(ctx, cand["dataset"], cand.get("next_call"),
                                       cs.dataset_facts(ctx.conn, cand["dataset"], ctx.lang))
            cand["series_breaks"] = C.series_break_items(breaks)
            cand["notes"] += [{**_note("series_break", b["text"]), "subject": b["id"]} for b in breaks]


def _candidate(ctx, code: str, level, filters: dict, parsed: dict, relation: str,
               extra_notes=(), period_call: dict | None = None) -> dict:
    """One candidate dataset with its grain quality, domain and the next call.
    `period_call` replaces the data call when the requested year cannot be applied
    (the model first sees the actual periods; the year is never swapped)."""
    conn, lang = ctx.conn, ctx.lang
    facts = cs.dataset_facts(conn, code, lang)
    quality = grain_guard.file_status(code)["status"]
    actx = _actx(conn, code)
    domain = _domain(actx, lang)
    cols = {d["dim_column_name"] for d in actx["dimensions"]} if actx else None
    group_by = _group_by(cols, filters, parsed.get("level"), level, relation)
    notes = list(extra_notes)
    problems = []
    if facts is None:
        problems.append(_note("no_data_file", M.t(lang, "discover.no_data_file", code=code)))
    if quality in UNSAFE_GRAIN:
        problems.append(_note(f"grain_{quality}", M.t(
            lang, "discover.grain_conflicting" if quality == "conflicting" else "discover.grain_duplicate_keys",
            code=code)))
    if domain["complete"] is False:
        problems.append(_note("domain_incomplete", M.t(lang, "discover.domain_incomplete", desc=domain["description"])))
    pre = None if problems else _preflight(actx, group_by, filters)
    if pre:
        reason, col = pre
        problems.append(_note("aggregation_unavailable", M.t(
            lang, "discover.aggregation_unavailable", reason=reason, column=f", {col}" if col else "")))
    if quality == "unverified":
        notes.append(_note("grain_unverified", M.t(lang, "discover.grain_unverified")))
    queryable = not problems
    if not queryable:
        next_call = _call("describe_dataset", dataset=code, lang=lang)
    elif period_call is not None:
        next_call = period_call
    else:
        next_call = _call("query_data", dataset=code, filters=filters, group_by=group_by, lang=lang)
        queryable = next_call is not None
    return {"dataset": code, "kind": "dataset", "relation": relation, "level": level,
            "quality": quality, "domain": domain, "title": facts["title"] if facts else None,
            "coverage": dict(facts["coverage"]) if facts and facts.get("coverage") else None,
            "url": C.dataset_page(code, lang, filters or None), "queryable": queryable,
            "preferred": False, "notes": problems + notes, "series_breaks": [], "next_call": next_call}


def _complete_siblings(ctx, code: str, domain: dict) -> list:
    """Sub-datasets of the same parent with the same split on every dimension
    except the restricted one (the single-age child's grouped-age sibling)."""
    restricted = {m["column"] for m in domain["missing"]}
    if not restricted:
        return []
    try:
        meta = dataset_meta.get_dataset_meta(code, "ro", conn=ctx.conn)
        parent = meta and meta.get("parent_matrix_code")
        pmeta = parent and dataset_meta.get_dataset_meta(parent, "ro", conn=ctx.conn)
    except Exception:
        log.exception("sibling lookup failed dataset=%s", code)
        return []
    if not pmeta:
        return []
    mine = next((s.get("split_dimensions") for s in pmeta["splits"]
                 if s["matrix_code"] == code), None)
    if not mine:
        return []
    out = []
    for s in pmeta["splits"]:
        sd = s.get("split_dimensions")
        if s["matrix_code"] == code or not sd or set(sd) != set(mine):
            continue
        if all(sd[k] == mine[k] for k in mine if k not in restricted):
            out.append(s["matrix_code"])
    return out


def _level_pairs(raw: dict) -> list:
    """[(level, dataset)]: the card's own variant first, then the concept's other levels."""
    return [(raw["level"], raw["code"])] + [(v["level"], v["code"]) for v in raw.get("variants") or []]


def _dataset_candidates(ctx, raw: dict, parsed: dict) -> list:
    conn, lang = ctx.conn, ctx.lang
    levels = _level_pairs(raw)
    year, wanted = parsed.get("period"), parsed.get("periods")
    sel = _filters_for_call(raw.get("selection"))
    cands = []
    for idx, (level, code) in enumerate(levels):
        filters, notes, period_call = {}, [], None
        facts = cs.dataset_facts(conn, code, lang)
        if idx == 0 and sel.get("REF_AREA"):
            filters["REF_AREA"] = sel["REF_AREA"]
        if wanted and ((facts or {}).get("coverage") or {}).get("frequency") == "annual":
            tvs, pnote = _periods_state(conn, code, wanted, lang)
            if pnote:
                notes.append(pnote)
            if tvs:
                filters["TIME_PERIOD"] = tvs
            else:
                period_call = _lookup_periods(code, lang)
        elif year:
            tv, pnote, lookup_q = _period_state(conn, code, facts, year, lang)
            if pnote:
                notes.append(pnote)
                period_call = _lookup_periods(code, lang, lookup_q)
            if tv:
                filters["TIME_PERIOD"] = [tv]
        elif parsed.get("latest") and facts and (facts.get("coverage") or {}).get("last"):
            tv = str(facts["coverage"]["last"])
            filters["TIME_PERIOD"] = [tv]
            notes.append(_note("latest_period", M.t(lang, "discover.latest_period", code=code, period=tv)))
        cand = _candidate(ctx, code, level, filters, parsed,
                          "primary" if idx == 0 else "level_variant", notes, period_call)
        cands.append(cand)
        if idx == 0 and cand["domain"]["complete"] is False:
            for sib in _complete_siblings(ctx, code, cand["domain"]):
                cands.append(_candidate(ctx, sib, level, filters, parsed, "sibling",
                                        period_call=period_call))
        if idx == 0 and any(n["code"].startswith("grain_") or n["code"] == "domain_incomplete"
                            for n in cand["notes"]):
            fam = (facts or {}).get("family")
            if fam and fam != code and cs.dataset_facts(conn, fam, lang):
                cands.append(_candidate(ctx, fam, None, filters, parsed, "parent",
                                        period_call=period_call))
    return cands


def _source_areas(conn, area_ds: str | None, places: list) -> tuple:
    """(areas for run_recipe, named places the source lacks, the source's labels or None). A place
    is passed as the exact REF_AREA label the recipe will match it to (recipes.geo_id: accents,
    case, spacing); a place with no such label keeps its own name and is reported, never replaced
    by a similar one. Without a complete label list (None) nothing is claimed."""
    names = [p["name"] for p in places]
    try:
        res = data_query.dimension_values(conn, area_ds, "REF_AREA", limit=500) if area_ds else None
    except data_query.QueryError:
        res = None
    if res is None or res["total"] > len(res["values"]):
        return names, [], None
    labels = {recipes.geo_id(v): v for v in res["values"]}
    return ([labels.get(recipes.geo_id(n), n) for n in names],
            [n for n in names if recipes.geo_id(n) not in labels], res["values"])


def _recipe_candidate(ctx, rid: str, parsed: dict, coverage: dict | None, relation: str,
                      notes=(), title: str | None = None) -> dict | None:
    r = recipes.load_recipes().get(rid)
    if not r:
        return None
    sources = [s["dataset"] for s in recipes.source_specs(r)]
    quality = _worst_quality([grain_guard.file_status(s)["status"] for s in sources])
    args = {"recipe": rid, "lang": ctx.lang}
    year = parsed.get("period")
    cov = coverage or {}
    notes, period_call = list(notes), None
    if parsed.get("periods") and year:
        notes.append(_note("period_range_single", M.t(ctx.lang, "discover.recipe_range", year=year,
                                                      asked=_years_text(parsed["periods"]))))
    if year:
        try:
            inside = int(str(cov["first"])[:4]) <= year <= int(str(cov["last"])[:4])
        except (KeyError, TypeError, ValueError):
            inside = False
        if inside:
            args["year"] = str(year)
        else:
            span = f" ({cov['first']}–{cov['last']})" if cov.get("first") else ""
            notes.append(_note("period_unavailable", M.t(ctx.lang, "discover.recipe_period", year=year, span=span)))
            period_call = _lookup_periods(sources[0], ctx.lang)
    area_ds, area_call = recipe_tool.area_dataset(rid), None
    areas, absent, labels = _source_areas(ctx.conn, area_ds, parsed.get("places") or [])
    if parsed.get("places"):
        args["areas"] = areas
        if absent:
            notes.append(_note("place_not_in_dataset", M.t(
                ctx.lang, "discover.recipe_place", absent=", ".join(absent), dataset=area_ds)))
            if len(absent) == len(args["areas"]):       # nothing left to run
                area_call = _call("find_dimension_values", dataset=area_ds, column="REF_AREA",
                                  query=recipe_tool.lookup_query(absent[0], labels), limit=20)
    unsafe = quality in UNSAFE_GRAIN
    if unsafe:
        notes.append(_note(f"grain_{quality}", M.t(ctx.lang, "discover.recipe_grain")))
    next_call = area_call or period_call or _call("run_recipe", **args)
    lookup = None
    if labels is not None:      # the source's labels could be listed, so this lookup will run
        named = (absent or [p["name"] for p in parsed.get("places") or []])[:1]
        lookup = _call("find_dimension_values", dataset=area_ds, column="REF_AREA", limit=20,
                       **({"query": recipe_tool.lookup_query(named[0], labels)} if named else {}))
    return {"dataset": None, "recipe": rid, "kind": "recipe", "relation": relation, "level": r.get("geo_level", "county"),
            "quality": quality, "sources": sources, "area_lookup": lookup, "series_breaks": [],
            "domain": {"complete": None, "restrictions": [], "missing": [], "checked": [],
                       "description": M.t(ctx.lang, "discover.recipe_domain")},
            "title": title, "coverage": dict(cov) if cov else None, "url": None,
            "queryable": not unsafe and next_call is not None, "preferred": False, "notes": notes,
            "next_call": next_call}


def _choose(cands: list, wanted_level, lang: str) -> dict | None:
    ok = [c for c in cands if c["queryable"] and c["next_call"]]
    pick = next((c for c in ok if wanted_level and c["level"] == wanted_level), None) \
        or (ok[0] if ok else None)
    if pick is not None:
        pick["preferred"] = True
        if wanted_level and pick["level"] != wanted_level:
            pick["notes"].append(_note("level_differs", M.t(
                lang, "discover.level_differs", wanted=wanted_level,
                level=pick["level"] or M.t(lang, "discover.parent_level"))))
    return pick


# ------------------------------------------------------------------ discover: cards

def _concept_recipe(cdef: dict) -> str | None:
    """The recipe a concept's card routes to: its own, else its reviewed total route."""
    return cdef.get("recipe") or cdef.get("total_recipe")


def _alternative(ctx, alt: dict, by_id: dict, base_query: str) -> dict:
    cdef = by_id.get(alt["id"], {})
    q = _specific_query(alt["id"], by_id, base_query, ctx.lang)
    out = {"id": alt["id"], "name": alt["name"], "difference": alt.get("note"),
           "recipe": _concept_recipe(cdef),
           "dataset": None if cdef.get("recipe") else alt.get("code"),
           "title": alt.get("title"), "coverage": alt.get("coverage"),
           "next_call": _call("discover_indicators", query=q, lang=ctx.lang) if q else None}
    return out


def _concept_card(ctx, raw: dict, by_id: dict, parsed: dict, query: str) -> dict:
    cdef = by_id.get(raw["id"], {})
    definition, cut = C._short(raw.get("definition"))
    is_recipe = bool(cdef.get("recipe"))
    card = {
        "id": raw["id"], "kind": "recipe" if is_recipe else "dataset", "name": raw["name"],
        "concept_note": raw.get("note"), "matched": raw.get("matched"),
        "generic_match": bool(raw.get("ambiguous")), "definition": definition,
        "definition_truncated": cut, "unit": raw.get("unit"), "unit_type": raw.get("unit_type"),
        "source_updated": raw.get("source_updated"),
        "coverage": dict(raw["coverage"]) if raw.get("coverage") else None,
        "recipe": None, "levels": [], "notes": _card_notes(raw, ctx.lang),
        "alternatives": [], "candidates": [], "preferred": None, "next_call": None,
        "requires_choice": False}
    if is_recipe:
        card["recipe"] = cdef["recipe"]
        cand = _recipe_candidate(ctx, cdef["recipe"], parsed, raw.get("coverage"), "primary",
                                 title=raw.get("title"))
        cands = [cand] if cand else []
        card["levels"] = [{"level": raw.get("level"), "sources": cand["sources"] if cand else []}]
    else:
        cands = _dataset_candidates(ctx, raw, parsed)
        card["levels"] = [{"level": lv, "dataset": c} for lv, c in _level_pairs(raw)]
        total = raw.get("total")
        if cdef.get("total_recipe") and total:
            card["recipe"] = cdef["total_recipe"]
            rc = _recipe_candidate(ctx, cdef["total_recipe"], parsed, total.get("coverage"),
                                   "source_total")
            if rc:
                rc["title"] = total.get("title")
                rc["notes"].append(_note("source_total", total.get("status") or M.t(ctx.lang, "discover.source_total")))
                cands.append(rc)
    first = cands[0] if cands else None
    if first:           # the requested year, as the card's primary source answers it
        card["notes"] += [n for n in first["notes"] if n["code"] in PERIOD_NOTES + RANGE_NOTES]
    wanted = parsed.get("level") or (first["level"] if first else None)
    _choose(cands, wanted, ctx.lang)
    # preferred first, the rest in discovery order
    cands.sort(key=lambda c: not c["preferred"])
    card["candidates"] = cands
    pref = next((c for c in cands if c["preferred"]), None)
    if pref:
        card["preferred"] = pref["dataset"] or pref.get("recipe")
        card["next_call"] = pref["next_call"]
    else:
        card["notes"].append(_note("no_verified_candidate", M.t(ctx.lang, "discover.no_verified_candidate")))
        card["next_call"] = next((c["next_call"] for c in cands if c["next_call"]), None)
    base = _base_query(query, raw.get("matched"))
    card["alternatives"] = [_alternative(ctx, a, by_id, base) for a in raw.get("alternatives") or []]
    card["base_query"] = base
    return card


def _trim(text, n: int = ACTION_NOTE_CHARS) -> str:
    t = _ws(text)
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


def _resolve_choice(ctx, query: str | None, cid: str, recipe=None, dataset=None) -> dict:
    out = _read_choice(ctx, query, cid, recipe, dataset)
    log.debug("choice resolved choice=%s status=%s action=%s recipe=%s notes=%s", cid, out["action_status"],
              (out["action"] or {}).get("tool"), out["recipe"], [n["code"] for n in out["action_notes"]])
    return out


def _read_choice(ctx, query: str | None, cid: str, recipe=None, dataset=None) -> dict:
    """What picking a choice leads to, as the call to make once the user has picked it.

    `query` restates the question with the choice (a plain discover call). The card that call
    returns for `cid` is read back, so the advertised `action` IS that card's own next call
    (query_data, rank_entities, run_recipe, describe_dataset or a period/area lookup) and
    `recipe` is that card's recipe, never a second opinion. `action_status`:
      ready               `action` is validated and complete; run it after the user picks
      needs_clarification more interpretation is needed (another ambiguity, or the named place
                          cannot be applied at the picked definition's levels): only the
                          restatement (`next_call`) is offered, nothing is chosen here
      unavailable         the picked definition cannot answer; `action_notes` says why
    `action_notes` carries the qualifications of the action (a period that is not there, a
    series break, a constraint that was not applied). Choices do not resolve recursively."""
    out = {"recipe": recipe, "dataset": dataset, "action": None, "action_status": "needs_clarification",
           "action_notes": []}
    if ctx.notes.get("resolving"):
        return out
    if not query:
        out["action_notes"] = [_note("no_specific_wording", M.t(ctx.lang, "discover.no_specific_wording"))]
        return out
    ctx.notes["resolving"] = True
    try:
        sub = discover_indicators(S.DiscoverIndicatorsArgs(query=query, lang=ctx.lang, limit=1), ctx)
    except ToolFailure as f:
        out.update(action_status="unavailable", action_notes=[_note(f.reason, _trim(f.message))])
        return out
    except Exception:
        log.exception("choice resolution failed choice=%s", cid)
        out["action_notes"] = [_note("resolution_failed", M.t(ctx.lang, "discover.resolution_failed"))]
        return out
    finally:
        ctx.notes.pop("resolving", None)
    if sub["status"] != "ok":
        out["action_notes"] = [_note(sub["reason"] or sub["status"], _trim(sub["message"]))]
        return out
    card = next((c for c in sub["data"]["concepts"] if c["id"] == cid), None)
    if card is None:
        out.update(action_status="unavailable", action_notes=[_note(
            "no_match", M.t(ctx.lang, "discover.no_match_choice"))])
        return out
    pref = next((c for c in card["candidates"] if c.get("preferred")), None)
    out["recipe"] = card["recipe"]
    carried = [{**_note(w["code"], _trim(w["message"])), **({"subject": w["subject"]} if w.get("subject") else {})}
               for w in sub["warnings"] if w["code"] in CARRIED_WARNINGS]
    place = [_note(n["code"], _trim(n["message"])) for n in card["notes"] + (pref["notes"] if pref else [])
             if n["code"] in PLACE_NOTES]
    # a card with no headline (an unapplied constraint, nothing queryable) still points its first
    # candidate at describe_dataset, where explicit values can be read and filtered
    nc = card["next_call"] or next((c["next_call"] for c in card["candidates"]
                                    if (c.get("next_call") or {}).get("tool") == "describe_dataset"), None)
    if place:           # the named place cannot be applied here: a call would silently widen it
        out["action_notes"] = (place + carried)[:MAX_ACTION_NOTES]
        return out
    if not nc or nc["tool"] not in ACTION_TOOLS:
        out.update(action_status="unavailable", action_notes=(carried + [_note(
            "no_call", M.t(ctx.lang, "discover.no_call"))])[:MAX_ACTION_NOTES])
        return out
    args = nc["arguments"]
    # the dataset a lookup reads (a recipe's source, a period list) is not the choice's dataset
    out.update(action=nc, action_status="ready", action_notes=carried[:MAX_ACTION_NOTES],
               dataset=args["dataset"] if nc["tool"] in ("query_data", "rank_entities", "describe_dataset") else dataset,
               recipe=args["recipe"] if nc["tool"] == "run_recipe" else out["recipe"])
    return out


def _definition_choices(ctx, cards: list, by_id: dict) -> list:
    top = next(c for c in cards if c["generic_match"] and c["alternatives"])
    query = top["base_query"]
    items = [{"id": top["id"], "label": top["name"], "description": top.get("concept_note") or "",
              "dataset": next((c["dataset"] for c in top["candidates"]
                               if c["kind"] == "dataset"), None),
              "coverage": top.get("coverage")}]
    items += [{"id": a["id"], "label": a["name"], "description": a.get("difference") or "",
               "dataset": a.get("dataset"), "coverage": a.get("coverage")}
              for a in top["alternatives"]]
    choices = []
    for it in items[:MAX_CHOICES]:
        q = _specific_query(it["id"], by_id, query, ctx.lang)
        it["recipe"] = _concept_recipe(by_id.get(it["id"], {}))
        it["next_call"] = _call("discover_indicators", query=q, lang=ctx.lang) if q else None
        it.update(_resolve_choice(ctx, q, it["id"], it["recipe"], it["dataset"]))
        choices.append(it)
    return choices


def _place_choices(ctx, cards: list, parsed: dict) -> list:
    year, places = parsed.get("period"), parsed.get("places") or []
    card = next((c for c in cards if c["kind"] == "recipe" or any(
        lv["level"] == "county" for lv in c["levels"])), cards[0])
    matched = card.get("matched")
    names = ", ".join(p["name"] for p in places)
    county_q = _county_query(matched, [dict(p) for p in places], year, ctx.conn)
    all_q = _all_counties_query(matched, year, ctx.conn)
    choices = [{"id": "county", "label": M.t(ctx.lang, "discover.county_label", names=names),
                "description": M.t(ctx.lang, "discover.county_description"),
                "next_call": _call("discover_indicators", query=county_q, lang=ctx.lang)
                if county_q else None},
               {"id": "all_counties", "label": M.t(ctx.lang, "discover.all_counties_label"),
                "description": M.t(ctx.lang, "discover.all_counties_description"),
                "next_call": _call("discover_indicators", query=all_q, lang=ctx.lang)
                if all_q else None}]
    pref = next((c for c in card["candidates"] if c.get("preferred")), None)
    for ch, q in zip(choices, (county_q, all_q)):
        ch.update(_resolve_choice(ctx, q, card["id"], card["recipe"], pref.get("dataset") if pref else None))
    return choices


# ------------------------------------------------------------------ discover: families

def _family_item(ctx, it: dict) -> dict:
    members = it.get("members") or []
    return {"family": it["family"], "code": it["code"], "title": it["title"],
            "time_range": it.get("time_range"), "verified": False,
            "members_total": len(members), "members_truncated": len(members) > MAX_FAMILY_MEMBERS,
            "members": [{"code": m["code"], "label": m.get("label"),
                         "time_range": m.get("time_range"),
                         "next_call": _call("describe_dataset", dataset=m["code"], lang=ctx.lang)}
                        for m in members[:MAX_FAMILY_MEMBERS]],
            "next_call": _call("describe_dataset", dataset=it["family"], lang=ctx.lang)}


# ------------------------------------------------------------------ discover: output fit

def _shrink_discover(data: dict) -> bool:
    """Cut optional detail in our own fresh objects; False when nothing is left."""
    notes = [n for ch in data["choices"] for n in ch.get("action_notes") or () if len(n["message"]) > 90]
    if notes:           # a choice keeps its codes; only the prose of its qualifications is cut
        for n in notes:
            n["message"] = n["message"][:80].rsplit(" ", 1)[0] + " …"
        return True
    fams = data["families"]
    if any(len(f["members"]) > 3 for f in fams):
        for f in fams:
            f["members"] = f["members"][:3]
            f["members_truncated"] = f["members_total"] > 3
        return True
    if fams:
        del fams[len(fams) // 2:]
        data["families_info"]["returned"] = len(fams)
        return True
    for c in data["concepts"]:
        if any("title" in a for a in c["alternatives"]):
            for a in c["alternatives"]:
                a.pop("title", None)
            return True
        if len(c["candidates"]) > 2:
            del c["candidates"][2:]
            return True
        if c.get("definition") and len(c["definition"]) > 160:
            c["definition"] = c["definition"][:160].rsplit(" ", 1)[0] + " …"
            c["definition_truncated"] = True
            return True
    return False


# ------------------------------------------------------------------ discover_indicators

def _locality_card(conn, lang: str, plan, parsed: dict, by_id: dict) -> dict:
    """The reviewed locality series for a city question, as a concept card. The question
    never reaches it through search: the configured variants replace the concept's own."""
    by_id[plan.locality["id"]] = plan.locality
    raw = cs.concept_card(conn, plan.locality, parsed, lang, plan.locality_alias, False)
    if raw is None:
        raise C.ToolFailure("unavailable", "level_unavailable", M.t(lang, "discover.city_series_missing"))
    return raw


_CALL_TOOLS = ("query_data", "rank_entities", "run_recipe")


def _withhold_calls(cards: list, lang: str):
    """A constraint discovery cannot apply (sex, age, a denominator, a county around a city
    ranking) must not hide behind a data call that ignores it: a dataset candidate points at
    describe_dataset (explicit values can be filtered there), a recipe candidate offers no call."""
    for card in cards:
        for cand in card["candidates"]:
            if (cand.get("next_call") or {}).get("tool") not in _CALL_TOOLS:
                continue
            cand["next_call"] = _call("describe_dataset", dataset=cand["dataset"], lang=lang) \
                if cand.get("dataset") else None
            cand["notes"].append(_note("constraint_not_applied", M.t(lang, "discover.constraint_withheld") + " " + M.t(
                lang, "discover.constraint_filter" if cand["next_call"] else "discover.constraint_recipe")))
        pref = next((c for c in card["candidates"] if c.get("preferred")), None)
        card["next_call"] = pref.get("next_call") if pref else None


# --- AQ-05A: the one supported city change (policy: discovery_policy.city_change) ---------------

def _change_calls(cards: list, plan, intent: dict, lang: str, place: dict | None = None):
    """A city change question reaches compare_periods with the cities class, the two exact
    years, the stated direction and top K (and the county that narrows the cities, if one was
    named). Everything else on the card is left as it was."""
    for card in cards:
        for cand in card["candidates"]:
            if cand.get("kind") != "dataset" or not cand.get("queryable"):
                continue
            prev = (cand.get("next_call") or {}).get("arguments") or {}
            filters = {k: v for k, v in prev.get("filters", {}).items() if k != "TIME_PERIOD"}
            cand["next_call"] = _call("compare_periods", dataset=cand["dataset"], **plan.rank,
                                      **plan.change, filters={**filters, **(place or {})},
                                      top_k=intent["top_k"], lang=lang)
        pref = next((c for c in card["candidates"] if c.get("preferred")), None)
        card["next_call"] = pref.get("next_call") if pref else None


# --- one county narrows a city ranking (discovery_policy.county_filter) -------------------------

def _place_filter(ctx, plan, geo, unapplied: list) -> dict | None:
    """{REF_AREA: [exact label]} when the policy lets the one county named narrow the city ranking,
    else None (the geography is reported as not applied). The label is read from the locality series
    itself; a list that cannot be read in full, or a county the series has no label for, applies nothing."""
    rule = plan.place_rule
    if not rule or unapplied or geo.regions or len(geo.places) != 1:
        return None
    try:
        res = data_query.dimension_values(ctx.conn, plan.locality["variants"]["locality"], rule["column"], limit=500)
    except data_query.QueryError:
        return None
    if res["total"] > len(res["values"]):
        return None
    return dpol.county_filter(geo.places, res["values"], rule)


def _disclose_place_filter(cards: list, place: dict, lang: str) -> dict:
    """The county filter is the user's own wording, not a default: it is stated in a warning (subject:
    the exact label) and on each candidate whose call carries it; the card's note that the series has no
    county level no longer applies."""
    (column, (label,)), = place.items()
    text = M.t(lang, "discover.place_filter", county=label)
    for card in cards:
        card["notes"] = [n for n in card["notes"] if n["code"] != "place_level_unavailable"]
        for cand in card["candidates"]:
            if (cand.get("next_call") or {}).get("arguments", {}).get("filters", {}).get(column) == [label]:
                cand["notes"].append(_note("place_filter_applied", text))
    return C.warning("place_filter_applied", text, label)


# ------------------------------------------------------------------------------------------------

def _constraint_warnings(unapplied: list, lang: str) -> list:
    out = []
    for kind in dict.fromkeys(c["kind"] for c in unapplied):
        words = "; ".join(repr(c["text"]) for c in unapplied if c["kind"] == kind)
        out.append(C.warning("constraint_not_applied", M.t(
            lang, "discover.constraint_warning", kind=M.tx(lang).get(f"discover.kind.{kind}", kind), words=words), kind))
    return out


LEVEL_NOUNS = {"county": "discover.level_county", "region": "discover.level_region",
               "macroregion": "discover.level_macroregion", "national": "discover.level_national"}


def _level_warning(cid: str, info: dict, by_id: dict, lang: str) -> dict:
    """Why a level picked this definition, and which other definition has no series at that level (the
    levels it covers come from the catalogue, so the sentence cannot go stale)."""
    noun = lambda level: M.t(lang, LEVEL_NOUNS[level])
    missing = "".join(M.t(lang, "discover.level_missing", name=(by_id[o].get("name") or {}).get(lang, o),
                          level=noun(info["level"]), covers=", ".join(noun(v) for v in by_id[o].get("variants") or {}))
                      for o in info["missing"])
    return C.warning("assumed_definition", M.t(
        lang, "discover.assumed_level", label=(by_id[cid].get("name") or {}).get(lang, cid), level=noun(info["level"]),
        missing=missing), cid)


def _assumed_warning(cdef: dict, cid: str, lang: str, cities: bool) -> dict:
    label = (cdef.get("name") or {}).get(lang, cid)
    if cities:      # the locality series is the only city definition: say what it counts
        note = (cdef.get("note") or {}).get(lang) or ""
        return C.warning("assumed_definition", M.t(lang, "discover.assumed_cities", label=label, note=note), cid)
    return C.warning("assumed_definition", M.t(lang, "discover.assumed", label=label), cid)


def discover_indicators(args, ctx):
    conn, lang = ctx.conn, ctx.lang
    from app.services.tools.intent import interpret
    intent = interpret(args.query)
    by_id = {c["id"]: c for c in cs.load_concepts()}
    geo = dpol.read_geography(args.query, conn)             # counties, regions and levels the question names
    plan = dpol.plan(intent, args.query, by_id, lang, geo=geo)       # reviewed defaults, routes, refusals
    # more families than shown, so those at the requested level can be moved up (_level_families)
    res = cs.search(plan.query, conn, lang=lang, limit=max(args.limit, LEVEL_POOL))
    parsed = res["interpretation"]
    parsed["latest"] = parsed.get("latest") or intent["latest"]
    parsed["period_range"] = rng = intent["period_range"]
    # every year asked for when there is more than one: a span, or years listed one by one
    parsed["periods"] = list(range(rng["from"], rng["to"] + 1)) if rng else (
        intent["years"] if len(intent["years"]) > 1 else None)
    if plan.locality:
        parsed["level"] = "locality"
        res["concepts"] = [_locality_card(conn, lang, plan, parsed, by_id)]
    if plan.recipe:
        res["concepts"] = [c for c in res["concepts"] if c["id"] == plan.recipe]
        if not res["concepts"]:
            raise C.ToolFailure("unavailable", "recipe_unavailable", M.t(lang, "discover.recipe_unavailable"))
    places = [dict(p) for p in parsed.get("places") or []]
    cards = [_concept_card(ctx, raw, by_id, parsed, args.query)
             for raw in res["concepts"][:args.limit]]
    named = {w for c in cards for w in cs.fold(c.get("matched") or "").split()}
    # a constraint inside the matched concept's own alias ("population by age") is that concept
    unapplied = [c for c in plan.unapplied if not set(cs.fold(c["text"]).split()) <= named]
    place = None
    if plan.locality and (geo.places or geo.regions):
        # one county can narrow the city ranking (policy); anything else the question names around it
        # (two counties, a city's name, a region) is reported, never dropped
        place = _place_filter(ctx, plan, geo, unapplied)
        if place is None:
            unapplied.append({"kind": "geography", "text": ", ".join([p["name"] for p in geo.places] + list(geo.regions))})
    if unapplied:
        _withhold_calls(cards, lang)
    elif plan.change:
        _change_calls(cards, plan, intent, lang, place)
    elif intent["operation"] == "rank" or intent["cities"]:
        for card in cards:
            for cand in card["candidates"]:
                if cand.get("kind") != "dataset" or not cand.get("queryable"):
                    continue
                prev = (cand.get("next_call") or {}).get("arguments") or {}
                filters = {k: v for k, v in prev.get("filters", {}).items() if k != "TIME_PERIOD"}
                cand["next_call"] = _call("rank_entities", dataset=cand["dataset"], **plan.rank,
                    year=str(parsed["period"]) if parsed.get("period") else None,
                    filters={**filters, **(place or {})}, top_k=intent["top_k"], order=intent["order"], lang=lang)
            pref = next((c for c in card["candidates"] if c.get("preferred")), None)
            card["next_call"] = pref.get("next_call") if pref else None

    _attach_breaks(ctx, cards)
    ambiguities, warnings = [], _generation_warnings(ctx)
    # only a default that reached the answer is disclosed: a configured mapping whose source
    # produced no card must not warn about a definition nobody was shown
    assumed = plan.assumed if any(c["id"] == plan.assumed for c in cards) else None
    if assumed:
        warnings.append(_level_warning(assumed, plan.assumed_level, by_id, lang) if plan.assumed_level
                        else _assumed_warning(by_id.get(assumed, {}), assumed, lang, intent["cities"]))
    if place:
        warnings.append(_disclose_place_filter(cards, place, lang))
    warnings += _constraint_warnings(unapplied, lang)
    if plan.change and not unapplied:
        warnings.append(C.warning("classification_reference", M.t(lang, "policy.city_change_note")))
    for card in cards:
        if assumed and card["id"] == assumed:
            card["assumed"] = True
    for c in cards:
        if c["generic_match"] and c["alternatives"]:
            ambiguities.append({
                "kind": "definition", "concept": c["id"], "matched": c["matched"],
                "alternatives": [a["id"] for a in c["alternatives"]],
                "message": M.t(lang, "discover.generic_word", matched=c["matched"], names="; ".join(
                    [c["name"]] + [a["name"] for a in c["alternatives"]]))})
        elif c["generic_match"]:
            warnings.append(C.warning("generic_match", M.t(lang, "discover.generic_single", matched=c["matched"]),
                                      c["id"]))
        for n in c["notes"]:
            if n["code"] in PERIOD_NOTES:
                ambiguities.append({"kind": "period", "concept": c["id"], "reason": n["code"],
                                    "requested": parsed.get("period"),
                                    "coverage": c.get("coverage"), "message": n["message"]})
                warnings.append(C.warning(n["code"], n["message"], c["id"]))
            elif n["code"] in RANGE_NOTES:
                warnings.append(C.warning(n["code"], n["message"], c["id"]))
    city = [p for p in places if p.get("note") == "city_not_county"]
    for p in city:
        ambiguities.append({
            "kind": "place", "place": p["name"], "slug": p["slug"], "reason": "city_not_county",
            "message": M.t(lang, "discover.city_not_county", name=p["name"])})
    county_based = [c for c in cards if c["kind"] == "recipe"
                    or any(lv["level"] == "county" for lv in c["levels"])]

    choices, status, reason = [], "ok", None
    if any(a["kind"] == "definition" for a in ambiguities):
        status, reason = "needs_clarification", "ambiguous_definition"
        choices = _definition_choices(ctx, cards, by_id)
    elif city and county_based:
        status, reason = "needs_clarification", "ambiguous_place"
        choices = _place_choices(ctx, cards, parsed)
    for c in cards:
        c.pop("base_query", None)
    if status != "ok":
        for c in cards:                       # no headline until the user chooses
            c["requires_choice"] = True
            c["next_call"] = None
            for cand in c["candidates"]:
                cand["preferred"] = False
                cand["next_call"] = None

    if status == "ok":          # a recorded break inside what the headline call selects
        have = {(w["code"], w.get("subject")) for w in warnings}
        for card in cards:
            pref = next((c for c in card["candidates"] if c.get("preferred")), None)
            for n in (pref or {}).get("notes", ()):
                if n["code"] == "series_break" and ("series_break", n["subject"]) not in have:
                    have.add(("series_break", n["subject"]))
                    warnings.append(C.warning("series_break", n["message"], n["subject"]))

    fam = _level_families(res["families"], parsed.get("level"))
    cap = max(0, args.limit - len(cards))
    families = [_family_item(ctx, it) for it in fam["items"][:cap]]
    families_info = {
        "total": fam["total"], "returned": len(families), "matching_datasets": fam["matching_datasets"],
        "truncated": fam["truncated"], "search_mode": fam["search_mode"], "verified": False,
        "note": M.t(lang, "discover.families_note")}
    if fam["search_mode"] != "fts" and dataset_search.search_status()["mode"] == "fallback":
        warnings.append(C.warning("search_degraded", M.t(lang, "discover.search_degraded")))

    interp = {"places": places, "level": parsed.get("level"), "period": parsed.get("period"),
              "period_range": parsed.get("period_range"), "periods": parsed.get("periods"),
              "latest": parsed.get("latest"), "family_query": parsed.get("fts"),
              "ambiguities": ambiguities, "operation": intent["operation"], "assumed_definition": assumed,
              "unapplied_constraints": unapplied}
    data = {"interpretation": interp, "concepts": cards, "families": families,
            "families_info": families_info, "choices": choices}

    if status == "needs_clarification":
        if reason == "ambiguous_definition":
            names = [ch["label"] for ch in choices]
            message = M.t(lang, "discover.msg_definition", n=len(names), names="; ".join(names))
        else:
            message = M.t(lang, "discover.msg_place",
                          place=places[0]["name"] if places else M.t(lang, "discover.the_place"))
        recovery = [C.recovery("tool_call", M.t(lang, "discover.use_choice", label=ch["label"]),
                               "discover_indicators", ch["next_call"]["arguments"])
                    for ch in choices if ch["next_call"]][:3]
    elif not cards and not families:
        warnings.append(C.warning("no_match", M.t(lang, "discover.no_match")))
        message = M.t(lang, "discover.no_match")
        recovery = [C.recovery("clarify", M.t(lang, "discover.rephrase"))]
    else:
        message = M.t(lang, "discover.msg_ok", n=len(cards), m=len(families)) + (
            M.t(lang, "discover.msg_unapplied",
                items=", ".join(f"{c['kind']} ({c['text']!r})" for c in unapplied)) if unapplied else "")
        recovery = []

    def build():
        return C.envelope("discover_indicators", ctx, status=status, reason=reason, message=message,
                          data=data, warnings=warnings, recovery=recovery)

    env = build()
    shrunk = False
    while C.size(env) > FIT_BYTES and _shrink_discover(data):
        shrunk = True
        env = build()
    if shrunk:
        warnings.append(C.warning("response_shortened", M.t(lang, "discover.response_shortened")))
        env = build()
    return env


# ------------------------------------------------------------------ describe_dataset

def _ordered_examples(values, is_time: bool) -> list:
    if is_time:
        return heapq.nlargest(MAX_EXAMPLES, values)
    return heapq.nsmallest(MAX_EXAMPLES, values, key=lambda v: (cs.fold(v), v))


def _total_info(d: dict, values: dict | None, struct_col: dict | None, lang: str) -> dict:
    """Does the data really have the Total-like row metadata lists?"""
    out = {"total_in_data": None}
    if d.get("dim_type") in ("time", "unit"):
        return out
    meta_totals = [o.get("sdmx_value") or o.get("label") or "" for o in d.get("options") or []]
    meta_totals = [t for t in meta_totals if TOTAL_RE.match(t.strip())]
    verified = (struct_col or {}).get("aggregate_value")
    if verified:
        out["verified_aggregate"] = verified
    if values is None:
        return out
    data_totals = sorted(v for v in values if TOTAL_RE.match(v.strip()))
    if data_totals:
        out.update(total_in_data=True, total_values=data_totals[:3])
    elif meta_totals:
        out.update(total_in_data=False, total_metadata_values=meta_totals[:3],
                   total_note=M.t(lang, "describe.total_note", names=", ".join(repr(t) for t in meta_totals[:2]),
                                  col=d["dim_column_name"]))
    return out


def _structure_info(struct_col: dict | None) -> dict:
    if not struct_col:
        return {"levels": []}
    levels = []
    if struct_col.get("confidence") == "verified":
        levels = [{"level_id": l.get("level_id"), "name": l.get("name"),
                   "members": len(l.get("members") or []),
                   "default": l.get("level_id") == struct_col.get("default_level")}
                  for l in struct_col.get("levels") or [] if l.get("verified")]
    out = {"levels": levels}
    if struct_col.get("nests_in"):
        out["nests_in"] = struct_col["nests_in"]
    if struct_col.get("additive") is not None:
        out["additive"] = struct_col["additive"]
    if struct_col.get("source_mismatch"):
        out["source_mismatch"] = dict(struct_col["source_mismatch"])
    return out


def _dimension_info(code: str, d: dict, values: dict | None, struct_col: dict | None, lang: str) -> dict:
    col = d["dim_column_name"]
    is_time = d.get("dim_type") == "time"
    meta_n = d.get("option_count")
    if meta_n is None:
        meta_n = len(d.get("options") or [])
    info = {"column": col, "label": d.get("dim_label"), "type": d.get("dim_type"),
            "option_count": None if values is None else len(values),
            "metadata_option_count": meta_n,
            "examples": [] if values is None else _ordered_examples(list(values), is_time),
            "values_truncated": bool(values) and len(values) > MAX_EXAMPLES,
            **_total_info(d, values, struct_col, lang), **_structure_info(struct_col),
            "lookup": _call("find_dimension_values", dataset=code, column=col)}
    if values is None:
        info["values_note"] = M.t(lang, "describe.no_values")
    return info


def _geo_block(dims: list, struct: dict) -> dict:
    geo = [d for d in dims if d.get("dim_type") == "geo"]
    cols = [d["dim_column_name"] for d in geo]
    nesting = {}
    for c in cols:
        parent = ((struct or {}).get(c) or {}).get("nests_in")
        if parent in cols:
            nesting[c] = parent
    leaves = [c for c in cols if c not in nesting.values()]
    keys = []
    for leaf in leaves:
        chain = [leaf]
        while chain[0] in nesting:
            chain.insert(0, nesting[chain[0]])
        keys.append(chain)
    levels = {}
    for d in geo:
        counts = Counter((o.get("parsed") or {}).get("geo_level") for o in d.get("options") or [])
        counts.pop(None, None)
        levels[d["dim_column_name"]] = counts.most_common(1)[0][0] if counts else None
    return {"columns": cols, "entity_keys": keys, "nesting": nesting, "levels": levels}


def _metadata_range(dim: dict | None) -> dict | None:
    if not dim:
        return None
    vals = sorted(str(o["sdmx_value"]) for o in dim.get("options") or [] if o.get("sdmx_value"))
    if not vals:
        return None
    return {"first": vals[0], "last": vals[-1], "options": len(vals)}


def _time_block(ctx, code: str, time_dim: dict | None, has_file: bool) -> tuple[dict, list]:
    col = time_dim["dim_column_name"] if time_dim else None
    t = {"column": col, "first": None, "last": None, "frequency": None, "periods_with_data": None,
         "source": "data", "metadata_range": _metadata_range(time_dim)}
    notes = []
    if not col:
        return t, notes
    if not has_file:
        notes.append(_note("no_period_data", M.t(ctx.lang, "describe.no_period_file")))
        return t, notes
    try:
        res = data_query.dimension_values(ctx.conn, code, col, limit=1)
    except data_query.QueryError:
        notes.append(_note("no_period_data", M.t(ctx.lang, "describe.period_unreadable")))
        return t, notes
    pb = res.get("period_bounds") or {}
    t.update(first=pb.get("first"), last=pb.get("last"), periods_with_data=pb.get("periods_with_data"),
             frequency=_frequency(pb.get("last")))
    mr = t["metadata_range"]
    if mr and (mr["first"], mr["last"]) != (t["first"], t["last"]):
        notes.append(_note("metadata_period_range_differs", M.t(
            ctx.lang, "describe.metadata_range", mfirst=mr["first"], mlast=mr["last"], options=mr["options"],
            first=t["first"], last=t["last"], periods=t["periods_with_data"])))
    return t, notes


def _split_items(ctx, meta: dict) -> tuple[list, int]:
    splits = meta.get("splits") or []
    out = [{"dataset": s["matrix_code"], "label": s.get("label"), "rows": s.get("row_count"),
            "split_dimensions": dict(s["split_dimensions"]) if s.get("split_dimensions") else None,
            "quality": grain_guard.file_status(s["matrix_code"])["status"],
            "next_call": _call("describe_dataset", dataset=s["matrix_code"], lang=ctx.lang)}
           for s in splits[:MAX_SPLITS]]
    return out, len(splits)


def _shrink_describe(data: dict) -> bool:
    if any(len(d["examples"]) > 3 for d in data["dimensions"]):
        for d in data["dimensions"]:
            d["examples"] = d["examples"][:3]
        return True
    if len(data["splits"]) > 10:
        del data["splits"][10:]
        return True
    if data.get("definition") and len(data["definition"]) > 160:
        data["definition"] = data["definition"][:160].rsplit(" ", 1)[0] + " …"
        data["definition_truncated"] = True
        return True
    if any(n.get("text") and len(n["text"]) > 120 for n in data["notes"]):
        for n in data["notes"]:
            n["text"] = n["text"][:120].rsplit(" ", 1)[0] + " …"
        return True
    return False


def describe_dataset(args, ctx):
    conn, lang, code = ctx.conn, ctx.lang, args.dataset
    meta = dataset_meta.get_dataset_meta(code, lang, conn=conn)
    if meta is None:
        raise ToolFailure(
            "error", "unknown_dataset", M.t(lang, "describe.unknown", code=code),
            provenance=C.base_provenance(ctx),
            recovery=[C.recovery("tool_call", M.t(lang, "describe.find"),
                                 "discover_indicators",
                                 {"query": _ws(code.replace("_", " "))[:200], "lang": lang}),
                      C.recovery("clarify", M.t(lang, "describe.code_shape"))])
    has_file = _has_file(code)
    actx = _actx(conn, code) if has_file else None
    actual = (actx or {}).get("actual_values") or {}
    struct = (actx or {}).get("struct") or {}
    dims = meta["dimensions"]
    facts = cs.dataset_facts(conn, code, lang)
    notes = [{k: v for k, v in (("id", n.get("id")), ("kind", n.get("kind")),
                                ("text", C._short(n.get("text"), 300)[0])) if v}
             for n in meta.get("notes") or []]

    time_dim = next((d for d in dims if d.get("dim_type") == "time"), None)
    time, time_notes = _time_block(ctx, code, time_dim, has_file)
    notes += [{"id": n["code"], "kind": "interpretation", "text": n["message"]} for n in time_notes]
    dim_infos = [_dimension_info(code, d, actual.get(d["dim_column_name"]) if has_file else None,
                                 struct.get(d["dim_column_name"]), lang) for d in dims]
    splits, n_splits = _split_items(ctx, meta)
    parent = meta.get("parent")
    if not has_file:
        notes.append({"id": "no_data_file", "kind": "interpretation", "text":
                      M.t(lang, "describe.no_data_file")
                      + (M.t(lang, "describe.no_data_file_splits") if n_splits else ".")})

    grain = grain_guard.file_status(code)
    domain = _domain(actx, lang)
    if domain["complete"] is False:
        domain["complete_alternatives"] = [
            {"dataset": s, "next_call": _call("describe_dataset", dataset=s, lang=lang)}
            for s in _complete_siblings(ctx, code, domain)][:3]
    definition, cut = C._short(meta.get("definitie"))
    profile = meta.get("profile") or {}
    unit_types = (meta.get("chart_config") or {}).get("unit_types") or []
    data = {
        "dataset": code, "name": meta.get("matrix_name"), "definition": definition,
        "definition_truncated": cut, "definition_url": C.dataset_page(code, lang),
        "measure": meta.get("measure"), "unit": facts.get("unit") if facts else None,
        "unit_type": (facts or {}).get("unit_type") or profile.get("primary_unit_type"),
        "unit_types": list(unit_types) if len(unit_types) > 1 else None,
        "source_updated": meta.get("ultima_actualizare"), "url": C.dataset_page(code, lang),
        "has_data": has_file, "row_count": meta.get("row_count"),
        "time": time, "dimensions": dim_infos, "geo": _geo_block(dims, struct),
        "parent": ({"dataset": parent["matrix_code"], "name": parent.get("matrix_name"),
                    "next_call": _call("describe_dataset", dataset=parent["matrix_code"], lang=lang)}
                   if parent else None),
        "splits": splits, "splits_total": n_splits, "grain": grain, "domain": domain,
        "notes": notes,
        "examples_note": M.t(lang, "describe.examples_note")}

    warnings = _generation_warnings(ctx)
    # recorded breaks inside the data the dataset holds (all of it when the period is unknown)
    breaks = dataset_notes.series_breaks(code, lang, span=(time["first"], time["last"])
                                         if time["first"] and time["last"] else None)
    data["series_breaks"] = C.series_break_items(breaks)
    warnings += [C.warning("series_break", b["text"], b["id"]) for b in breaks]
    if grain["status"] in UNSAFE_GRAIN:
        warnings.append(C.warning(f"grain_{grain['status']}", M.t(
            lang, f"describe.grain_{'conflicting' if grain['status'] == 'conflicting' else 'duplicate_keys'}"), code))
    if domain["complete"] is False:
        warnings.append(C.warning("domain_incomplete", M.t(lang, "discover.domain_incomplete",
                                                           desc=domain["description"]), code))

    prov = {"sources": [C.source_entry(conn, code, lang)], "scope": _scope_provenance(domain, lang)}

    def build():
        return C.envelope("describe_dataset", ctx, message=message, data=data, provenance=prov,
                          warnings=warnings)

    span = f"{time['first']}–{time['last']}" if time["first"] else M.t(lang, "describe.no_period_data")
    message = M.t(lang, "describe.message", code=code, n=len(dim_infos), span=span) \
        + (M.t(lang, "describe.message_frequency", frequency=M.tx(lang).get(f"discover.freq.{time['frequency']}",
                                                                          time["frequency"]))
           if time["frequency"] else "") \
        + (M.t(lang, "describe.message_splits", n=n_splits) if n_splits else "") + "."
    env = build()
    while C.size(env) > FIT_BYTES and _shrink_describe(data):
        env = build()
    return env


# ------------------------------------------------------------------ find_dimension_values

def _canonical_column(conn, code: str, column: str) -> str:
    try:
        from app.services import query_builder as qb
        return qb.to_sdmx_name(qb.resolve_parquet_schema(conn, code), column)
    except Exception:
        return column


def _value_labels(conn, code: str, column: str, values: list) -> dict:
    """Metadata label of each returned data value (best effort; the data value
    stays the identifier)."""
    actx = _actx(conn, code)
    dim = next((d for d in (actx or {}).get("dimensions") or []
                if d["dim_column_name"] == column), None)
    if not dim:
        return {}
    by_value = {}
    for o in dim.get("options") or []:
        if o.get("sdmx_value") is not None:
            by_value.setdefault(str(o["sdmx_value"]), o.get("label"))
    return {v: _ws(by_value[v]) for v in values if by_value.get(v)}


def find_dimension_values(args, ctx):
    conn, lang, code = ctx.conn, ctx.lang, args.dataset
    try:
        res = data_query.dimension_values(conn, code, args.column, q=args.query or None,
                                          limit=args.limit, offset=args.offset)
    except data_query.QueryError as e:
        if e.status == 400 and "unknown column" in e.message:
            raise _unknown_column(ctx, code, args.column) from None
        raise C.query_failure(e, ctx, code) from None
    column = _canonical_column(conn, code, args.column)
    labels = _value_labels(conn, code, column, res["values"])
    items = [{"value": v, "label": labels.get(v, _ws(v))} for v in res["values"]]
    pb = res.get("period_bounds")
    hint = None
    warnings = _generation_warnings(ctx)
    recovery = []
    if res["total"] == 0 and args.query:
        hint = M.t(lang, "values.no_match", col=column, query=args.query)
        recovery = [C.recovery("tool_call", M.t(lang, "values.list_all"),
                               "find_dimension_values", {"dataset": code, "column": column})]
    elif res["total"] == 0:
        hint = M.t(lang, "values.none", col=column)
    elif not items:
        hint = M.t(lang, "values.past_end", offset=args.offset, total=res["total"])
    if pb and pb.get("first") and args.query and res["total"] == 0:
        hint += M.t(lang, "values.periods_with_data", first=pb["first"], last=pb["last"])
    data = {"dataset": code, "column": column, "query": args.query or None, "values": items,
            "offset": res["offset"], "limit": res["limit"], "next_offset": res["next_offset"],
            "total": res["total"], "values_truncated": res["truncated"], "period_bounds": pb,
            "order": "newest first" if pb is not None else "alphabetical (accent-insensitive)",
            "hint": hint}
    if items:
        message = (M.t(lang, "values.message", total=res["total"], col=column, first=res["offset"] + 1,
                       last=res["offset"] + len(items))
                   + (M.t(lang, "values.next_offset", n=res["next_offset"]) if res["next_offset"] is not None else "")
                   + M.t(lang, "values.use_exact"))
    else:
        message = hint
    prov = {"sources": [C.source_entry(conn, code, lang)]}
    return C.envelope("find_dimension_values", ctx, message=message, data=data, provenance=prov,
                      warnings=warnings, recovery=recovery)


def _unknown_column(ctx, code: str, column: str) -> ToolFailure:
    prov = C.base_provenance(ctx)
    describe = C.recovery("tool_call", M.t(ctx.lang, "contract.read_dataset"),
                          "describe_dataset", {"dataset": code, "lang": ctx.lang})
    if column == "OBS_VALUE":
        return ToolFailure("error", "unknown_column", M.t(ctx.lang, "values.obs_value"), provenance=prov,
                           recovery=[describe])
    actx = _actx(ctx.conn, code)
    cols = [d["dim_column_name"] for d in (actx or {}).get("dimensions") or []][:20]
    listing = M.t(ctx.lang, "values.its_columns", cols=", ".join(cols)) if cols else ""
    return ToolFailure("error", "unknown_column", M.t(ctx.lang, "values.unknown_column", code=code, col=column)
                       + listing, provenance=prov, recovery=[describe])
