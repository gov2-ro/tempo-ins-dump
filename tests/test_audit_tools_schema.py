"""PKG-TOOLS F17: an integer year is read as the same year in text."""
import pytest

from app.services.tools import schemas as S


def test_integer_year_is_coerced():
    a = S.RankEntitiesArgs.model_validate({"dataset": "X", "entity_columns": ["REF_AREA"], "year": 2025})
    assert a.year == "2025"
    b = S.RunRecipeArgs.model_validate({"recipe": "r", "year": 2019})
    assert b.year == "2019"


@pytest.mark.parametrize("bad", [True, 20.5, "25", 99, 12345])
def test_other_values_stay_invalid(bad):
    with pytest.raises(Exception):
        S.RunRecipeArgs.model_validate({"recipe": "r", "year": bad})
