"""AQ-02A: the versioned task set (data/eval/ask_tasks.json) is valid, complete, bilingual and
hand-checkable.

Every expected number is recomputed here from the fixture's raw cells with plain arithmetic: DuckDB
reads the generated Parquet files (or, for INS published cells, the metadata table) directly, never a
tool result, so an expectation cannot be a copy of what the implementation returned. Cases pinned to a
copied generation are recomputed from that generation's Parquet files and skip individually when it is
absent or another generation. Nothing here rebuilds a search or chart baseline.
"""
import json
import os
import re
from pathlib import Path

import duckdb
import pytest

import aq02_env as A
from aq02_tasks import (HARD, LANGS, TASKS_PATH, load_taskset, norm, number_candidates, numbers_in, pattern_in,
                        phrase_in, safe_eval, states_number, stray_numbers, turns_of, validate_taskset)
from app.services.tools import registry

DOC = load_taskset()
TASKS = {t["id"]: t for t in DOC["tasks"]}
REQUIRED = [f"T{i:02d}" for i in range(1, 21)] + [f"X{i:02d}" for i in range(1, 13)]
PACKAGES = {"AQ-03", "AQ-04"}
MINIMUM = {"X01": "per-resident", "X02": "current county population", "X03": "top cities", "X04": "resident population",
           "X05": "density", "X06": "unemployment", "X07": "birth", "X08": "change", "X09": "follow-up",
           "X10": "wrong unit", "X11": "public limit", "X12": "election"}


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """The synthetic generation, built once for this module (and read by plain DuckDB below)."""
    from app.services import dataset_search
    mp = pytest.MonkeyPatch()
    try:
        yield A.synthetic_env(tmp_path_factory.mktemp("aq02-tasks"), mp).corpus
    finally:
        mp.undo()
        dataset_search._reset_for_tests()


def cells(corpus_dir: Path, code: str, agg="sum(OBS_VALUE)", **where):
    """An aggregate of the Parquet cells of a dataset matching column = value (or column in list)."""
    clauses, params = [], []
    for col, val in where.items():
        if isinstance(val, (list, tuple)):
            clauses.append(f"{col} IN ({', '.join('?' * len(val))})")
            params += list(val)
        else:
            clauses.append(f"{col} = ?")
            params.append(val)
    sql = f"select {agg} from read_parquet(?) " + (f"where {' and '.join(clauses)}" if clauses else "")
    row = duckdb.connect().execute(sql, [str(corpus_dir / "parquet" / f"{code}.parquet"), *params]).fetchone()
    return row[0]


# ------------------------------------------------------------------ the file itself

def test_the_task_file_is_valid():
    assert validate_taskset(DOC, registry.tool_names()) == []
    assert DOC["schema"] == "ask-tasks/1" and DOC["version"]
    assert Path(TASKS_PATH).name == "ask_tasks.json" and "baseline" not in Path(TASKS_PATH).name


def test_the_at04_tasks_and_the_minimum_extra_cases_are_present_with_stable_ids():
    ids = [t["id"] for t in DOC["tasks"]]
    assert len(ids) == len(set(ids))
    assert set(REQUIRED) <= set(ids)
    assert all(re.fullmatch(r"[TX]\d{2}[A-Z]?", i) for i in ids)
    # the twelve minimum cases of the spec table keep its order
    for tid, word in MINIMUM.items():
        assert word in TASKS[tid]["title"].lower(), (tid, word)


def test_every_prompt_and_answer_exists_in_both_languages_and_they_differ():
    for t in DOC["tasks"]:
        for turn in turns_of(t):
            for key in ("prompt", "answer"):
                if key in turn:
                    ro, en = turn[key]["ro"], turn[key]["en"]
                    assert ro.strip() and en.strip() and ro != en, (t["id"], key)
        for n in t.get("negatives", []):
            assert n["answer"]["ro"] != n["answer"]["en"]


