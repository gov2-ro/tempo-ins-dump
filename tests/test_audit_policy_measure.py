"""Audit C03: rate-like indicator names with no unit type are non-additive."""
import pytest

from app.services.aggregation_policy import dataset_measure

RATE_NAMES = [
    'Prevalenta malnutritiei in randul copiilor sub cinci ani',
    'Prevalența obezității',
    'PREVALENTA MALNUTRITIEI (GREUTATEA RAPORTATA LA INALTIME)',
    'Incidenta tuberculozei',
    'Incidența SIDA, pe sexe',
    'Mortalitatea infantila pe judete',
    'Mortalitatea maternă',
    'Natalitatea pe medii de rezidenta',
    'Fertilitatea feminina',
    'Fecunditatea pe grupe de varsta',
    'Rata somajului',
    'Prevalence of stunting among children under five',
    'Incidence of tuberculosis',
    'Infant mortality',
    'Natality by residence area',
    'Fertility by age of mother',
    'Death rates by cause',
]


@pytest.mark.parametrize('name', RATE_NAMES)
@pytest.mark.parametrize('unit_type', [None, 'other'])
def test_rate_words_are_non_additive_without_unit_type(name, unit_type):
    assert dataset_measure(unit_type, name) == 'non_additive'


@pytest.mark.parametrize('name', [
    'Numarul de nascuti-vii pe judete',
    'Decedati pe grupe de varsta',
    'Incidente de securitate raportate',
    'Imbunatatiri funciare - asigurarea fertilitatii solului',
    'Incidenta unor boli transmisibile [cazuri noi]',
])
def test_counts_stay_additive(name):
    assert dataset_measure(None, name) == 'additive'


def test_count_unit_type_is_not_overridden_by_name():
    assert dataset_measure('count', 'Prevalenta malnutritiei') == 'additive'
