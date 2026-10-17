"""Bounded interpretation for analytical discovery, preserving consequential words.

This describes supported intent; it is not a substitute for dataset validation. What a
population or ranking question defaults to is not decided here but by the reviewed
configuration (`discovery_policy`); this module only reads the words.
"""
import re
from app.services.concept_search import fold

# Words of constraints that discovery never turns into a filter itself. They are reported
# (`constraints`) so a default alias match cannot silently drop them. Folded text: no accents,
# punctuation is a space ("20-24" reads "20 24").
_SEX = re.compile(r'\b(femei\w*|feminin\w*|barbat\w*|masculin\w*|sexe|sexul|gender|women|woman|female\w*|men|male\w*)\b')
_AGE = re.compile(
    r'\b((?:peste|sub|intre|de|la|over|under|above|below|between|aged?)\s+\d{1,3}(?:\s+\d{1,3})?\s+(?:de\s+)?(?:ani|years?)|'
    r'aged?\s+\d{1,3}(?:\s+\d{1,3})?|\d{1,3}\s+\d{1,3}\s+(?:de\s+)?(?:ani|years?)|'
    r'\d{1,3}\s+(?:de\s+)?ani\s+si\s+peste|\d{1,3}\s+(?:years?\s+)?(?:and|or)\s+(?:over|older|above)|'
    r'varst\w*|ages?|aged|age groups?|copii\w*|tineri\w*|varstnic\w*|pensionar\w*|adult\w*|children|youth|'
    r'elderly|seniors?)\b')
_DENOMINATOR = re.compile(r'\b((?:pe|per|la(?: un)?) locuitor|per (?:resident|inhabitant|capita)|pe cap de locuitor|'
                          r'mia de locuitori|(?:1000|1 000|100 000) (?:de )?(?:locuitori|residents|inhabitants))\b')


def interpret(query: str) -> dict:
    t = fold(query)
    cities = bool(re.search(r'\b(orase|orasele|oraselor|municipii|municipiile|municipiilor|cities|towns)\b', t))
    latest = bool(re.search(r'\b(curent[ae]?|actual[ae]?|prezent|latest|current|now)\b', t))
    rank = bool(re.search(r'\b(top|bottom|clasament|cele mai populate|celor mai populate|most populated|largest|smallest|highest|lowest)\b', t))
    change = bool(re.search(r'\b(pierdut|scazut|crescut|crestere|scadere|grew|fell|decline|growth|change)\b', t))
    n = re.search(r'\b(?:top|bottom|largest|smallest|biggest|populate|populated)\s+(\d{1,3})\b|'
                  r'\b(?:primele|primii)\s+(\d{1,3})\s+(?:de\s+)?(?:orase|municipii|judete|localitati|regiuni)\b|'
                  r'\b(\d{1,3})\s+(?:largest|biggest|smallest|most populated)\b', t)
    k = next((g for g in n.groups() if g), None) if n else None
    bottom = bool(re.search(r'\b(bottom|smallest|lowest|cele mai mici)\b', t))
    per_resident = bool(re.search(r'\b(pe|per|la(?: un)?) locuitor\b|\bper (resident|inhabitant|capita)\b', t))
    thousands = bool(re.search(r'\b(mia de locuitori|(?:1000|1 000) (?:de )?(?:locuitori|residents|inhabitants))\b', t))
    stays = bool(re.search(r'\b(innoptari(?:le)?|overnight stays|nights|stays)\b', t))
    arrivals = bool(re.search(r'\b(turisti|sosiri|arrivals|tourists)\b', t)) and not stays
    density = bool(re.search(r'\b(densitat\w*|density|correlat\w*|corelat\w*)\b', t))
    tourism_ratio = stays and per_resident and not thousands
    constraints = [{'kind': kind, 'text': m[0]} for kind, rx in (('sex', _SEX), ('age', _AGE), ('denominator', _DENOMINATOR))
                   if (m := rx.search(t)) and not (kind == 'denominator' and tourism_ratio)]
    return {'cities': cities, 'latest': latest,
            'operation': 'change' if change else 'rank' if rank or k else None,
            'top_k': int(k) if k else 30, 'order': 'asc' if bottom else 'desc',
            'tourism_ratio': tourism_ratio,
            'unsupported_measure': density or (stays and thousands) or (arrivals and per_resident),
            'population': bool(re.search(r'\b(populati\w*|population|populate|populated)\b', t)),
            'constraints': constraints}
