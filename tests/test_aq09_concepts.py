"""AQ-09 B: reviewed concepts for common indicators (GDP, life expectancy, infant mortality, ...)."""
import pytest

from app.services import concept_search as cs

NEW = ["gdp_per_inhabitant", "gdp_regional", "life_expectancy", "infant_mortality_rate",
       "infant_mortality_domicile", "dwellings_completed", "pupils_by_education_level", "exports_annual"]


def top(q, lang="ro"):
    hits = cs.match_concepts(cs.fold(q), lang)
    return hits[0]["concept"]["id"] if hits else None


@pytest.mark.parametrize("q,lang,cid", [
    ("top cele mai mari și cele mai mici 5 județe cu venituri/PIB per capita", "ro", "gdp_per_inhabitant"),
    ("PIB pe locuitor în județul Cluj", "ro", "gdp_per_inhabitant"),
    ("Which counties have the highest GDP per capita?", "en", "gdp_per_inhabitant"),
    ("PIB total pe județe", "ro", "gdp_regional"),
    ("speranța de viață la naștere", "ro", "life_expectancy"),
    ("Average life expectancy in Romania by sex over time", "en", "life_expectancy"),
    ("Care județ are cea mai mare rată a mortalității infantile?", "ro", "infant_mortality_rate"),
    ("infant mortality rate by county", "en", "infant_mortality_rate"),
    ("Top 5 județe după numărul de locuințe noi terminate în 2023", "ro", "dwellings_completed"),
    ("completed dwellings in Cluj", "en", "dwellings_completed"),
    ("Câți elevi sunt în învățământul liceal în județul Iași în 2022?", "ro", "pupils_by_education_level"),
    ("Romania total exports by year", "en", "exports_annual"),
    ("exporturi anuale ale României", "ro", "exports_annual"),
    # EN aliases of the earnings concepts (sweep Q05)
    ("Which 10 counties have the highest average gross monthly wage?", "en", "gross_earnings"),
    ("average gross monthly salary by county", "en", "gross_earnings"),
    ("average net monthly wage in Cluj", "en", "net_earnings"),
])
def test_question_finds_its_reviewed_concept(q, lang, cid):
    assert top(q, lang) == cid


def test_diacritics_do_not_matter():
    assert top("Speranța de viață", "ro") == top("speranta de viata", "ro") == "life_expectancy"
    assert top("mortalității infantile") == top("mortalitatii infantile") == "infant_mortality_rate"


def test_a_bare_wage_is_a_generic_match_with_alternatives():
    hits = cs.match_concepts(cs.fold("wage"), "en")
    assert hits and hits[0]["generic"] and "gross_earnings" in hits[0]["concept"]["alternatives"]


def test_exports_by_country_is_not_the_annual_total_concept():
    assert top("exporturi pe tari") is None


def test_each_new_concept_has_levels_notes_and_both_languages():
    by_id = {c["id"]: c for c in cs.load_concepts()}
    ids = set(by_id)
    for cid in NEW:
        c = by_id[cid]
        assert c["variants"] and c["family"]
        assert c["aliases"]["ro"] and c["aliases"]["en"]
        assert c["note"]["ro"] and c["note"]["en"] and c["name"]["ro"] and c["name"]["en"]
        assert set(c.get("alternatives", [])) <= ids
        for lang in ("ro", "en"):
            for a in c["aliases"][lang]:
                assert cs.fold(a) == a, f"{cid}: alias {a!r} must be stored folded (no diacritics, lower case)"


def test_a_specific_alias_belongs_to_one_concept():
    seen = {}
    for c in cs.load_concepts():
        for lang in ("ro", "en"):
            for a in (c.get("aliases") or {}).get(lang, []):
                assert seen.setdefault(cs.fold(a), c["id"]) == c["id"], a


def test_the_old_caen_series_is_named_as_not_comparable():
    c = next(c for c in cs.load_concepts() if c["id"] == "gdp_per_inhabitant")
    assert "CON103B" in c["note"]["en"] and "not comparable" in c["note"]["en"]
    assert "CON103B" in c["note"]["ro"] and "nu este comparabilă" in c["note"]["ro"]


@pytest.mark.corpus
@pytest.mark.parametrize("cid,first,last", [
    ("gdp_per_inhabitant", "2000", "2022"), ("gdp_regional", "2000", "2022"),
    ("life_expectancy", "2008", "2023"), ("infant_mortality_rate", "2012", "2024"),
    ("infant_mortality_domicile", "1990", "2024"), ("dwellings_completed", "1990", "2025"),
    ("pupils_by_education_level", "1990", "2024"), ("exports_annual", "2006", "2024")])
def test_corpus_variants_exist_and_cover_the_period_the_note_names(cid, first, last):
    from app.db import get_conn
    conn = get_conn()
    c = next(c for c in cs.load_concepts() if c["id"] == cid)
    for level, code in c["variants"].items():
        facts = cs.dataset_facts(conn, code, "en")
        assert facts, f"{cid}/{level}: {code} has no served data file"
        assert (str(facts["coverage"]["first"]), str(facts["coverage"]["last"])) == (first, last), (cid, level, code)
        assert f"{first}–{last}" in c["note"]["en"] or f"{first}-{last}" in c["note"]["en"], cid
