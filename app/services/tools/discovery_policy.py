"""Reviewed defaults of `discover_indicators` (AQ-04A), as validated configuration.

AT-05 put three mappings in discovery code: the canonical phrase put in front of a
generic population question, the locality series injected for a city ranking and the
route from "overnight stays per resident" to the reviewed tourism recipe. They live in
`app/data/discovery_defaults.json` now and `plan` applies them. The policy is unchanged:

  * generic population            -> resident population, disclosed (alternatives stay)
  * generic city population rank  -> population by domicile, disclosed
  * explicit resident/July city   -> unavailable, nothing substituted
  * explicit domicile             -> respected
  * generic unemployment          -> no default (`clarify_only`): the user is asked
  * stays per resident            -> the reviewed tourism recipe
  * city change (AQ-05A)          -> compare_periods with entity_class=cities, only for two
                                     exact years and a stated direction; historical membership
                                     or constant boundaries stay unavailable

This is configuration for tool discovery only. It is not a query language and not a second
search: `plan` can put one reviewed phrase in front of the question, swap one concept's
variants for the reviewed locality series and keep one recipe concept. `concept_search`
(the catalogue and UI search) never reads it. A rule whose concept is absent from the
catalogue in use is inert: it assumes nothing and says nothing about a source that was not
selected.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from app.services import concept_search as cs
from app.services.tools import contract as C
from app.services.tools import messages as M

log = logging.getLogger(__name__)

POLICY_PATH = Path(__file__).resolve().parents[2] / "data" / "discovery_defaults.json"

LEVELS = ("locality", "county", "region", "macroregion", "national")
OPERATIONS = ("lookup", "rank", "change")
# What the shared tools can serve at a level. A rule may claim a subset, never more. At the
# locality level "change" exists only as compare_periods with entity_class=cities (AQ-05A), which
# `_structure` requires of any rule that claims it.
SERVED = {"locality": {"rank", "change"}, **{lv: set(OPERATIONS) for lv in LEVELS if lv != "locality"}}
ENTITY_CLASSES = ("all", "cities")
ROUTE_INTENTS = ("tourism_ratio",)          # flags of intent.interpret that a route may use
MAX_TOP_K = 100                             # rank_entities' own limit (schemas.RankEntitiesArgs)
DEFAULT_RANK = {"entity_columns": ["REF_AREA"], "entity_class": "all"}

_CODE = re.compile(r"[A-Za-z0-9_]+")
_COLUMN = re.compile(r"[A-Z][A-Z0-9_]*")
_TERM = re.compile(r"[a-z0-9]+\*?")


class PolicyError(ValueError):
    """The shipped configuration is invalid; discovery refuses to guess instead."""


@dataclass(frozen=True)
class Policy:
    data: dict
    term_res: dict              # definition concept id -> compiled regex of its terms


@dataclass
class Plan:
    """What discovery does with one question, decided before the shared search runs."""
    query: str                              # the question given to concept_search
    assumed: str | None = None              # concept id a default stands for
    locality: dict | None = None            # the concept with the reviewed locality variants
    locality_alias: str | None = None
    recipe: str | None = None               # concept id the question is routed to
    rank: dict = field(default_factory=lambda: {**DEFAULT_RANK, "entity_columns": list(DEFAULT_RANK["entity_columns"])})
    unapplied: list = field(default_factory=list)   # constraints discovery does not apply
    change: dict | None = None              # the one supported city change: intervals, metric, order


# ------------------------------------------------------------------ validation

def _text(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _specific_alias(concept: dict | None, phrase: str) -> bool:
    """Is `phrase` (folded) one of the concept's own specific aliases, in either language?"""
    f = cs.fold(phrase)
    return any(cs.fold(a) == f for items in ((concept or {}).get("aliases") or {}).values() for a in items)


