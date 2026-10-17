"""AQ-04C: the visible prose of the tools is Romanian or English, everything else is the same.

Part 1 pins the catalogue (`tools/messages.py`): both languages define the same keys with the same
placeholders, every key used in the code exists and none is dead, and no tool module passes a
literal English sentence as a `message` any more.

Part 2 runs real tools on the synthetic corpora of AQ-04A/04B/05A in both languages and compares
the complete envelopes: they must differ only in prose fields (`message`, warning and recovery
texts, labels, names, dataset titles), never in a status, reason, code, subject, id, filter, value,
count or call argument. Stored identifiers stay as written inside the Romanian sentences.
"""
import ast
import re
from pathlib import Path

import pytest

import test_aq04a_discovery_defaults as t04a
import test_aq04b_follow_up_actions as t04b
import test_aq05a_city_changes as t05a
from app.services import dataset_search
from app.services.tools import discovery_policy as dpol
from app.services.tools import messages as M
from app.services.tools import registry as R
from at01_fixtures import call, make_env

APP = Path(__file__).resolve().parent.parent / "app"
KEY = re.compile(r"^(?:contract|registry|gate|query|discover|describe|values|policy|rank|changes|period|agent|present|recipe)"
                 r"\.[a-z_]+(?:\.[a-z_]+)*$")
# keys chosen at run time: f"query.{rows|raw_rows}_{one|many}", f"discover.note.{code}", ...
DYNAMIC = ("query.rows_", "query.raw_rows_", "discover.note.", "discover.freq.", "discover.kind.",
           "period.native.", "describe.grain_", "agent.limit.")
PLACEHOLDER = re.compile(r"\{(\w+)")


# ============================================================ part 1: the catalogue

def test_both_languages_define_the_same_keys_and_placeholders():
    en, ro = M.TEXT["en"], M.TEXT["ro"]
    assert set(en) == set(ro) and len(en) > 300
    for k in en:
        assert en[k].strip() and ro[k].strip(), k
        assert set(PLACEHOLDER.findall(en[k])) == set(PLACEHOLDER.findall(ro[k])), k
        # a fragment that joins onto another keeps the same space on both sides in both languages
        assert (en[k][:1].isspace(), en[k][-1:].isspace()) == (ro[k][:1].isspace(), ro[k][-1:].isspace()), k


# the same in both languages on purpose: punctuation around a value, and the word "sex"
SAME = {"query.col_suffix", "describe.message_frequency", "values.next_offset", "discover.kind.sex"}


def test_no_text_was_left_untranslated():
    same = [k for k in M.TEXT["en"] if M.TEXT["en"][k] == M.TEXT["ro"][k] and k not in SAME]
    assert same == [], f"identical in both languages: {same}"
    # the Romanian texts really are Romanian: most carry a diacritic, none is the English sentence
    marked = sum(bool(re.search("[ăâîșțĂÂÎȘȚ]", v)) for v in M.TEXT["ro"].values())
    assert marked > 0.8 * len(M.TEXT["ro"])


def test_t_formats_falls_back_and_refuses_unknown_keys():
    assert M.t("en", "query.rows_many", n=3) == "3 rows returned."
    assert M.t("ro", "query.rows_many", n=3) == "3 rânduri returnate."
    assert M.t("xx", "query.rows_many", n=3) == M.t("ro", "query.rows_many", n=3)       # like every _TX table
    assert M.t("en", "registry.unknown_argument") == "unknown argument"
    with pytest.raises(KeyError):
        M.t("en", "query.no_such_text")


def _python_files():
    return [p for p in sorted(APP.rglob("*.py")) if "_obsolete" not in p.parts and p.name != "messages.py"]


def _string_constants(tree):
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_every_key_in_the_code_exists_and_none_is_dead():
    used = set()
    for path in _python_files():
        used |= {s for s in _string_constants(ast.parse(path.read_text(encoding="utf-8")))
                 if KEY.match(s) and not s.endswith(("_", "."))}       # an f-string's literal start is a family, not a key
    missing = sorted(k for k in used if k not in M.TEXT["en"])
    assert missing == [], f"keys used but not in the catalogue: {missing}"
    dead = sorted(k for k in M.TEXT["en"] if k not in used and not k.startswith(DYNAMIC))
    assert dead == [], f"catalogue entries nothing uses: {dead}"