def test_ro_and_en_answers_state_the_same_figures():
    def figures(text):
        return [set(c) for _, c in numbers_in(text)]

    def covered(a, b):
        return all(any(x & y for y in b) for x in a)
    for t in DOC["tasks"]:
        texts = [turn["answer"] for turn in turns_of(t) if "answer" in turn] + [n["answer"] for n in t.get("negatives", [])]
        texts += [t["pinned"]["answer"]] if t.get("pinned") and "answer" in t["pinned"] else []
        for a in texts:
            ro, en = figures(a["ro"]), figures(a["en"])
            assert covered(ro, en) and covered(en, ro), (t["id"], a["ro"], a["en"])


def test_only_documented_known_limitations_exist():
    for t in DOC["tasks"]:
        if t.get("known_failure"):
            assert t["known_failure"]["package"] in PACKAGES and len(t["known_failure"]["note"]) > 30
        for n in t.get("negatives", []):
            if n.get("known_limitation"):
                assert n["known_limitation"]["package"] in PACKAGES and n["detect"]["app"] == "accepted"
                assert set(n["detect"]["hard"]) <= set(HARD)


# ------------------------------------------------------------------ fixture references

def test_the_declared_synthetic_fixture_is_the_built_one(corpus):
    declared = DOC["fixtures"]["synthetic-v1"]
    db = duckdb.connect(str(corpus / "metadata.duckdb"), read_only=True)
    built = sorted(r[0] for r in db.execute("select matrix_code from matrices").fetchall())
    assert declared["datasets"] == built
    manifest = json.loads((corpus / "generation-manifest.json").read_text())
    assert manifest["generation_id"] == declared["generation"] == A.GENERATION
    assert (Path(__file__).resolve().parent.parent / declared["builder"].split(":")[0]).exists()
    for t in DOC["tasks"]:
        for turn in turns_of(t):
            for step in turn.get("steps", []):
                ds = (step.get("arguments") or {}).get("dataset")
                if ds and t["fixture"] == "synthetic-v1":
                    assert ds in built, (t["id"], ds)


def test_task_fixtures_are_declared_and_pinned_cases_name_the_copied_generation():
    for t in DOC["tasks"]:
        assert t["fixture"] in DOC["fixtures"]
        if t.get("pinned"):
            fx = DOC["fixtures"][t["pinned"]["fixture"]]
            assert fx["kind"] == "copied" and fx["generation_prefix"] == "9b3e065d"
    assert sorted(t["id"] for t in DOC["tasks"] if t.get("pinned")) == ["X01", "X02", "X03", "X07", "X08"]
    assert [t["id"] for t in DOC["tasks"] if DOC["fixtures"][t["fixture"]]["kind"] == "copied"] == ["X03B"]


# ------------------------------------------------------------------ independent arithmetic (synthetic)