def _structure(raw: dict) -> list:
    bad = []
    if raw.get("version") != 1:
        bad.append("version must be 1")
    pop = raw.get("population")
    if not isinstance(pop, dict):
        return bad + ["population must be an object"]
    defs = pop.get("definitions")
    if not isinstance(defs, dict) or not defs:
        bad.append("population.definitions must be a non-empty object")
        defs = {}
    for cid, d in defs.items():
        terms = d.get("terms") if isinstance(d, dict) else None
        if not isinstance(terms, list) or not terms or not all(isinstance(t, str) and _TERM.fullmatch(t) for t in terms):
            bad.append(f"definition {cid}: terms must be a non-empty list of folded words (a trailing * is any ending)")
    for name in ("default", "cities"):
        rule = pop.get(name)
        if not isinstance(rule, dict):
            bad.append(f"population.{name} must be an object")
            continue
        if rule.get("concept") not in defs:
            bad.append(f"population.{name}.concept {rule.get('concept')!r} is not a definition")
        phrase = rule.get("phrase")
        if not _text(phrase) or phrase != cs.fold(phrase):
            bad.append(f"population.{name}.phrase must be a non-empty folded phrase")
    cities = pop.get("cities") if isinstance(pop.get("cities"), dict) else {}
    variants = cities.get("variants")
    if not isinstance(variants, dict) or "locality" not in variants:
        bad.append("population.cities.variants must map the locality level")
        variants = {}
    for level, code in variants.items():
        if level not in LEVELS:
            bad.append(f"population.cities.variants: unknown level {level!r}")
        if not (isinstance(code, str) and _CODE.fullmatch(code)):
            bad.append(f"population.cities.variants.{level}: {code!r} is not a dataset code")
    ops = cities.get("operations")
    if not isinstance(ops, list) or not ops or any(o not in OPERATIONS for o in ops):
        bad.append(f"population.cities.operations must be a non-empty subset of {list(OPERATIONS)}")
    else:
        for level in variants:
            over = [o for o in ops if o not in SERVED.get(level, ())]
            if over:
                bad.append(f"population.cities.operations {over} cannot be served at level {level!r}")
    cols = cities.get("entity_columns")
    if not isinstance(cols, list) or not cols or len(set(cols)) != len(cols) \
            or not all(isinstance(c, str) and _COLUMN.fullmatch(c) and c != "TIME_PERIOD" for c in cols):
        bad.append("population.cities.entity_columns must be unique non-time dimension columns")
        cols = []
    if cities.get("entity_class") not in ENTITY_CLASSES:
        bad.append(f"population.cities.entity_class must be one of {list(ENTITY_CLASSES)}")
    elif cities["entity_class"] == "cities" and "REF_AREA_2" not in cols:
        bad.append("entity_class 'cities' requires REF_AREA_2 in entity_columns")
    if isinstance(ops, list) and "change" in ops and cities.get("entity_class") != "cities":
        bad.append("population.cities.operations 'change' is served at the locality level only "
                   "through entity_class 'cities'")
    if not _text(cities.get("alias")):
        bad.append("population.cities.alias must be a non-empty string")
    routes = raw.get("recipe_routes")
    if not isinstance(routes, list):
        bad.append("recipe_routes must be a list")
        routes = []
    seen = set()
    for r in routes:
        if not isinstance(r, dict) or r.get("intent") not in ROUTE_INTENTS or not _text(r.get("concept")):
            bad.append(f"recipe route {r!r}: intent must be one of {list(ROUTE_INTENTS)} with a concept")
            continue
        if r["intent"] in seen:
            bad.append(f"recipe route intent {r['intent']!r} is listed twice")
        seen.add(r["intent"])
        if not _text(r.get("phrase")) or r["phrase"] != cs.fold(r["phrase"]):
            bad.append(f"recipe route {r['intent']}: phrase must be a non-empty folded phrase")
    clarify = raw.get("clarify_only")
    if not isinstance(clarify, list):
        bad.append("clarify_only must be a list")
        clarify = []
    targets = {pop.get("default", {}).get("concept") if isinstance(pop.get("default"), dict) else None,
               cities.get("concept")} | {r.get("concept") for r in routes if isinstance(r, dict)}
    for entry in clarify:
        ids = entry.get("concepts") if isinstance(entry, dict) else None
        if not isinstance(ids, list) or not ids or not _text(entry.get("topic")):
            bad.append(f"clarify_only entry {entry!r} needs a topic and concepts")
        elif set(ids) & targets:
            bad.append(f"clarify_only {entry['topic']}: {sorted(set(ids) & targets)} also has a default or route")
    return bad