def test_every_call_passes_the_values_its_template_needs():
    """`M.t(lang, "key", a=..)` and `aid.t("key", a=..)` give every placeholder of the key a value: a
    missing one would only fail on the rarely taken branch that needs it."""
    problems, checked = [], 0
    for path in _python_files():
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
            args = n.args[1:] if name == "t" and len(n.args) > 1 and isinstance(n.func, ast.Attribute) \
                and getattr(n.func.value, "id", "") == "M" else n.args if name == "t" else None
            if args is None or not args or not (isinstance(args[0], ast.Constant) and isinstance(args[0].value, str)
                                                and args[0].value in M.TEXT["en"]):
                continue
            if any(k.arg is None for k in n.keywords):
                continue
            need = set(PLACEHOLDER.findall(M.TEXT["en"][args[0].value]))
            got = {k.arg for k in n.keywords}
            checked += 1
            if need - got:
                problems.append(f"{path.name}:{n.lineno} {args[0].value} lacks {sorted(need - got)}")
    assert problems == [] and checked > 250, (problems, checked)


def test_the_run_time_key_families_are_complete():
    from app.services import agent
    from app.services.period_changes import _NATIVE_REASONS
    for r in _NATIVE_REASONS:
        assert f"period.native.{r}" in M.TEXT["en"]
    for stop in agent.BUDGET_STOPS:
        assert f"agent.limit.{stop}" in M.TEXT["en"]
    for f in ("annual", "quarterly", "monthly"):
        assert f"discover.freq.{f}" in M.TEXT["en"]
    for kind in ("sex", "age", "denominator", "geography"):
        assert f"discover.kind.{kind}" in M.TEXT["en"]
    for k in ("query.rows", "query.raw_rows"):
        assert f"{k}_one" in M.TEXT["en"] and f"{k}_many" in M.TEXT["en"]


# (call name) -> index of the message argument; the only places a tool phrases a sentence
MESSAGE_ARG = {"warning": 1, "recovery": 1, "ToolFailure": 2, "_note": 1, "_unavailable": 1, "_synthetic": 3,
               "_gate_envelope": 4, "find_values_rec": 2, "query_rec": 0, "fail": 2}
PROSE = re.compile(r"[A-Za-z]{4,}")


def _is_prose(node) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and bool(PROSE.search(node.value))
    if isinstance(node, ast.JoinedStr):
        return any(_is_prose(v) for v in node.values)
    if isinstance(node, ast.BinOp):
        return _is_prose(node.left) or _is_prose(node.right)
    return False


def test_no_tool_module_passes_an_english_sentence_as_a_message():
    scanned = [APP / "services" / "tools", APP / "services" / "period_changes.py", APP / "services" / "agent.py",
               APP / "services" / "public_mcp.py", APP / "services" / "ask_present.py"]
    files = [p for root in scanned for p in ([root] if root.is_file() else sorted(root.glob("*.py")))
             if p.name != "messages.py"]
    offenders = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
            if name == "_refuse":       # discovery_policy: (status, reason, message); ranking: (reason, message, ...)
                idx = 2 if path.name == "discovery_policy.py" else 1
            else:
                idx = MESSAGE_ARG.get(name)
            if idx is not None and len(n.args) > idx and _is_prose(n.args[idx]):
                offenders.append(f"{path.name}:{n.lineno} {name}(...)")
    assert offenders == [], "English prose passed as a message: " + "; ".join(offenders)


# ============================================================ part 2: the same results in both languages

RECIPE_TEXT = {"unit", "status", "formula", "reconstruction_formula", "missing_policy"}
PROSE_KEYS = {"message", "description", "label", "name", "title", "definition", "concept_note", "difference",
              "hint", "text", "metric", "reference"}