def oracle(corpus):
    """(task, number id) -> the value recomputed from raw cells. Plain sums and differences."""
    c = lambda code, **w: cells(corpus, code, **w)           # noqa: E731
    mean = lambda code, **w: cells(corpus, code, agg="avg(OBS_VALUE)", **w)   # noqa: E731
    singles = [f"{a} ani" for a in range(5)]
    pub = duckdb.connect(str(corpus / "metadata.duckdb"), read_only=True).execute(
        "select value from published_totals where matrix_code = 'PUBM' and ref_area = 'Alfa' and time_period = '2024'"
    ).fetchone()[0]
    by_city = duckdb.connect().execute(
        "select TIME_PERIOD, sum(OBS_VALUE) v from read_parquet(?) where REF_AREA_2 <> '9999 COMMUNE' "
        "group by TIME_PERIOD, REF_AREA_2 order by v desc", [str(corpus / "parquet" / "POP107D_grupe_localitate.parquet")]).fetchall()
    top = {y: [v for yy, v in by_city if yy == y][:30] for y in ("2024", "2025")}
    ratio = lambda area, y: c("STAYS1", REF_AREA=area, TIME_PERIOD=y) / c("RESPOP", REF_AREA=area, TIME_PERIOD=y)   # noqa: E731
    change = lambda e, a, b: c("COUNTX", REF_AREA=e, TIME_PERIOD=b) - c("COUNTX", REF_AREA=e, TIME_PERIOD=a)       # noqa: E731
    pct = lambda e, a, b: change(e, a, b) / c("COUNTX", REF_AREA=e, TIME_PERIOD=a) * 100                           # noqa: E731
    popc = lambda county, y: c("POPC", REF_AREA=county, TIME_PERIOD=y)                                            # noqa: E731
    return {
        ("T01", "cluj_2021"): popc("Cluj", "2021"), ("T02", "cluj_2021"): popc("Cluj", "2021"),
        ("T04", "cluj_2024_09"): c("MONTHX", REF_AREA="Cluj", TIME_PERIOD="2024-09"),
        ("T06", "alfa_ratio"): ratio("Alfa", "2024"),
        ("T06", "alfa_stays"): c("STAYS1", REF_AREA="Alfa", TIME_PERIOD="2024"),
        ("T06", "alfa_population"): c("RESPOP", REF_AREA="Alfa", TIME_PERIOD="2024"),
        ("T07", "published_cell"): pub,
        ("T07", "reconstruction"): c("PSTAY", REF_AREA="Alfa", TIME_PERIOD="2024") / c("PPOP", REF_AREA="Alfa", TIME_PERIOD="2024"),
        ("T08", "b_1992_2002"): change("B", "1992", "2002"), ("T08", "b_from"): c("COUNTX", REF_AREA="B", TIME_PERIOD="1992"),
        ("T08", "b_to"): c("COUNTX", REF_AREA="B", TIME_PERIOD="2002"), ("T08", "a_1992_2002"): change("A", "1992", "2002"),
        ("T08", "d_2010_2020"): change("D", "2010", "2020"), ("T08", "a_2010_2020"): change("A", "2010", "2020"),
        ("T08", "b_2010_2020"): change("B", "2010", "2020"), ("T08", "c_2010_2020"): change("C", "2010", "2020"),
        ("T09", "alfa_from"): c("DUPL", REF_AREA="Alfa", TIME_PERIOD="2020"), ("T09", "alfa_to"): c("DUPL", REF_AREA="Alfa", TIME_PERIOD="2021"),
        ("T09", "beta_from"): c("DUPL", REF_AREA="Beta", TIME_PERIOD="2020"), ("T09", "beta_to"): c("DUPL", REF_AREA="Beta", TIME_PERIOD="2021"),
        ("T10", "single_year_total_2025"): c("POPX", AGE=singles, TIME_PERIOD="2025"),
        ("T10B", "parent_total_2024"): c("PARENTX", TIME_PERIOD="2024"),
        ("T11", "ages_0_2"): c("AGEP_judete_varste", REF_AREA="Cluj", TIME_PERIOD="2023"),
        ("T11", "all_ages"): c("AGEP_judete_grupe", REF_AREA="Cluj", TIME_PERIOD="2023"),
        ("T12", "category_a"): c("NOTOT", CATEGORY="A", TIME_PERIOD="2024"), ("T12", "category_b"): c("NOTOT", CATEGORY="B", TIME_PERIOD="2024"),
        ("T16", "cluj_2021"): popc("Cluj", "2021"), ("T16", "iasi_2021"): popc("Iași", "2021"), ("T16", "iasi_2020"): popc("Iași", "2020"),
        ("T17", "cluj_2021"): popc("Cluj", "2021"),
        ("T18", "mean_2023"): mean("RATEX", TIME_PERIOD="2023"), ("T18", "mean_2024"): mean("RATEX", TIME_PERIOD="2024"),
        ("T20", "cluj_2021"): popc("Cluj", "2021"), ("T20C", "held_call_completes"): popc("Cluj", "2021"),
        ("X01", "beta_ratio"): ratio("Beta", "2024"),
        ("X02", "bihor_2021"): popc("Bihor", "2021"), ("X02", "cluj_2021"): popc("Cluj", "2021"), ("X02", "iasi_2021"): popc("Iași", "2021"),
        ("X03", "rank_1"): top["2025"][0], ("X03", "rank_2"): top["2025"][1], ("X03", "rank_3"): top["2025"][2],
        ("X03", "rank_30"): top["2025"][29],
        ("X04B", "rank_1"): top["2025"][0], ("X04B", "rank_2"): top["2025"][1], ("X04B", "rank_3"): top["2025"][2],
        ("X06", "ilo_2020"): c("UNEMI", TIME_PERIOD="2020"), ("X06", "ilo_2021"): c("UNEMI", TIME_PERIOD="2021"),
        ("X07", "births_a_2023"): c("BIRTHA", TIME_PERIOD="2023"), ("X07", "births_b_2023"): c("BIRTHB", TIME_PERIOD="2023"),
        ("X08", "d_percent"): pct("D", "2010", "2020"), ("X08", "a_percent"): pct("A", "2010", "2020"), ("X08", "b_percent"): pct("B", "2010", "2020"),
        ("X09", "rank_1_2025"): top["2025"][0], ("X09", "rank_2_2025"): top["2025"][1], ("X09", "rank_3_2025"): top["2025"][2],
        ("X09", "rank_1_2024"): top["2024"][0], ("X09", "rank_2_2024"): top["2024"][1], ("X09", "rank_3_2024"): top["2024"][2],
        ("X10", "cluj_2021"): popc("Cluj", "2021"), ("X10", "iasi_2021"): popc("Iași", "2021"),
        ("X10B", "b_change"): change("B", "1992", "2002"), ("X10B", "b_from"): c("COUNTX", REF_AREA="B", TIME_PERIOD="1992"),
        ("X10B", "b_to"): c("COUNTX", REF_AREA="B", TIME_PERIOD="2002"),
    }