def _references(raw: dict, concepts: list, recipe_ids, dataset_columns) -> list:
    bad = []
    by_id = {c["id"]: c for c in concepts}
    pop = raw["population"]
    for cid in pop["definitions"]:
        if cid not in by_id:
            bad.append(f"definition {cid}: not in the concept catalogue")
    for name in ("default", "cities"):
        rule = pop[name]
        c = by_id.get(rule["concept"])
        if c is None:
            bad.append(f"population.{name}.concept {rule['concept']!r}: not in the concept catalogue")
            continue
        if not c.get("variants"):
            bad.append(f"population.{name}.concept {rule['concept']!r} has no dataset variants")
        if not _specific_alias(c, rule["phrase"]):
            bad.append(f"population.{name}.phrase {rule['phrase']!r} is not a specific alias of {rule['concept']}")
    cities = pop["cities"]
    if by_id.get(cities["concept"]) is not None and not _specific_alias(by_id[cities["concept"]], cities["alias"]):
        bad.append(f"population.cities.alias {cities['alias']!r} is not an alias of {cities['concept']}")
    if dataset_columns is not None:
        for level, code in cities["variants"].items():
            cols = dataset_columns(code)
            if cols is None:
                bad.append(f"population.cities.variants.{level}: dataset {code} does not exist")
            elif set(cities["entity_columns"]) - set(cols):
                bad.append(f"population.cities.entity_columns {sorted(set(cities['entity_columns']) - set(cols))} "
                           f"are not columns of {code}")
    for r in raw["recipe_routes"]:
        c = by_id.get(r["concept"])
        if c is None:
            bad.append(f"recipe route {r['intent']}: concept {r['concept']!r} is not in the concept catalogue")
            continue
        if not c.get("recipe"):
            bad.append(f"recipe route {r['intent']}: concept {r['concept']} is not a recipe concept")
        elif recipe_ids is not None and c["recipe"] not in recipe_ids:
            bad.append(f"recipe route {r['intent']}: recipe {c['recipe']!r} does not exist")
        if not _specific_alias(c, r["phrase"]):
            bad.append(f"recipe route {r['intent']}: phrase {r['phrase']!r} is not a specific alias of {r['concept']}")
    for entry in raw["clarify_only"]:
        for cid in entry["concepts"]:
            if cid not in by_id:
                bad.append(f"clarify_only {entry['topic']}: concept {cid!r} is not in the concept catalogue")
    return bad


def validate(raw, concepts: list | None = None, *, recipe_ids=None, dataset_columns=None) -> list:
    """Problems of a configuration; [] when it is consistent.

    Structure is always checked: shape, levels, operations a level can serve, entity columns.
    With `concepts` (the catalogue) every referenced concept, phrase and alias must exist;
    `recipe_ids` checks routed recipes; `dataset_columns(code) -> set | None` checks the
    locality datasets and the entity columns against a corpus."""
    if not isinstance(raw, dict):
        return ["the configuration must be an object"]
    bad = _structure(raw)
    if not bad and concepts is not None:
        bad = _references(raw, concepts, recipe_ids, dataset_columns)
    return bad


# ------------------------------------------------------------------ loading

_lock = threading.Lock()
_cache: dict = {}


def _terms_re(terms: list):
    return re.compile(r"\b(?:" + "|".join(re.escape(t[:-1]) + r"\w*" if t.endswith("*") else re.escape(t)
                                         for t in terms) + r")\b")


