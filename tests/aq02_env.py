"""The synthetic generation behind data/eval/ask_tasks.json (AQ-02).

One corpus, composed from the existing AT-01/02/03/05 builders plus a few datasets of its own
(raw values below, so an expected number can be recomputed without the implementation):

  COUNTX A-D 1992-2020, STAYS1/RESPOP/PSTAY/PPOP/PUBM + recipes, POPC     at02_env.build_all pieces
  CITYX + GOS102A (the city catalogue)                                    test_at05_ranking
  the discovery corpus (POPK_*, AGEP_*, MONK_*, ...)                      test_at01_discovery._build
  POPD, UNEMR, UNEMI, BIRTHA, BIRTHB, MONTHX, DUPL, NOTOT, BIGLONG, PARENTX/CHILDX, POP107D_grupe_localitate,
  BIGSCAN (1,000,100 rows: over the default public scan limit)           below

`synthetic_env` also writes a concept catalogue and recipe file for them (the real catalogue
points at datasets this corpus does not have) and patches the paths like the AT-01 tests do.
"""
from __future__ import annotations

import json

import duckdb

import test_at01_discovery as disc
import test_at05_ranking as ranking
from at01_fixtures import add_dataset, add_split, make_env
from at02_env import POPC_ROWS
from test_at01_changes import area_dim, build_countx, time_dim, unit_dim
from test_at01_query import _fam_dims, _fam_rows
from test_at01_recipes_links import RECIPES as CORE_RECIPES
from test_at01_recipes_links import build_core, make_recipe

GENERATION = "gen-at01-fixture"
COUNTIES = ["Cluj", "Iași", "Bihor"]
PERSONS = "Numar persoane"
PERCENT = "Procente"

# ---------------------------------------------------------------- raw values (hand-checkable)
POPD = {"Cluj": (1030.0, 1040.0), "Iași": (920.0, 900.0), "Bihor": (610.0, 620.0)}     # 2020, 2021
UNEMR = {"Cluj": (3.0, 2.5), "Iași": (4.0, 3.5), "Bihor": (5.0, 4.5)}                    # 2020, 2021
UNEMI = {"Romania": (6.1, 5.6)}
# two published series of live births (national sum of three counties), 2023 and 2024
BIRTHS = {"BIRTHA": ("Nascuti vii dupa resedinta mamei", {"2023": (80.0, 50.0, 34.0), "2024": (78.0, 49.0, 33.0)}),
          "BIRTHB": ("Nascuti vii dupa locul nasterii", {"2023": (82.0, 52.0, 34.0), "2024": (80.0, 51.0, 34.0)})}
MONTHS = [f"{y}-{m:02d}" for y in (2023, 2024) for m in range(1, 13)][:21]              # 2023-01 .. 2024-09
MONTHX_BASE = {"Cluj": 100.0, "Iași": 200.0}


def monthx_value(county: str, month: str) -> float:
    """base + the month's position in the series (2023-01 is 1, 2024-09 is 21)."""
    return MONTHX_BASE[county] + MONTHS.index(month) + 1
DUPL = {("Alfa", "2020"): 100.0, ("Alfa", "2021"): 105.0, ("Beta", "2020"): 300.0, ("Beta", "2021"): 305.0}
NOTOT_ROWS = [("A", "2023", 50.0), ("B", "2023", 30.0), ("A", "2024", 60.0), ("B", "2024", 40.0)]
LONG_LABEL = "ș" * 100
N_CITIES = 230                                                                          # catalogue cities; one commune on top
BIGSCAN_ROWS = 1_000_100


def city_names():
    return [f"{1000 + i} ORAS CITY{i:03}" for i in range(N_CITIES)]


def city_value(i: int, year: str) -> float:
    """Population of city i (catalogue order): i + 100 in 2025, ten fewer in 2024. The commune
    row, 9999 COMMUNE, is 999,999 in both years."""
    return float(i + 100) if year == "2025" else float(i + 90)