def synthetic_numbers():
    for t in DOC["tasks"]:
        if t["fixture"] != "synthetic-v1":
            continue
        for i, turn in enumerate(turns_of(t)):
            for n in turn.get("expect", {}).get("numbers", []):
                yield t["id"], n


def test_every_expected_number_is_recomputed_from_raw_cells(corpus):
    expected = oracle(corpus)
    seen = set()
    for tid, n in synthetic_numbers():
        key = (tid, n["id"])
        assert key in expected, f"no independent recomputation for {key}"
        got = expected[key]
        assert got == pytest.approx(n["value"], rel=1e-9, abs=1e-9), (key, got, n["value"])
        assert safe_eval(n["derivation"]) == pytest.approx(n["value"], rel=1e-9, abs=1e-9)
        seen.add(key)
    assert seen == set(expected), set(expected) - seen         # no stale oracle entry either


def test_the_spec_examples_hold(corpus):
    c = lambda code, **w: cells(corpus, code, **w)           # noqa: E731
    assert c("STAYS1", REF_AREA="Alfa", TIME_PERIOD="2024") / c("RESPOP", REF_AREA="Alfa", TIME_PERIOD="2024") == 2   # 120 stays / 60 residents
    cities = sorted(c("POP107D_grupe_localitate", REF_AREA_2=f"{1000 + i} ORAS CITY{i:03}", TIME_PERIOD="2025")
                    for i in range(A.N_CITIES))
    assert cities[-1] == 329 and cities[-1] > cities[-2]                              # the winner is row 230 of 231, after row 200
    commune = c("POP107D_grupe_localitate", REF_AREA_2="9999 COMMUNE", TIME_PERIOD="2025")
    assert commune == 999999 and commune > cities[-1]                                 # a larger commune that must stay out
    assert cells(corpus, "POP107D_grupe_localitate", agg="count(distinct REF_AREA_2)", TIME_PERIOD="2025") == 231


