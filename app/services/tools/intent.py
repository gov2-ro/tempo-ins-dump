"""Bounded interpretation for analytical discovery, preserving consequential words.

This describes supported intent; it is not a substitute for dataset validation.
"""
import re
from app.services.concept_search import fold


def interpret(query: str) -> dict:
    t = fold(query)
    cities = bool(re.search(r'\b(orase|oraselor|municipii|municipiilor|cities|towns)\b', t))
    latest = bool(re.search(r'\b(curent[ae]?|actual[ae]?|prezent|latest|current|now)\b', t))
    rank = bool(re.search(r'\b(top|bottom|clasament|cele mai populate|celor mai populate|most populated|largest|smallest|highest|lowest)\b', t))
    change = bool(re.search(r'\b(pierdut|scazut|crescut|crestere|scadere|grew|fell|decline|growth|change)\b', t))
    n = re.search(r'\b(?:top|bottom|populate|populated)\s+(\d{1,3})\b', t)
    bottom = bool(re.search(r'\b(bottom|smallest|lowest|cele mai mici)\b', t))
    per_resident = bool(re.search(r'\b(pe|per|la(?: un)?) locuitor\b|\bper (resident|inhabitant|capita)\b', t))
    thousands = bool(re.search(r'\b(mia de locuitori|(?:1000|1 000) (?:de )?(?:locuitori|residents|inhabitants))\b', t))
    stays = bool(re.search(r'\b(innoptari(?:le)?|overnight stays|nights|stays)\b', t))
    arrivals = bool(re.search(r'\b(turisti|sosiri|arrivals|tourists)\b', t)) and not stays
    density = bool(re.search(r'\b(densitat\w*|density|correlat\w*|corelat\w*)\b', t))
    return {'cities': cities, 'latest': latest, 'operation': 'change' if change else 'rank' if rank else None,
            'top_k': int(n[1]) if n else 30, 'order': 'asc' if bottom else 'desc',
            'tourism_ratio': stays and per_resident and not thousands,
            'unsupported_measure': density or (stays and thousands) or (arrivals and per_resident),
            'population': bool(re.search(r'\b(populati\w*|population)\b', t)),
            'explicit_population': bool(re.search(r'\b(rezident\w*|resident|domiciliu|domicile|iulie|july)\b', t))}