def locality_rows(names):
    return [("County", c, year, PERSONS, city_value(i, year) if i < N_CITIES else 999999.0)
            for year in ("2024", "2025") for i, c in enumerate(names)]


def _years(*ys):
    return time_dim(tuple(ys))


def extras(corpus):
    add_dataset(corpus, "POPD", [area_dim(COUNTIES), _years("2020", "2021"), unit_dim(PERSONS)],
                [(c, y, PERSONS, v) for c, vs in POPD.items() for y, v in zip(("2020", "2021"), vs)],
                name="Populatia dupa domiciliu pe judete")
    add_dataset(corpus, "UNEMR", [area_dim(COUNTIES), _years("2020", "2021"), unit_dim(PERCENT)],
                [(c, y, PERCENT, v) for c, vs in UNEMR.items() for y, v in zip(("2020", "2021"), vs)],
                unit_type="percentage", name="Rata somajului inregistrat pe judete")
    add_dataset(corpus, "UNEMI", [area_dim(["Romania"], level="national"), _years("2020", "2021"),
                                  unit_dim(PERCENT)],
                [(c, y, PERCENT, v) for c, vs in UNEMI.items() for y, v in zip(("2020", "2021"), vs)],
                unit_type="percentage", name="Rata somajului BIM")
    for code, (name, by_year) in BIRTHS.items():
        add_dataset(corpus, code, [area_dim(COUNTIES), _years("2023", "2024"), unit_dim(PERSONS)],
                    [(c, y, PERSONS, v) for y, vs in by_year.items() for c, v in zip(COUNTIES, vs)], name=name)
    cols = [area_dim(["Cluj", "Iași"]),
            ("TIME_PERIOD", "Luni", "time", [(m, dict(year=int(m[:4]), month=int(m[5:]))) for m in MONTHS]),
            unit_dim("Numar")]
    add_dataset(corpus, "MONTHX", cols, [(c, m, "Numar", monthx_value(c, m)) for c in MONTHX_BASE for m in MONTHS],
                name="Indicator lunar lung")
    add_dataset(corpus, "DUPL", [area_dim(["Alfa", "Beta"]), area_dim(["LIVEZI"], "locality", "REF_AREA_2"),
                                 _years("2020", "2021"), unit_dim(PERSONS)],
                [(c, "LIVEZI", y, PERSONS, v) for (c, y), v in DUPL.items()], name="Localitati omonime")
    # a Total that INS lists in the metadata but the export lacks (NOTOT of test_at01_query)
    add_dataset(corpus, "NOTOT", [("CATEGORY", "Categorie", None, [("Total", {}), ("A", {}), ("B", {})]),
                                  time_dim(("2023", "2024"))], NOTOT_ROWS, name="Total doar in metadate")
    # the conflicting-child family of test_at01_query (CHILDX repeats one key with 10 and 11)
    add_dataset(corpus, "PARENTX", _fam_dims(), _fam_rows())
    add_dataset(corpus, "CHILDX", _fam_dims(), _fam_rows([("Masculin", "Nord", "2024", 11.0)]), parent="PARENTX")
    add_split(corpus, "PARENTX", "CHILDX", "CHILDX", {})
    # long Romanian labels: a raw preview that cannot fit the 32 KiB result budget
    add_dataset(corpus, "BIGLONG", [("CATEGORY", "Categorie", None, [("x", {})]), time_dim(("2024",))],
                [(f"{LONG_LABEL}{i:03d}", "2024", float(i)) for i in range(250)], name="Etichete lungi")
    # the locality series that discovery's city ranking names (the city catalogue is GOS102A)
    names = city_names() + ["9999 COMMUNE"]
    add_dataset(corpus, "POP107D_grupe_localitate",
                [area_dim(["County"]), area_dim(names, "locality", "REF_AREA_2"), _years("2024", "2025"),
                 unit_dim(PERSONS)], locality_rows(names), name="Populatia dupa domiciliu pe localitati")
    # more rows than the default public scan limit: written with DuckDB, registered metadata-only
    add_dataset(corpus, "BIGSCAN", [area_dim(["Cluj"]), _years(*[str(y) for y in range(2000, 2025)]),
                                    unit_dim("Numar")], [], file=False, name="Serie foarte mare")
    db = duckdb.connect()
    db.execute(f"COPY (SELECT 'Cluj' AS REF_AREA, (2000 + i % 25)::VARCHAR AS TIME_PERIOD, 'Numar' AS UNIT_MEASURE, "
               f"i::DOUBLE AS OBS_VALUE FROM range({BIGSCAN_ROWS}) t(i)) TO '{corpus / 'parquet' / 'BIGSCAN.parquet'}' "
               "(FORMAT PARQUET)")
    db.close()