def test_the_forbidden_figures_are_the_wrong_answers_they_claim_to_be(corpus):
    c = lambda code, **w: cells(corpus, code, **w)           # noqa: E731
    assert c("POPX", TIME_PERIOD="2025") == 220                                       # singles + the 0-4 band, double counted
    assert c("CHILDX", TIME_PERIOD="2024") == 111                                     # every raw row, 11 repeating a key
    assert c("DUPL", TIME_PERIOD="2020") == 400 and c("DUPL", TIME_PERIOD="2021") == 410          # the namesakes merged
    assert c("BIRTHA", TIME_PERIOD="2023") + c("BIRTHB", TIME_PERIOD="2023") == 332
    assert c("NOTOT", TIME_PERIOD="2024") == 100                                      # the guessed Total
    assert c("POPD", REF_AREA="Cluj", TIME_PERIOD="2021") == 1040                     # the domicile figure, not the resident one
    assert c("AGEP_judete_varste", REF_AREA="Cluj", TIME_PERIOD="2023") == 33         # ages 0-2 only
    assert c("STAYS1", REF_AREA="Beta", TIME_PERIOD="2024") == 50                     # the count, not the ratio


# ------------------------------------------------------------------ the scripted answers

def positive_texts():
    for t in DOC["tasks"]:
        for i, turn in enumerate(turns_of(t)):
            if "answer" in turn:
                yield t["id"], i, turn
        if t.get("pinned") and "answer" in t["pinned"]:
            yield t["id"] + "/pinned", 0, t["pinned"]


def test_each_correct_answer_states_its_numbers_and_no_other_figure():
    for tid, i, turn in positive_texts():
        expect = turn.get("expect", {})
        values = [float(n["value"]) for n in expect.get("numbers", [])]
        allowed = [float(x) for x in (expect.get("answer") or {}).get("allowed_numbers", [])]
        for lang in LANGS:
            text = turn["answer"][lang]
            if turn.get("shown") is False:
                continue                                     # the app writes its own notice; the script text is never shown
            for n in expect.get("numbers", []):
                if n.get("stated", True):
                    assert states_number(text, float(n["value"])), (tid, i, lang, n["id"], text)
            if (expect.get("answer") or {}).get("check_numbers", bool(values) or (expect.get("answer") or {}).get("no_numbers")):
                assert not stray_numbers(text, values, allowed), (tid, i, lang, stray_numbers(text, values, allowed))


def test_correct_answers_hold_their_mandatory_statements_and_no_forbidden_claim():
    for tid, i, turn in positive_texts():
        expect = turn.get("expect", {})
        if turn.get("shown") is False:
            continue
        for lang in LANGS:
            text = turn["answer"][lang]
            for q in expect.get("qualifications", []):
                if q.get("answer_any"):
                    assert phrase_in(text, q["answer_any"][lang]), (tid, i, lang, q["id"])
            for f in expect.get("forbidden", []):
                if f.get("on") == "visible":
                    continue
                assert not pattern_in(text, f.get("answer_pattern", {}).get(lang, [])), (tid, i, lang, f["id"])
                assert not [v for v in f.get("numbers", []) if states_number(text, float(v))], (tid, i, lang, f["id"])