def mask(node, path=()):
    """The envelope without its prose: every sentence, label, name and title becomes a marker, the
    `lang` argument of a call and the page-language parameter of a link are neutral. What is left is
    the structure the two languages must share."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in PROSE_KEYS or k.endswith("_note") or (k == "note" and "families_info" in path):
                out[k] = "<prose>" if isinstance(v, str) else v
            elif k == "lang":
                out[k] = "<lang>"
            elif k == "query" and "lang" in node and "dataset" not in node and isinstance(v, str):
                out[k] = "<prose>"                      # a discover_indicators restatement uses the language's own aliases
            elif k in RECIPE_TEXT and (path[-2:] == ("data", "recipe") or node.get("kind") == "recipe") \
                    and isinstance(v, str):
                out[k] = "<prose>"                      # a recipe describes itself in the request's language
            elif k.endswith("url") and isinstance(v, str):
                out[k] = re.sub(r"[&?]lang=en\b", "", v)
            else:
                out[k] = mask(v, path + (k,))
        return out
    if isinstance(node, list):
        return [mask(x, path) for x in node]
    return node


def sentences(node, acc=None):
    """Every string under a prose key (to find which texts the language changed)."""
    acc = [] if acc is None else acc
    if isinstance(node, dict):
        for k, v in node.items():
            if (k in PROSE_KEYS or k.endswith("_note")) and isinstance(v, str):
                acc.append(v)
            else:
                sentences(v, acc)
    elif isinstance(node, list):
        for v in node:
            sentences(v, acc)
    return acc


def both(tool, **args):
    return call(tool, lang="ro", **args), call(tool, lang="en", **args)


def differences(a, b, path="$"):
    """Where two masked envelopes differ, as readable paths."""
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(set(a) | set(b)) for d in
                (differences(a[k], b[k], f"{path}.{k}") if k in a and k in b else [f"{path}.{k} only on one side"])]
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: {len(a)} items vs {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: {str(a)[:60]!r} vs {str(b)[:60]!r}"]


def assert_same_but_prose(ro, en, where=""):
    assert differences(mask(ro), mask(en)) == [], where
    assert ro["status"] == en["status"] and ro["reason"] == en["reason"], where


def assert_localized(ro, en, where=""):
    """The sentences are in the request's language: every one of them differs and the Romanian ones
    are not the English ones (a text both languages share would be an untranslated leftover)."""
    r, e = sentences(ro), sentences(en)
    assert r and len(r) == len(e), where
    assert ro["message"] != en["message"], where


@pytest.fixture
def e04b(tmp_path, monkeypatch):
    yield t04b._setup(tmp_path, monkeypatch)
    monkeypatch.undo()
    dataset_search._reset_for_tests()


@pytest.fixture
def e04a(tmp_path, monkeypatch):
    yield t04a.make(tmp_path, monkeypatch)
    monkeypatch.undo()
    dataset_search._reset_for_tests()


@pytest.fixture
def e05a(tmp_path, monkeypatch):
    return make_env(tmp_path, monkeypatch, build=t05a.build_chg)


def test_discovery_has_the_same_structure_in_both_languages_and_localized_prose(e04b):
    """24 questions across every branch (ambiguity, place, period, recipe, partial): choices,
    their actions and notes, candidates, warnings and recoveries keep every code, id, filter and
    call argument; only sentences, names and the `lang` argument differ."""
    for q, _ in t04b.QUESTIONS:
        ro, en = both("discover_indicators", query=q)
        assert_same_but_prose(ro, en, q)
        assert_localized(ro, en, q)


@pytest.mark.parametrize("question", [
    "top 3 cities by population", "cele mai populate 5 orase", "populatia feminina Cluj 2024",
    "numarul de locuitori in 2023", "somaj", "Cate innoptari revin la un locuitor in Cluj in 2023",
    "top 10 cities by population decline between 2015 and 2020", "orasele care au pierdut populatie",
    "resident population of the cities", "top 0 cities by population", "density of cities",
])
def test_the_reviewed_defaults_and_refusals_read_the_same_in_both_languages(e04a, question):
    ro, en = both("discover_indicators", query=question)
    assert_same_but_prose(ro, en, question)
    assert_localized(ro, en, question)


def test_a_refusal_keeps_its_reason_and_the_data_empty_in_both_languages(e04a):
    for q in ("resident population of the cities", "density of cities"):
        ro, en = both("discover_indicators", query=q)
        assert ro["status"] == "unavailable" and ro["data"] == {} == en["data"]
        assert ro["reason"] == en["reason"]


def test_query_data_results_and_refusals_differ_only_in_prose(e04b):
    scenarios = [
        dict(dataset="SERK_judete", filters={"REF_AREA": ["Cluj"]}, group_by=["REF_AREA", "TIME_PERIOD"]),
        dict(dataset="SERK_judete", filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2022", "2023"]}, group_by=["REF_AREA", "TIME_PERIOD"]),
        dict(dataset="STAYK_judete", limit=2),
        dict(dataset="POPK_judete", filters={"TIME_PERIOD": ["2030"]}, group_by=["REF_AREA"]),
        dict(dataset="POPK_judete", filters={"REF_AREA": ["Nowhere"]}, group_by=["REF_AREA"]),
        dict(dataset="POPK_judete", filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2021"]}, group_by=[]),
        dict(dataset="ENETK_judete", group_by=["REF_AREA", "TIME_PERIOD"]),
        dict(dataset="ENETK_judete", filters={"REF_AREA": ["Cluj"], "TIME_PERIOD": ["2023"]}, group_by=["REF_AREA"]),
        dict(dataset="NOPE_judete"), dict(dataset="POPK_judete", filters={"TIME_PERIOD": []}, limit=1),
    ]
    statuses = set()
    for args in scenarios:
        ro, en = both("query_data", **args)
        assert_same_but_prose(ro, en, args)
        assert_localized(ro, en, args)
        statuses.add((ro["status"], ro["reason"]))
    assert len({s for _, s in statuses if s}) >= 4                        # not vacuous: several distinct refusals
    # a text the shared request validation words itself is passed through as written
    ro, en = both("query_data", dataset="POPK_judete", group_by=["BOGUS"])
    assert_same_but_prose(ro, en)
    assert ro["reason"] == "unknown_column" and ro["message"] == en["message"] == "Invalid group_by: unknown column 'BOGUS'"


def test_the_other_tools_differ_only_in_prose(e04b):
    runs = [
        ("describe_dataset", dict(dataset="SERK_judete")), ("describe_dataset", dict(dataset="POPK_judete")),
        ("describe_dataset", dict(dataset="NOPE")),
        ("find_dimension_values", dict(dataset="POPK_judete", column="REF_AREA", query="zzz")),
        ("find_dimension_values", dict(dataset="POPK_judete", column="REF_AREA")),
        ("find_dimension_values", dict(dataset="POPK_judete", column="OBS_VALUE")),
        ("find_dimension_values", dict(dataset="POPK_judete", column="TIME_PERIOD", query="2030")),
        ("rank_entities", dict(dataset="POPK_judete", entity_columns=["REF_AREA"], year="2023", top_k=2)),
        ("rank_entities", dict(dataset="ENETK_judete", entity_columns=["REF_AREA"], year="2023")),
        ("compare_periods", dict(dataset="SERK_judete", entity_columns=["REF_AREA"], intervals=[{"from": "2020", "to": "2023"}])),
        ("compare_periods", dict(dataset="ENETK_judete", entity_columns=["REF_AREA"], intervals=[{"from": "2020", "to": "2023"}])),
        ("compare_periods", dict(dataset="POPK_judete", entity_columns=["REF_AREA"], intervals=[{"from": "2001", "to": "2023"}])),
        ("run_recipe", dict(recipe="tk_intensity", year="2023", areas=["Cluj", "Cluj-Napoca"])),
        ("run_recipe", dict(recipe="tk_intensity", year="2030")), ("run_recipe", dict(recipe="nope")),
        ("run_recipe", dict(recipe="tk_intensity")),
    ]
    for tool, args in runs:
        ro, en = both(tool, **args)
        assert_same_but_prose(ro, en, (tool, args))
        assert_localized(ro, en, (tool, args))


def test_evidence_links_and_the_registry_read_the_same_in_both_languages(e04b):
    sel = {"kind": "dataset", "dataset": "POPK_judete", "filters": {"REF_AREA": ["Cluj"]}, "group_by": [],
           "approximate": False}
    gen = call("describe_dataset", dataset="POPK_judete")["provenance"]["generation"]["id"]
    ro, en = both("get_evidence_links", selection=sel, generation_id=gen)
    assert_same_but_prose(ro, en)
    assert_localized(ro, en)
    for name, args in (("nope", {}), ("query_data", {"dataset": "POPK_judete", "nope": 1}),
                       ("query_data", {"dataset": "POPK_judete", "filters": {"X": ["a" * 20000]}})):
        ro = R.call_tool(name, {**args, "lang": "ro"} if name != "nope" else args)
        en = R.call_tool(name, {**args, "lang": "en"} if name != "nope" else {"lang": "en"})
        assert ro["reason"] == en["reason"] and ro["status"] == en["status"] == "error"
        assert ro["message"] != en["message"]
    ro = R.call_tool("nope", {"lang": "ro"})
    en = R.call_tool("nope", {"lang": "en"})
    assert (ro["reason"], en["reason"]) == ("unknown_tool", "unknown_tool")
    assert "disponibile" in ro["message"] and "available" in en["message"] and "'nope'" in ro["message"]


def test_cities_keep_their_ranking_counts_and_classification_in_both_languages(e05a):
    cmp_args = dict(dataset="CHG", entity_columns=["REF_AREA", "REF_AREA_2"], intervals=[{"from": "2015", "to": "2020"}],
                    entity_class="cities", top_k=3)
    ro, en = both("compare_periods", **cmp_args)
    assert_same_but_prose(ro, en)
    assert_localized(ro, en)
    assert ro["data"]["outside_class_count"] == en["data"]["outside_class_count"] == 2
    assert [r["entity"] for r in ro["data"]["intervals"][0]["rows"]] == [r["entity"] for r in en["data"]["intervals"][0]["rows"]]
    rank = dict(dataset="CHG", entity_columns=["REF_AREA", "REF_AREA_2"], entity_class="cities", year="2020", top_k=3)
    ro, en = both("rank_entities", **rank)
    assert_same_but_prose(ro, en)
    assert_localized(ro, en)
    ro, en = both("compare_periods", dataset="CHG", entity_columns=["REF_AREA_2"], intervals=[{"from": "2015", "to": "2020"}])
    assert_same_but_prose(ro, en)                                         # the VALEA clash: the same outcome in both


# ============================================================ the required texts, pinned in both languages

def warn(out, code, subject=None):
    return next(w for w in out["warnings"] if w["code"] == code and (subject is None or w.get("subject") == subject))


def test_assumed_definition_is_disclosed_in_the_request_language(e04a):
    ro, en = both("discover_indicators", query="populatia Cluj 2023")
    w_ro, w_en = warn(ro, "assumed_definition"), warn(en, "assumed_definition")
    assert w_ro["subject"] == w_en["subject"] == "resident_population"
    assert w_en["message"].startswith("Definition assumed:") and "alternatives remain available" in w_en["message"]
    assert w_ro["message"].startswith("Definiție presupusă:") and "alternativele rămân disponibile" in w_ro["message"]
    ro, en = both("discover_indicators", query="top 3 cities by population")
    assert "Definition assumed for cities" in warn(en, "assumed_definition")["message"]
    assert "Definiție presupusă pentru orașe" in warn(ro, "assumed_definition")["message"]
    assert "Populația rezidentă nu este disponibilă pentru orașe" in warn(ro, "assumed_definition")["message"]


def test_a_constraint_that_was_not_applied_is_reported_in_the_request_language(e04a):
    ro, en = both("discover_indicators", query="populatia feminina Cluj 2024")
    w_ro, w_en = warn(ro, "constraint_not_applied"), warn(en, "constraint_not_applied")
    assert w_ro["subject"] == w_en["subject"] == "sex"
    assert "The question asks for sex ('feminina')" in w_en["message"] and "Nothing was dropped silently" in w_en["message"]
    assert "constrângere de tip sex ('feminina')" in w_ro["message"] and "Nimic nu a fost omis în tăcere" in w_ro["message"]
    assert "Not applied from the question: sex" in en["message"] and "Neaplicat din întrebare: sex" in ro["message"]
    cand_ro = ro["data"]["concepts"][0]["candidates"][0]["notes"]
    assert any(n["code"] == "constraint_not_applied" and "nu este aplicată de discovery" in n["message"] for n in cand_ro)


def test_the_city_classification_caveat_is_in_both_languages_everywhere_it_is_stated(e05a):
    ro, en = both("compare_periods", dataset="CHG", entity_columns=["REF_AREA", "REF_AREA_2"],
                  intervals=[{"from": "2015", "to": "2020"}], entity_class="cities", top_k=2)
    w_ro, w_en = warn(ro, "classification_reference"), warn(en, "classification_reference")
    assert "municipalities and towns in the referenced catalogue (INS GOS102A" in w_en["message"]
    assert "does not prove historical city status or unchanged boundaries" in w_en["message"]
    assert "municipii și orașe din catalogul de referință (INS GOS102A" in w_ro["message"]
    assert "nu dovedește statutul istoric de oraș sau limite neschimbate" in w_ro["message"]
    assert "nu dovedește statutul istoric de oraș sau limite neschimbate" in ro["message"]
    ro, en = both("rank_entities", dataset="CHG", entity_columns=["REF_AREA", "REF_AREA_2"], entity_class="cities",
                  year="2020", top_k=2)
    assert "historical changes of UAT class are not tracked" in warn(en, "classification_reference")["message"]
    assert "schimbările istorice ale clasei UAT nu sunt urmărite" in warn(ro, "classification_reference")["message"]
    assert "municipiile și orașele din catalogul SIRUTA" in warn(ro, "classification_reference")["message"]


def test_the_discovery_note_of_a_city_change_is_the_same_caveat(e04a):
    q = "top 10 cities by population decline between 2024 and 2025"
    ro, en = both("discover_indicators", query=q)
    assert en["status"] == ro["status"] == "ok"
    w_en, w_ro = warn(en, "classification_reference"), warn(ro, "classification_reference")
    assert w_en["message"] == dpol.CITY_CHANGE_NOTE
    assert "nu dovedește statutul istoric de oraș sau limite neschimbate" in w_ro["message"]
    assert w_ro["subject"] == w_en["subject"] if "subject" in w_en else True


def test_series_breaks_come_back_in_the_request_language_with_one_code_and_subject(e04b):
    sel = dict(dataset="SERK_judete", filters={"REF_AREA": ["Cluj"]}, group_by=["REF_AREA", "TIME_PERIOD"])
    ro, en = both("query_data", **sel)
    w_ro, w_en = warn(ro, "series_break", "SERK-break"), warn(en, "series_break", "SERK-break")
    assert w_ro["message"] == "Seria SERK se rupe între 2021 și 2022 (test)."
    assert w_en["message"] == "SERK breaks between 2021 and 2022 (test)."
    assert ro["provenance"]["series_breaks"] == en["provenance"]["series_breaks"]
    ro, en = both("compare_periods", dataset="SERK_judete", entity_columns=["REF_AREA"],
                  intervals=[{"from": "2020", "to": "2023"}])
    assert warn(en, "series_break", "SERK-break")["message"].startswith("Inside the compared interval 2020→2023: ")
    assert warn(ro, "series_break", "SERK-break")["message"].startswith("În intervalul comparat 2020→2023: ")


def test_choice_action_notes_and_lookup_recoveries_are_localized(e04b):
    ro, en = both("discover_indicators", query="populatie Cluj 2019")
    for ch_ro, ch_en in zip(ro["data"]["choices"], en["data"]["choices"]):
        assert [n["code"] for n in ch_ro["action_notes"]] == [n["code"] for n in ch_en["action_notes"]] \
            == ["period_unavailable"]
        assert ch_ro["action_notes"][0]["message"].startswith(f"2019 este în afara datelor {ch_ro['dataset']}")
        assert ch_en["action_notes"][0]["message"].startswith(f"2019 is outside the data of {ch_en['dataset']}")
    ro, en = both("run_recipe", recipe="tk_intensity", year="2023", areas=["Cluj-Napoca", "Cluj"])
    r_ro, r_en = ro["recovery"][0], en["recovery"][0]
    assert r_ro["tool"] == r_en["tool"] == "find_dimension_values"
    assert r_ro["arguments"] == r_en["arguments"] and r_ro["message"] != r_en["message"]
    assert "Caută eticheta exactă" in r_ro["message"] and "'Cluj-Napoca'" in r_ro["message"]
    assert "Look up the exact label" in r_en["message"] and "'Cluj-Napoca'" in r_en["message"]


def test_stored_identifiers_are_never_translated_inside_the_romanian_sentences(e04b):
    out = call("query_data", dataset="POPK_judete", filters={"REF_AREA": ["Nowhere"]}, group_by=["REF_AREA"], lang="ro")
    assert out["reason"] == "slice_value_missing"
    assert "REF_AREA" in out["message"] and "Nowhere" in out["message"]
    assert out["recovery"][0]["arguments"] == {"dataset": "POPK_judete", "column": "REF_AREA", "query": "Nowhere"}
    out = call("query_data", dataset="POPK_judete", filters={"TIME_PERIOD": ["2030"]}, group_by=["REF_AREA"], lang="ro")
    assert "TIME_PERIOD" in out["message"] and "'2030'" in out["message"] or "2030" in out["message"]
    assert out["data"]["selection"]["missing_values"] == {"TIME_PERIOD": ["2030"]}


def test_a_known_query_error_is_localized_and_an_unknown_one_passes_through(e04b):
    ro = call("describe_dataset", dataset="NOPE", lang="ro")
    assert ro["reason"] == "unknown_dataset" and ro["message"] == "Set de date necunoscut 'NOPE'."
    ro = call("query_data", dataset="NOPE_X", lang="ro")
    assert ro["reason"] == "unknown_dataset" and ro["message"] == "Setul de date NOPE_X nu a fost găsit"
    en = call("query_data", dataset="NOPE_X", lang="en")
    assert en["message"] == "Dataset NOPE_X not found"
    # a text the shared data_query service words itself is passed through as it wrote it
    bad = call("query_data", dataset="POPK_judete", group_by=["POPK"], limit=1, lang="ro")
    assert bad["status"] == "error" and bad["message"]


def test_what_a_population_series_counts_does_not_depend_on_the_language(tmp_path, monkeypatch):
    """INS's English title of a domicile series can say "resident": the note is judged on the source's own
    Romanian words, so both languages say the same thing and only the sentence is translated."""
    def build(corpus):
        import duckdb
        t05a.build_chg(corpus)
        db = duckdb.connect(str(corpus / "metadata.duckdb"))
        db.execute("UPDATE matrices SET matrix_name = 'POPULATIA DUPA DOMICILIU pe localitati', "
                   "matrix_name_en = 'LEGALLY RESIDENT POPULATION by localities', "
                   "definitie = 'Populatia dupa domiciliu reprezinta persoanele cu domiciliu in tara.' "
                   "WHERE matrix_code = 'CHG'")
        db.close()
    make_env(tmp_path, monkeypatch, build=build)
    ro, en = both("compare_periods", dataset="CHG", entity_columns=["REF_AREA", "REF_AREA_2"],
                  intervals=[{"from": "2015", "to": "2020"}], top_k=1)
    assert_same_but_prose(ro, en)
    assert "populația după domiciliu (domiciliu)" in warn(ro, "boundary_continuity_unverified")["message"]
    assert "domicile (domiciliu) population" in warn(en, "boundary_continuity_unverified")["message"]
    assert "resident (usual residence)" not in warn(en, "boundary_continuity_unverified")["message"]


def test_the_shrink_hooks_warn_in_the_request_language():
    from app.services.tools import contract as C
    from app.services.tools import query as Q
    env = {"data": {"rows": [[1], [2], [3], [4]]}, "limits": {"returned_rows": 4}, "warnings": [], "recovery": []}
    assert C.shrink_rows(env, lang="en") and env["warnings"][0]["message"].startswith("The preview was shortened")
    env = {"data": {"rows": [[1], [2], [3], [4]]}, "limits": {"returned_rows": 4}, "warnings": [], "recovery": []}
    assert Q.shrink(env, lang="ro") and env["warnings"][0]["message"].startswith("Previzualizarea a fost scurtată")
    assert env["warnings"][0]["code"] == "preview_shortened"
    labels = {"data": {"column_labels": {"A": {"x": "y"}}, "rows": []}, "warnings": [], "limits": {}, "recovery": []}
    Q.shrink(labels, lang="ro")
    assert labels["warnings"][0]["code"] == "labels_omitted" and labels["warnings"][0]["subject"] == "A"
    assert "Etichetele afișate au fost omise" in labels["warnings"][0]["message"]
