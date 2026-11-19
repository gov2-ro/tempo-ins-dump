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
_Y = r'(19[5-9]\d|20[0-4]\d)'
# A span of years ("între 2015 și 2024", "from 2015 to 2024", "perioada 2015-2024"). A bare
# "2015 2024" is not one: folding turns "2015, 2024" (two years) into the same text, so a dash
# counts only in the unfolded question.
_RANGE = re.compile(
    rf'\b(?:intre|between)\s+(?:anii\s+|years\s+)?{_Y}\s+(?:si|and)\s+(?:anul\s+)?{_Y}\b|'
    rf'\b(?:din|de la|from|since)\s+(?:anul\s+)?{_Y}\s+(?:pana\s+(?:in|la)|to|until|through|till)\s+(?:anul\s+)?{_Y}\b|'
    rf'\b(?:perioada|period|anii|years)\s+{_Y}\s+{_Y}\b')
_DASH = re.compile(rf'\b{_Y}\s*[-–—]\s*{_Y}\b')
_DENOMINATOR = re.compile(r'\b((?:pe|per|la(?: un)?) locuitor|per (?:resident|inhabitant|capita)|pe cap de locuitor|'
                          r'mia de locuitori|(?:1000|1 000|100 000) (?:de )?(?:locuitori|residents|inhabitants))\b')

# Qualifiers discovery applies as exact filters, or reports (never ignores): residence, a named locality, a
# currency. They are read here and resolved against each candidate's own data file in `discovery`.
_RESIDENCE = re.compile(r'\b(rural[ae]?|rurali|urban[ae]?|urbani)\b')
_LOCALITY_CUE = re.compile(r'\b(?:(?:municipiul|municipiului|orasul|orasului|comuna|comunei|localitatea|localitatii|satul|satului)'
                           r'|(?:city|town|municipality|commune|village|locality)\s+of)\s+([a-z]+(?:\s+[a-z]+){0,3})')
_LOCALITY_STOP = frozenset(
    'in din la pe pentru si sau de a al cu for by from and or at on with during between over since per vs versus the '
    'was is este anul year years county judetul judet dupa according ordered sorted ranked'.split())
_EURO = re.compile(r'\b(euro|euros|eur)\b')
_LEI = re.compile(r'\b(lei|leu|ron)\b')


def locality_name(folded: str) -> str | None:
    """The 1-3 words after a locality cue ("municipiul", "city of"), up to a stop word or a year; None without a cue."""
    m = _LOCALITY_CUE.search(folded)
    if not m:
        return None
    words = []
    for w in m[1].split():
        if w in _LOCALITY_STOP:
            break
        words.append(w)
    return " ".join(words[:3]) or None


def qualifiers(query: str, folded: str) -> list:
    """[{kind, text, value}] for residence (value: "rural"/"urban", None when both are named), a named
    locality (value: its folded name) and a currency (value: "eur"/"ron", None when both are named)."""
    out = []
    words = [m[0] for m in _RESIDENCE.finditer(folded)]
    if words:
        stems = {w[:5] for w in words}
        out.append({"kind": "residence", "text": ", ".join(dict.fromkeys(words)),
                    "value": next(iter(stems)) if len(stems) == 1 else None})
    name = locality_name(folded)
    if name:
        out.append({"kind": "locality", "text": name, "value": name})
    euro = _EURO.findall(folded) + (["€"] if "€" in str(query) else [])
    lei = _LEI.findall(folded)
    if euro or lei:
        out.append({"kind": "currency", "text": ", ".join(dict.fromkeys(euro + lei)),
                    "value": None if euro and lei else "eur" if euro else "ron"})
    return out


def period_range(query: str) -> dict | None:
    """{"from", "to"} for a span of years the question names, earliest first; None otherwise."""
    m = _RANGE.search(fold(query)) or _DASH.search(str(query or ""))
    if not m:
        return None
    a, b = (int(y) for y in m.groups() if y)
    return {"from": a, "to": b} if a < b else None


_LAST_N = re.compile(r'\b(?:ultimii|ultimele|last|past|previous)\s+(\d{1,3})\s+(?:de\s+)?(?:ani|years?)\b')


def last_years(query: str) -> int | None:
    """N for "ultimii 30 de ani" / "the last 30 years" (1..200), else None."""
    m = _LAST_N.search(fold(query))
    return int(m[1]) if m and 1 <= int(m[1]) <= 200 else None


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
    density = bool(re.search(r'\b(densitat\w*|density)\b', t))
    correlation = bool(re.search(r'\b(correlat\w*|corelat\w*)\b', t))
    tourism_ratio = stays and per_resident and not thousands
    constraints = [{'kind': kind, 'text': m[0]} for kind, rx in (('sex', _SEX), ('age', _AGE), ('denominator', _DENOMINATOR))
                   if (m := rx.search(t)) and not (kind == 'denominator' and tourism_ratio)]
    return {'cities': cities, 'latest': latest,
            'operation': 'change' if change else 'rank' if rank or k else None,
            'top_k': int(k) if k else 30, 'order': 'asc' if bottom else 'desc',
            'tourism_ratio': tourism_ratio,
            # refused at once: a tourism ratio other than stays per resident, a correlation, a density of cities
            'unsupported_measure': (stays and thousands) or (arrivals and per_resident) or correlation
                                   or (density and cities),
            'tourism_unsupported': (stays and thousands) or (arrivals and per_resident),
            'correlation': correlation,
            # a density question is searched first (AQ-09 D5): refused only when no series exists
            'density': density,
            'period_range': period_range(query),
            'last_years': last_years(query),
            'years': sorted({int(y) for y in re.findall(_Y, t)}),
            # a city ranking keeps its own county handling (discovery_policy.county_filter), so no locality is read
            'qualifiers': [q for q in qualifiers(query, t) if not (cities and q['kind'] == 'locality')],
            'population': bool(re.search(r'\b(populati\w*|population|populate|populated)\b', t)),
            'constraints': constraints}