def test_each_wrong_answer_trips_the_check_it_declares():
    """A control is only meaningful if its text really is wrong for the stated reason: statically,
    the declared forbidden pattern/number matches it, the declared missing statement is absent, the
    declared figure is not stated or a stray figure is present."""
    controls = 0
    for t in DOC["tasks"]:
        turn = turns_of(t)[-1]
        expect = turn["expect"]
        values = [float(n["value"]) for n in expect.get("numbers", [])]
        allowed = [float(x) for x in (expect.get("answer") or {}).get("allowed_numbers", [])]
        for neg in t.get("negatives", []):
            controls += 1
            assert neg["answer"] != turn["answer"]
            for lang in LANGS:
                text = neg["answer"][lang]
                for need in neg["detect"]["fails"]:
                    kind, _, ident = need.partition(".")
                    if kind == "forbidden":
                        f = next(x for x in expect["forbidden"] if x["id"] == ident)
                        assert pattern_in(text, f.get("answer_pattern", {}).get(lang, [])) or any(
                            states_number(text, float(v)) for v in f.get("numbers", [])), (t["id"], neg["id"], lang, need)
                    elif kind == "qualification":
                        q = next(x for x in expect["qualifications"] if x["id"] == ident)
                        assert not phrase_in(text, q["answer_any"][lang]), (t["id"], neg["id"], lang, need)
                    elif kind == "stated":
                        n = next(x for x in expect["numbers"] if x["id"] == ident)
                        assert not states_number(text, float(n["value"])), (t["id"], neg["id"], lang, need)
                    elif need == "answer_numbers":
                        assert stray_numbers(text, values, allowed), (t["id"], neg["id"], lang)
                    else:
                        assert kind in ("bound", "verification", "outcome"), need        # decided by the app's own verdict
    assert controls >= 15


# ------------------------------------------------------------------ helpers the checks rely on

def test_safe_eval_is_arithmetic_only():
    assert safe_eval("(100 - 120) / 120 * 100") == pytest.approx(-100 / 6)
    for bad in ("__import__('os').system('true')", "[1][0]", "a + 1", "2 ** 8", "1 if 1 else 2", "abs(-1)"):
        with pytest.raises((ValueError, SyntaxError)):
            safe_eval(bad)


def test_numbers_are_read_in_both_notations_and_codes_are_not_numbers():
    assert states_number("În 2021: 1.010 persoane", 1010) and states_number("In 2021: 1,010 persons", 1010)
    assert states_number("4,91 înnoptări", 4.910854809317534) and states_number("4.91 stays", 4.910854809317534)
    assert not states_number("4,92 înnoptări", 4.910854809317534)
    assert states_number("variația: -50 persoane", -50) and not states_number("a crescut cu 50", -50)
    assert [t for t, _ in numbers_in("POPC GOS102A STAYS1 tempo-tools/2 2020–2021 0-4")] == ["2020", "2021", "0"]
    assert sorted(number_candidates("1.010")) == [1.01, 1010.0] and number_candidates("1.010.200") == [1010200.0]
    assert norm("Iași – Brașov") == "iasi - brasov"
    assert stray_numbers("Cluj 1010 în 2021 și 77", [1010], [2021]) == ["77"]


# ------------------------------------------------------------------ pinned cases (copied generation)

def copied_dir():
    data = os.environ.get("TEMPO_DATA_DIR")
    if not data:
        pytest.skip("TEMPO_DATA_DIR not set: copied-generation cases not run")
    corpus = Path(data) / "corpus"
    if not (corpus / "metadata.duckdb").exists():
        pytest.skip("no corpus under TEMPO_DATA_DIR")
    gen = json.loads((corpus / "generation-manifest.json").read_text()).get("generation_id") or ""
    prefix = DOC["fixtures"]["copied-9b3e065d"]["generation_prefix"]
    if not gen.startswith(prefix):
        pytest.skip(f"copied generation {gen[:8]} is not {prefix}")
    return corpus