def build_synthetic(corpus):
    """Order matters: the discovery corpus adds the search columns last (no dataset after it)."""
    build_countx(corpus)
    build_core(corpus)
    add_dataset(corpus, "POPC", [area_dim(COUNTIES), time_dim(("2020", "2021")), unit_dim(PERSONS)],
                POPC_ROWS, name="Populatie pe judete")
    ranking.build(corpus)
    extras(corpus)
    disc._build(corpus)


def concepts() -> dict:
    c = disc.concept
    return {"about": "AQ-02 fixture", "version": 1, "reviewed": "fixture", "concepts": [
        c("resident_population", "Populatia rezidenta", ["populatia rezidenta", "locuitori rezidenti"],
          variants={"county": "POPC"}, generic=["populatia", "populatie"], generic_en=["population"],
          alternatives=["domicile_population"], en=["resident population"]),
        c("domicile_population", "Populatia dupa domiciliu", ["populatia dupa domiciliu"],
          variants={"county": "POPD"}, alternatives=["resident_population"], en=["domicile population"]),
        c("registered_unemployment_rate", "Rata somajului inregistrat", ["somaj inregistrat"],
          variants={"county": "UNEMR"}, generic=["rata somajului", "somajul", "somaj"],
          generic_en=["unemployment rate", "unemployment"], alternatives=["ilo_unemployment_rate"]),
        c("ilo_unemployment_rate", "Rata somajului BIM", ["somaj bim", "somaj ilo"],
          variants={"national": "UNEMI"}, alternatives=["registered_unemployment_rate"], en=["ilo unemployment"]),
        c("monthly_indicator", "Indicator lunar lung",
          ["indicator lunar lung", "indicatorul lunar lung", "indicatorului lunar lung"], variants={"county": "MONTHX"},
          en=["long monthly indicator"]),
        c("tourism_intensity", "Intensitatea turistica", ["intensitate turistica", "innoptari pe locuitor"],
          recipe="tourism_intensity", en=["overnight stays per resident"]),
    ]}


def recipes() -> dict:
    return {"about": "AQ-02 fixture", "recipes": [
        *CORE_RECIPES, make_recipe("tourism_intensity", "STAYS1", "RESPOP"), *disc.RECIPES["recipes"]]}


def synthetic_env(tmp_path, monkeypatch):
    """Corpus + patched concept/recipe/search paths. `manifest` conflicts: CHILDX."""
    from app.services import concept_search, dataset_search
    from app.services import recipes as recipes_service
    env = make_env(tmp_path, monkeypatch, build=build_synthetic, conflicting=["CHILDX"])
    (tmp_path / "concepts.json").write_text(json.dumps(concepts(), ensure_ascii=False), encoding="utf-8")
    (tmp_path / "recipes.json").write_text(json.dumps(recipes(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(concept_search, "CONCEPTS_PATH", tmp_path / "concepts.json")
    monkeypatch.setattr(recipes_service, "RECIPES_PATH", tmp_path / "recipes.json")
    monkeypatch.setattr(dataset_search, "SEARCH_DB_PATH", tmp_path / "no-fts.duckdb")
    dataset_search._reset_for_tests()
    return env