def load_policy() -> Policy:
    """The validated configuration, cached by file version. Invalid or missing: PolicyError."""
    try:
        key = (str(POLICY_PATH), POLICY_PATH.stat().st_mtime_ns)
    except OSError as e:
        raise PolicyError(f"{POLICY_PATH.name} is unreadable: {e.strerror}") from None
    with _lock:
        if key not in _cache:
            try:
                raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
            except ValueError as e:
                raise PolicyError(f"{POLICY_PATH.name} is not valid JSON: {e}") from None
            bad = validate(raw)
            if bad:
                raise PolicyError(f"{POLICY_PATH.name} is invalid: " + "; ".join(bad))
            _cache.clear()
            _cache[key] = Policy(raw, {cid: _terms_re(d["terms"]) for cid, d in raw["population"]["definitions"].items()})
        return _cache[key]


# ------------------------------------------------------------------ planning

def _refuse(status: str, reason: str, message: str):
    raise C.ToolFailure(status, reason, message)


# --- city change (AQ-05A). intent.interpret recognizes a few exact change words; for a city
# question the direction words below (stems, both languages) also mean "change", so a phrasing it
# misses ("scaderea populatiei") is refused or answered as a change, never as a plain ranking.
# Anything outside the exact supported meaning is refused, never approximated.
_DECLINE = re.compile(r"\b(?:pierd\w*|scad\w*|descresc\w*|diminu\w*|fell|fall\w*|declin\w*|"
                      r"decreas\w*|los(?:t|e|es|ing)|drop(?:s|ped|ping)?|shr[iau]nk|shrink\w*)\b")
_GROWTH = re.compile(r"\b(?:cresc\w*|crester\w*|grew|grow\w*|gain\w*|increas\w*|rose|rise\w*|rising)\b")
_LEAST = re.compile(r"\b(?:bottom|smallest|lowest|least|slowest|minim\w*|ce\w* mai (?:mic\w*|putin\w*|slab\w*))\b")
_PERCENT = re.compile(r"\b(procent\w*|percent\w*)\b")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_HISTORICAL = re.compile(
    r"\b(?:constant|unchanged|same|fixed|stable|identical)\s+(?:administrative\s+)?(?:boundar\w*|borders?|limits)\b|"
    r"\b(?:boundar\w*|borders?)\s+(?:unchanged|constant|fixed)\b|"
    r"\b(?:granit\w*\s+(?:constante|neschimbate|identice|fixe)|aceleasi\s+granit\w*|aceleasi\s+limite)\b|"
    r"\b(?:historical\w*|istoric\w*)\s+(?:status|statut|membership|classification|clasificare|cit\w+|oras\w*)\b|"
    r"\b(?:that|which|care|ce)\s+(?:were|was|erau|era)\s+(?:already\s+|deja\s+)?(?:cities|towns|a city|a town|orase|oras|municipii)\b|"
    r"\bat\s+the\s+time\b|\bla\s+acea\s+data\b")


CITY_CHANGE_NOTE = M.t("en", "policy.city_change_note")        # the English wording; discovery warns in `lang`


def asks_city_change(intent: dict, query: str) -> bool:
    """Does a city question ask for a change over time (intent's change words or a direction word)?"""
    if not intent["cities"]:
        return False
    t = cs.fold(query)
    return intent["operation"] == "change" or bool(_DECLINE.search(t) or _GROWTH.search(t))


def city_change(query: str, intent: dict, lang: str = "ro") -> dict:
    """The one supported city change meaning, parsed from the folded question: two exact years,
    a stated direction (decline: most negative first; growth: largest first) and absolute change,
    or percent change when the question says so. Raises the refusal otherwise."""
    t = cs.fold(query)
    if _HISTORICAL.search(t):
        _refuse("unavailable", "unsupported_operation", M.t(lang, "policy.city_change_historical"))
    years = sorted(set(_YEAR.findall(t)))
    if len(years) != 2:
        _refuse("unavailable", "unsupported_operation", M.t(lang, "policy.city_change_years"))
    down, up = bool(_DECLINE.search(t)), bool(_GROWTH.search(t))
    if down == up:
        _refuse("unavailable", "unsupported_operation", M.t(lang, "policy.city_change_direction"))
    if intent["order"] == "asc" or _LEAST.search(t):    # "smallest decline" is not "decline"
        _refuse("unavailable", "unsupported_operation", M.t(lang, "policy.city_change_least"))
    return {"intervals": [{"from": years[0], "to": years[1]}],
            "metric": "percent" if _PERCENT.search(t) else "absolute", "order": "asc" if down else "desc"}