@pytest.mark.corpus
def test_pinned_numbers_are_recomputed_from_the_copied_generations_parquet():
    corpus = copied_dir()
    c = lambda code, **w: cells(corpus, code, **w)           # noqa: E731
    county = lambda year: {r[0]: r[1] for r in duckdb.connect().execute(     # noqa: E731
        "select REF_AREA, sum(OBS_VALUE) from read_parquet(?) where TIME_PERIOD = ? group by 1",
        [str(corpus / "parquet" / "POP105A_judete_grupe.parquet"), year]).fetchall()}
    def ranked(year):
        """City populations of a year, largest first: catalogue cities only (SIRUTA key of GOS102A)."""
        return duckdb.connect().execute("""
            with cat as (select distinct cast(regexp_extract(REF_AREA_2, '^\\s*(\\d+)\\s', 1) as bigint) siruta
                         from read_parquet(?) where regexp_matches(REF_AREA_2, '^\\s*\\d+\\s+(MUNICIPIUL|ORAS)', 'i'))
            select REF_AREA_2, sum(OBS_VALUE) v from read_parquet(?) where TIME_PERIOD = ?
              and cast(regexp_extract(REF_AREA_2, '^\\s*(\\d+)\\s', 1) as bigint) in (select siruta from cat)
            group by 1 order by v desc, 1""",
            [str(corpus / "parquet" / "GOS102A.parquet"), str(corpus / "parquet" / "POP107D_grupe_localitate.parquet"), year]).fetchall()
    eligible, eligible25 = ranked("2026"), ranked("2025")
    c12, c21, c26 = county("2012"), county("2021"), county("2026")
    losses = sorted(c21[k] - c12[k] for k in c12)
    expected = {
        ("X01", "brasov_ratio_2025"): c("TUR105D_judete", REF_AREA="Brasov", TIME_PERIOD="2025")
        / c("POP105A_judete_grupe", REF_AREA="Brasov", TIME_PERIOD="2025"),
        ("X01", "brasov_stays_2025"): c("TUR105D_judete", REF_AREA="Brasov", TIME_PERIOD="2025"),
        ("X01", "brasov_population_2025"): c("POP105A_judete_grupe", REF_AREA="Brasov", TIME_PERIOD="2025"),
        ("X02", "alba_2026"): c26["Alba"], ("X02", "arad_2026"): c26["Arad"],
        ("X03", "rank_1"): eligible[0][1], ("X03", "rank_2"): eligible[1][1], ("X03", "rank_3"): eligible[2][1],
        ("X03", "rank_30"): eligible[29][1],
        ("X03B", "rank_1"): eligible25[0][1], ("X03B", "rank_2"): eligible25[1][1], ("X03B", "rank_3"): eligible25[2][1],
        ("X03B", "rank_30"): eligible25[29][1],
        ("X07", "births_pop201e_2023"): c("POP201E", TIME_PERIOD="2023"), ("X07", "births_pop201d_2023"): c("POP201D", TIME_PERIOD="2023"),
        ("X08", "prahova_change"): c21["Prahova"] - c12["Prahova"], ("X08", "prahova_from"): c12["Prahova"],
        ("X08", "prahova_to"): c21["Prahova"],
        ("X08", "bucuresti_change"): c21["Municipiul Bucuresti"] - c12["Municipiul Bucuresti"],
        ("X08", "teleorman_change"): c21["Teleorman"] - c12["Teleorman"], ("X08", "olt_change"): c21["Olt"] - c12["Olt"],
        ("X08", "buzau_change"): c21["Buzau"] - c12["Buzau"],
    }
    seen = set()
    for t in DOC["tasks"]:
        block = t.get("pinned") or (t if DOC["fixtures"][t["fixture"]]["kind"] == "copied" else None)
        if not block:
            continue
        for n in block["expect"].get("numbers", []):
            key = (t["id"], n["id"])
            assert key in expected, key
            assert expected[key] == pytest.approx(n["value"], rel=1e-12), (key, expected[key], n["value"])
            assert safe_eval(n["derivation"]) == pytest.approx(n["value"], rel=1e-12)
            seen.add(key)
    assert seen == set(expected)
    # the ranking facts the pinned cases assert
    assert len(eligible) == 319 and losses[:5] == [-58119, -58085, -53623, -47904, -45281] and len(c12) == 42
    facts = TASKS["X03"]["pinned"]["expect"]["calls"][1]["equals"]
    assert facts["/data/eligible_count"] == len(eligible)
    assert facts["/data/outside_class_count"] == duckdb.connect().execute(
        "select count(distinct REF_AREA_2) from read_parquet(?) where TIME_PERIOD = '2026'",
        [str(corpus / "parquet" / "POP107D_grupe_localitate.parquet")]).fetchone()[0] - len(eligible)