def named_definitions(query: str, lang: str, policy: Policy) -> set:
    """Definitions the question names itself: by a configured term, or by one of the
    definition's specific (non-generic) aliases in the catalogue in use."""
    t = cs.fold(query)
    named = {cid for cid, rx in policy.term_res.items() if rx.search(t)}
    named |= {h["concept"]["id"] for h in cs.match_concepts(t, lang)
              if not h["generic"] and h["concept"]["id"] in policy.term_res}
    return named


def _usable(by_id: dict, rule: dict) -> bool:
    """A rule applies only while its concept and phrase exist in the catalogue in use. An
    absent concept is a normal inert rule; a present concept without the phrase is a
    configuration/catalogue mismatch (`validate` reports it) and is logged."""
    ok = _specific_alias(by_id.get(rule["concept"]), rule["phrase"])
    if not ok and rule["concept"] in by_id:
        log.error("discovery default inert: %r is not a specific alias of %s", rule["phrase"], rule["concept"])
    return ok


def plan(intent: dict, query: str, by_id: dict, lang: str, policy: Policy | None = None) -> Plan:
    """Decide the reviewed defaults, routes and refusals for one question. `by_id` is the
    concept catalogue in use. Raises ToolFailure where the policy refuses; never picks a
    definition the question names itself."""
    pol = policy or load_policy()
    pop = pol.data["population"]
    cities = pop["cities"]
    out = Plan(query=query, unapplied=list(intent["constraints"]))
    change = asks_city_change(intent, query)
    if intent["cities"] and ("change" if change else intent["operation"] or "rank") not in cities["operations"]:
        _refuse("unavailable", "unsupported_operation", M.t(lang, "policy.city_change_unsupported"))
    if intent["unsupported_measure"]:
        _refuse("unavailable", "unsupported_operation", M.t(lang, "policy.unsupported_measure"))
    named = named_definitions(query, lang, pol)
    if intent["cities"]:
        if not intent["population"]:
            _refuse("unavailable", "level_unavailable", M.t(lang, "policy.city_not_population"))
        if named - {cities["concept"]}:
            _refuse("unavailable", "level_unavailable", M.t(lang, "policy.city_resident"))
        if cities["concept"] not in by_id:
            _refuse("unavailable", "level_unavailable", M.t(lang, "policy.city_not_configured"))
        out.locality = {**by_id[cities["concept"]], "variants": dict(cities["variants"])}
        out.locality_alias = cities["alias"]
        out.rank = {"entity_columns": list(cities["entity_columns"]), "entity_class": cities["entity_class"]}
        if change:
            out.change = city_change(query, intent, lang)
    route = next((r for r in pol.data["recipe_routes"] if intent.get(r["intent"])), None)
    if route:
        if not _usable(by_id, route):
            _refuse("unavailable", "recipe_unavailable", M.t(lang, "policy.recipe_unavailable"))
        out.query, out.recipe = route["phrase"] + " " + query, route["concept"]
    elif intent["population"] and not named:
        # the city series is injected whatever the phrase does, so it is a disclosed default either way
        rule = cities if intent["cities"] else pop["default"]
        usable = _usable(by_id, rule)
        if usable:
            out.query = rule["phrase"] + " " + query
        if usable or intent["cities"]:
            out.assumed = rule["concept"]
    log.debug("discovery plan assumed=%s locality=%s recipe=%s named=%s constraints=%s", out.assumed,
              bool(out.locality), out.recipe, sorted(named), [c["kind"] for c in out.unapplied])
    if (intent["operation"] == "rank" or intent["cities"]) and not 1 <= intent["top_k"] <= MAX_TOP_K:
        _refuse("error", "invalid_input", M.t(lang, "policy.top_k_max", max=MAX_TOP_K)
                if intent["top_k"] > MAX_TOP_K else M.t(lang, "policy.top_k_min"))
    return out
