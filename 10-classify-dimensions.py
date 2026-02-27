#!/usr/bin/env python3
"""
10-classify-dimensions.py — Batch classify and parse all INS dimension options.

Creates two new DuckDB tables:
  - dimension_options_parsed  : parsed values for every unique nom_item_id
  - matrix_profiles           : per-dataset archetype and structural profile

Usage:
    python 10-classify-dimensions.py                     # Process all datasets
    python 10-classify-dimensions.py --matrix ACC101B    # Single dataset (testing)
    python 10-classify-dimensions.py --debug             # Verbose per-option logging
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict

import duckdb

from duckdb_config import DB_FILE


# ── Normalization helpers ──────────────────────────────────────────────────────

def strip_diacritics(s: str) -> str:
    """Convert Romanian diacritics to ASCII for comparison."""
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')


def norm(s: str) -> str:
    """Strip whitespace, lowercase, remove diacritics."""
    return strip_diacritics(s.strip().lower())


# ── County set ────────────────────────────────────────────────────────────────

# From profiling/ins_validation_rules.py (with diacritics stripped for comparison)
COUNTIES_NORM = {
    'alba', 'arad', 'arges', 'bacau', 'bihor', 'bistrita-nasaud',
    'botosani', 'brasov', 'braila', 'buzau', 'caras-severin',
    'calarasi', 'cluj', 'constanta', 'covasna', 'dambovita',
    'dolj', 'galati', 'giurgiu', 'gorj', 'harghita', 'hunedoara',
    'ialomita', 'iasi', 'ilfov', 'maramures', 'mehedinti',
    'mures', 'neamt', 'olt', 'prahova', 'satu mare', 'salaj',
    'sibiu', 'suceava', 'teleorman', 'timis', 'tulcea',
    'vaslui', 'valcea', 'vrancea', 'bucuresti',
    # variants seen in data
    'bistrita nasaud', 'caras severin', 'dambovita',
}


# ── Roman numerals ────────────────────────────────────────────────────────────

ROMAN = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4}


# ── Romanian month names ──────────────────────────────────────────────────────

RO_MONTHS = {
    'ianuarie': 1, 'ian': 1,
    'februarie': 2, 'feb': 2,
    'martie': 3,   'mar': 3,
    'aprilie': 4,  'apr': 4,
    'mai': 5,
    'iunie': 6,    'iun': 6,
    'iulie': 7,    'iul': 7,
    'august': 8,   'aug': 8,
    'septembrie': 9, 'sep': 9, 'sept': 9,
    'octombrie': 10, 'oct': 10,
    'noiembrie': 11, 'nov': 11,
    'decembrie': 12, 'dec': 12,
}


# ── Unit of measure lookup ────────────────────────────────────────────────────
# (unit_type, unit_scale, currency)

UNIT_MAP = {
    'procente':                ('percentage', 1,          None),
    '%':                       ('percentage', 1,          None),
    'procente puncte':         ('percentage', 1,          None),
    'puncte procentuale':      ('percentage', 1,          None),
    'pp':                      ('percentage', 1,          None),
    'numar':                   ('count',      1,          None),
    'nr.':                     ('count',      1,          None),
    'nr':                      ('count',      1,          None),
    'numar de cazuri':         ('count',      1,          None),
    'numar de persoane':       ('count',      1,          None),
    'persoane':                ('count',      1,          None),
    'mii persoane':            ('count',      1_000,      None),
    'mii':                     ('count',      1_000,      None),
    'milioane':                ('count',      1_000_000,  None),
    'lei':                     ('currency',   1,          'RON'),
    'mii lei':                 ('currency',   1_000,      'RON'),
    'mil. lei':                ('currency',   1_000_000,  'RON'),
    'milioane lei':            ('currency',   1_000_000,  'RON'),
    'miliarde lei':            ('currency',   1_000_000_000, 'RON'),
    'euro':                    ('currency',   1,          'EUR'),
    'mii euro':                ('currency',   1_000,      'EUR'),
    'milioane euro':           ('currency',   1_000_000,  'EUR'),
    'dolari sua':              ('currency',   1,          'USD'),
    'mii dolari sua':          ('currency',   1_000,      'USD'),
    'dts':                     ('currency',   1,          'SDR'),
    'hectare':                 ('area',       1,          None),
    'ha':                      ('area',       1,          None),
    'mii ha':                  ('area',       1_000,      None),
    'km2':                     ('area',       1,          None),
    'km patrati':              ('area',       1,          None),
    'tone':                    ('weight',     1,          None),
    'mii tone':                ('weight',     1_000,      None),
    'milioane tone':           ('weight',     1_000_000,  None),
    'tone co2 echivalent':     ('weight',     1,          None),
    'mii tep':                 ('energy',     1_000,      None),
    'kwh':                     ('energy',     1,          None),
    'mii kwh':                 ('energy',     1_000,      None),
    'mwh':                     ('energy',     1_000,      None),
    'gwh':                     ('energy',     1_000_000,  None),
    'indice':                  ('index',      1,          None),
    'indici':                  ('index',      1,          None),
    'indici de pret':          ('index',      1,          None),
    'rata':                    ('rate',       1,          None),
    'promile':                 ('rate',       1,          None),
    'km':                      ('distance',   1,          None),
    'zile':                    ('time_unit',  1,          None),
    'ore':                     ('time_unit',  1,          None),
    'numar mediu':             ('count',      1,          None),
    'locuri':                  ('count',      1,          None),
    'locuri de munca':         ('count',      1,          None),
    'unitati':                 ('count',      1,          None),
    'mii unitati':             ('count',      1_000,      None),
}


# ── Parsers ───────────────────────────────────────────────────────────────────

def parse_time(label: str) -> dict:
    sn = norm(label)

    # "Anul YYYY"
    m = re.match(r'anul\s+(\d{4})', sn)
    if m:
        return {'dim_type': 'time', 'year': int(m.group(1)), 'time_granularity': 'annual', 'parse_confidence': 1.0}

    # "Trimestrul I/II/III/IV YYYY" (Roman or Arabic)
    m = re.match(r'trimestrul\s+(i{1,3}v?|iv|[1-4])\s+(\d{4})', sn)
    if m:
        q_raw = m.group(1)
        q = ROMAN.get(q_raw) or (int(q_raw) if q_raw.isdigit() else None)
        if q:
            return {'dim_type': 'time', 'year': int(m.group(2)), 'quarter': q,
                    'time_granularity': 'quarterly', 'parse_confidence': 1.0}

    # "Semestrul I/II YYYY"
    m = re.match(r'semestrul\s+(i{1,2}|[12])\s+(\d{4})', sn)
    if m:
        sem_raw = m.group(1)
        sem = ROMAN.get(sem_raw) or (int(sem_raw) if sem_raw.isdigit() else None)
        if sem:
            return {'dim_type': 'time', 'year': int(m.group(2)), 'semester': sem,
                    'time_granularity': 'semester', 'parse_confidence': 1.0}

    # "Luna [name|num] YYYY"
    m = re.match(r'luna\s+(\w+)\s+(\d{4})', sn)
    if m:
        month_str = m.group(1)
        month = RO_MONTHS.get(month_str) or (int(month_str) if month_str.isdigit() else None)
        if month:
            return {'dim_type': 'time', 'year': int(m.group(2)), 'month': month,
                    'time_granularity': 'monthly', 'parse_confidence': 1.0}

    # Plain 4-digit year
    m = re.match(r'^(\d{4})$', sn.strip())
    if m:
        return {'dim_type': 'time', 'year': int(m.group(1)), 'time_granularity': 'annual', 'parse_confidence': 1.0}

    # Contains a year but in unknown format (ranges, "Anni ...", etc.) — extract first year
    m = re.search(r'(\d{4})', sn)
    if m:
        return {'dim_type': 'time', 'year': int(m.group(1)), 'time_granularity': 'other', 'parse_confidence': 0.5}

    return {'dim_type': 'time', 'parse_confidence': 0.1}


def parse_geo(label: str) -> dict:
    s = label.strip()
    sn = norm(s)

    # National total
    if sn in ('total', 'romania', 'total romania', 'total general',
              'nivel national', 'national', 'nivel national (agregat)'):
        return {'dim_type': 'geo', 'geo_level': 'national', 'geo_name_clean': 'Total', 'parse_confidence': 1.0}

    # Macroregion
    if 'macroregiunea' in sn:
        return {'dim_type': 'geo', 'geo_level': 'macroregion', 'geo_name_clean': s, 'parse_confidence': 1.0}

    # Development region
    if sn.startswith('regiunea') or re.search(r'\bregiunea\s+\w', sn):
        return {'dim_type': 'geo', 'geo_level': 'region', 'geo_name_clean': s, 'parse_confidence': 1.0}

    # București special cases
    if re.search(r'(municipiul\s+)?bucuresti', sn):
        return {'dim_type': 'geo', 'geo_level': 'county', 'geo_name_clean': 'Municipiul București', 'parse_confidence': 1.0}

    # Municipiu / Oras (locality-level)
    if re.match(r'^(municipiul|municipiu|oras|orașul)\s+\w', sn):
        return {'dim_type': 'geo', 'geo_level': 'locality', 'geo_name_clean': s, 'parse_confidence': 0.9}

    # County name lookup (normalized)
    if sn in COUNTIES_NORM:
        return {'dim_type': 'geo', 'geo_level': 'county', 'geo_name_clean': s, 'parse_confidence': 1.0}

    # SIRUTA code: 4–6 leading digits + name
    m = re.match(r'^(\d{4,6})\s+(.+)', s)
    if m:
        return {'dim_type': 'geo', 'geo_level': 'locality',
                'siruta_code': int(m.group(1)), 'geo_name_clean': m.group(2).strip(),
                'parse_confidence': 1.0}

    # Urban / Rural
    if re.search(r'\burban\b', sn):
        return {'dim_type': 'geo', 'geo_level': 'residence', 'geo_name_clean': 'urban', 'parse_confidence': 1.0}
    if re.search(r'\brural\b', sn):
        return {'dim_type': 'geo', 'geo_level': 'residence', 'geo_name_clean': 'rural', 'parse_confidence': 1.0}

    return {'dim_type': 'geo', 'geo_level': 'unknown', 'geo_name_clean': s, 'parse_confidence': 0.2}


def parse_gender(label: str) -> dict:
    sn = norm(label)
    if any(x in sn for x in ('masculin', 'barbati', 'barbat', 'baieti', 'baiat', 'de sex masculin')):
        return {'dim_type': 'gender', 'gender': 'male', 'parse_confidence': 1.0}
    if any(x in sn for x in ('feminin', 'femei', 'femeie', 'fete', 'fata', 'de sex feminin')):
        return {'dim_type': 'gender', 'gender': 'female', 'parse_confidence': 1.0}
    if 'necunoscut' in sn:
        return {'dim_type': 'gender', 'gender': 'unknown', 'parse_confidence': 1.0}
    if sn.strip() in ('total', 'ambele sexe'):
        return {'dim_type': 'gender', 'gender': 'total', 'parse_confidence': 1.0}
    return {'dim_type': 'gender', 'gender': 'other', 'parse_confidence': 0.5}


def parse_age(label: str) -> dict:
    sn = norm(label)
    if sn.strip() in ('total', 'total varste', 'toate varstele'):
        return {'dim_type': 'age', 'age_min': 0, 'age_max': 999, 'parse_confidence': 1.0}

    # "X-Y ani"
    m = re.search(r'(\d+)\s*-\s*(\d+)\s*ani', sn)
    if m:
        return {'dim_type': 'age', 'age_min': int(m.group(1)), 'age_max': int(m.group(2)), 'parse_confidence': 1.0}

    # "X ani" (single age)
    m = re.match(r'^\s*(\d+)\s+ani?\s*$', sn)
    if m:
        age = int(m.group(1))
        return {'dim_type': 'age', 'age_min': age, 'age_max': age, 'parse_confidence': 1.0}

    # "sub X ani"
    m = re.search(r'sub\s+(\d+)\s+ani?', sn)
    if m:
        return {'dim_type': 'age', 'age_min': 0, 'age_max': int(m.group(1)) - 1, 'parse_confidence': 1.0}

    # "X ani si peste" / "X ani si mai mult"
    m = re.search(r'(\d+)\s+ani?\s*(si\s+)?(peste|mai\s+mult)', sn)
    if m:
        return {'dim_type': 'age', 'age_min': int(m.group(1)), 'age_max': 999, 'parse_confidence': 1.0}

    # "peste X ani"
    m = re.search(r'peste\s+(\d+)\s+ani?', sn)
    if m:
        return {'dim_type': 'age', 'age_min': int(m.group(1)) + 1, 'age_max': 999, 'parse_confidence': 1.0}

    return {'dim_type': 'age', 'age_min': None, 'age_max': None, 'parse_confidence': 0.3}


def parse_residence(label: str) -> dict:
    sn = norm(label)
    if 'urban' in sn:
        return {'dim_type': 'residence', 'geo_level': 'residence', 'geo_name_clean': 'urban', 'parse_confidence': 1.0}
    if 'rural' in sn:
        return {'dim_type': 'residence', 'geo_level': 'residence', 'geo_name_clean': 'rural', 'parse_confidence': 1.0}
    if sn.strip() == 'total':
        return {'dim_type': 'residence', 'geo_level': 'residence', 'geo_name_clean': 'total', 'parse_confidence': 1.0}
    return {'dim_type': 'residence', 'geo_level': 'residence', 'geo_name_clean': sn.strip(), 'parse_confidence': 0.7}


def parse_unit(label: str) -> dict:
    sn = norm(label)
    # Strip "um: " prefix if present
    sn_clean = re.sub(r'^um:\s*', '', sn).strip()

    for key in (sn_clean, sn):
        if key in UNIT_MAP:
            unit_type, scale, currency = UNIT_MAP[key]
            return {'dim_type': 'unit', 'unit_type': unit_type, 'unit_scale': scale,
                    'currency': currency, 'parse_confidence': 1.0}

    return {'dim_type': 'unit', 'unit_type': 'other', 'unit_scale': 1, 'currency': None, 'parse_confidence': 0.1}


# ── Dimension type detection (from dim_label) ─────────────────────────────────

def detect_dim_type(dim_label: str) -> str:
    sn = norm(dim_label)

    # Unit columns always start with "UM:"
    if sn.startswith('um:') or sn.startswith('um ') or sn == 'um':
        return 'unit'

    # Time indicators
    TIME_KEYWORDS = ('perioade', 'trimestre', 'trimestru', 'semestre', 'semestru',
                     'saptamani', 'luni calendaristice')
    if any(k in sn for k in TIME_KEYWORDS):
        return 'time'
    if sn in ('ani', 'perioade', 'luni', 'trimestre', 'semestre', 'perioade de referinta'):
        return 'time'
    # "ani" appearing alone or as suffix in multi-word label
    if re.search(r'\bani\b', sn) and 'grupe de varsta' not in sn and 'varst' not in sn:
        return 'time'

    # Gender — must check before geo (some dim labels mix both)
    if re.search(r'\bsexe\b', sn) and 'rezidenta' not in sn:
        return 'gender'
    if sn == 'sex':
        return 'gender'

    # Age
    if any(k in sn for k in ('varsta', 'varste', 'grupe de varsta', 'grupe varsta', 'clase de varsta')):
        return 'age'

    # Residence (urban/rural) — before geo
    if 'rezidenta' in sn or 'grad de urbanizare' in sn or 'medii de rezident' in sn:
        return 'residence'

    # Geography
    GEO_KEYWORDS = ('macroregiuni', 'regiuni', 'judete', 'judet', 'localitati', 'localitate',
                    'municipii', 'orase', 'comune', 'sate', 'teritorii', 'zone geografice',
                    'tari', 'tara', 'continente', 'filiale')
    if any(k in sn for k in GEO_KEYWORDS):
        return 'geo'

    return 'indicator'


# ── Apply appropriate parser ──────────────────────────────────────────────────

PARSERS = {
    'time':      parse_time,
    'geo':       parse_geo,
    'gender':    parse_gender,
    'age':       parse_age,
    'residence': parse_residence,
    'unit':      parse_unit,
}


def parse_option(dim_type: str, option_label: str) -> dict:
    label = (option_label or '').strip()
    if dim_type == 'indicator':
        return {'dim_type': 'indicator', 'parse_confidence': 1.0}
    parser = PARSERS.get(dim_type)
    if not parser:
        return {'dim_type': 'other', 'parse_confidence': 0.0}
    result = parser(label)
    if result is None:
        return {'dim_type': dim_type, 'parse_confidence': 0.0}
    return result


# ── Archetype assignment ──────────────────────────────────────────────────────

def assign_archetype(has_time, has_geo, has_gender, has_age, has_residence) -> str:
    if has_time and has_geo:
        return 'geo_time'
    if has_time and (has_gender or has_age):
        return 'demographic'
    if has_time and has_residence:
        return 'time_residence'
    if has_time:
        return 'time_series'
    if has_geo:
        return 'geo_only'
    return 'categorical'


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='Classify and parse INS dimension options')
    ap.add_argument('--matrix', help='Process only this matrix code (for testing)')
    ap.add_argument('--debug', action='store_true', help='Verbose per-option logging')
    args = ap.parse_args()

    conn = duckdb.connect(str(DB_FILE))

    print("=" * 70)
    print("INS Dimension Classification & Parsing")
    print("=" * 70)

    # ── Schema setup ─────────────────────────────────────────────────────────
    print("\n→ Creating tables...")
    conn.execute("DROP TABLE IF EXISTS dimension_options_parsed")
    conn.execute("DROP TABLE IF EXISTS matrix_profiles")

    conn.execute("""
        CREATE TABLE dimension_options_parsed (
            nom_item_id      INTEGER PRIMARY KEY,
            dim_type         TEXT,
            -- time fields
            year             INTEGER,
            quarter          INTEGER,
            month            INTEGER,
            semester         INTEGER,
            time_granularity TEXT,
            -- geo / residence fields
            geo_level        TEXT,
            siruta_code      INTEGER,
            geo_name_clean   TEXT,
            -- gender
            gender           TEXT,
            -- age
            age_min          INTEGER,
            age_max          INTEGER,
            -- unit
            unit_type        TEXT,
            unit_scale       INTEGER,
            currency         TEXT,
            -- meta
            parse_confidence REAL,
            raw_label        TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE matrix_profiles (
            matrix_code       TEXT PRIMARY KEY,
            has_time          BOOLEAN,
            time_granularity  TEXT,
            time_year_min     INTEGER,
            time_year_max     INTEGER,
            has_geo           BOOLEAN,
            geo_levels        TEXT,
            has_gender        BOOLEAN,
            has_age           BOOLEAN,
            has_residence     BOOLEAN,
            unit_types        TEXT,
            primary_unit_type TEXT,
            dim_count         INTEGER,
            archetype         TEXT,
            parse_coverage    REAL
        )
    """)

    # ── Fetch all options with dimension context ──────────────────────────────
    matrix_filter = f"AND d.matrix_code = '{args.matrix}'" if args.matrix else ""

    print("→ Fetching dimension options from DuckDB...")
    rows = conn.execute(f"""
        SELECT
            opt.nom_item_id,
            opt.option_label,
            d.dim_label,
            d.matrix_code,
            d.dim_code
        FROM dimension_options opt
        JOIN dimensions d ON opt.dimension_id = d.dimension_id
        WHERE 1=1 {matrix_filter}
        ORDER BY d.matrix_code, d.dim_code, opt.option_offset
    """).fetchall()

    print(f"  Loaded {len(rows):,} option rows")
    if not rows:
        print("  No rows found — check DB path or --matrix filter.")
        sys.exit(1)

    # ── Parse every unique nom_item_id ────────────────────────────────────────
    # A nom_item_id is globally unique; use first-seen dim_label to determine type.
    seen: dict[int, dict] = {}          # nom_item_id → parsed dict

    # Per-matrix tracking for profiling
    # matrix_code → dim_code → {dim_type, years, granularities, geo_levels, unit_types}
    matrix_dims: dict[str, dict[int, dict]] = defaultdict(dict)

    # Per-matrix: all nom_item_ids (for coverage calculation)
    matrix_nids: dict[str, list[int]] = defaultdict(list)

    # Unknowns for reporting
    unknown_units: dict[str, int] = defaultdict(int)
    unknown_geo:   dict[str, int]  = defaultdict(int)

    for nom_item_id, option_label, dim_label, matrix_code, dim_code in rows:
        dim_type = detect_dim_type(dim_label)

        # Track per-matrix dimension info
        if dim_code not in matrix_dims[matrix_code]:
            matrix_dims[matrix_code][dim_code] = {
                'dim_type': dim_type,
                'dim_label': dim_label,
                'years': [],
                'granularities': set(),
                'geo_levels': set(),
                'unit_types': set(),
            }

        matrix_nids[matrix_code].append(nom_item_id)

        # Parse only once per unique ID
        if nom_item_id not in seen:
            parsed = parse_option(dim_type, option_label or '')
            parsed.setdefault('nom_item_id', nom_item_id)
            parsed['raw_label'] = option_label
            seen[nom_item_id] = parsed

            if args.debug:
                print(f"  [{dim_type:10}] {repr((option_label or '').strip()):<40} → "
                      f"conf={parsed.get('parse_confidence', 0):.1f} "
                      f"{_debug_summary(parsed)}")

            # Collect unknowns
            if dim_type == 'unit' and parsed.get('unit_type') == 'other':
                unknown_units[norm(option_label or '')] += 1
            if dim_type == 'geo' and parsed.get('geo_level') == 'unknown':
                unknown_geo[norm(option_label or '')] += 1

        # Accumulate matrix-level stats from parsed result
        parsed = seen[nom_item_id]
        dim_info = matrix_dims[matrix_code][dim_code]

        if dim_type == 'time':
            if parsed.get('year'):
                dim_info['years'].append(parsed['year'])
            if parsed.get('time_granularity'):
                dim_info['granularities'].add(parsed['time_granularity'])

        elif dim_type in ('geo', 'residence'):
            if parsed.get('geo_level'):
                dim_info['geo_levels'].add(parsed['geo_level'])

        elif dim_type == 'unit':
            if parsed.get('unit_type'):
                dim_info['unit_types'].add(parsed['unit_type'])

    # ── Bulk-insert parsed options ────────────────────────────────────────────
    print(f"\n→ Inserting {len(seen):,} parsed options...")

    insert_rows = []
    for p in seen.values():
        insert_rows.append((
            p.get('nom_item_id'),
            p.get('dim_type'),
            p.get('year'),
            p.get('quarter'),
            p.get('month'),
            p.get('semester'),
            p.get('time_granularity'),
            p.get('geo_level'),
            p.get('siruta_code'),
            p.get('geo_name_clean'),
            p.get('gender'),
            p.get('age_min'),
            p.get('age_max'),
            p.get('unit_type'),
            p.get('unit_scale'),
            p.get('currency'),
            p.get('parse_confidence', 0.5),
            p.get('raw_label'),
        ))

    conn.executemany(
        "INSERT INTO dimension_options_parsed VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        insert_rows
    )

    # ── Build matrix profiles ─────────────────────────────────────────────────
    print(f"→ Building profiles for {len(matrix_dims):,} matrices...")

    profile_rows = []
    archetype_counts: dict[str, int] = defaultdict(int)

    for matrix_code, dims in matrix_dims.items():
        has_time      = any(d['dim_type'] == 'time'      for d in dims.values())
        has_geo       = any(d['dim_type'] in ('geo',)    for d in dims.values())
        has_gender    = any(d['dim_type'] == 'gender'    for d in dims.values())
        has_age       = any(d['dim_type'] == 'age'       for d in dims.values())
        has_residence = any(d['dim_type'] == 'residence' for d in dims.values())

        # Time aggregation
        all_years: list[int] = []
        all_granularities: set[str] = set()
        for d in dims.values():
            if d['dim_type'] == 'time':
                all_years.extend(d['years'])
                all_granularities.update(d['granularities'])

        time_year_min = min(all_years) if all_years else None
        time_year_max = max(all_years) if all_years else None

        if len(all_granularities) > 1:
            time_granularity = 'mixed'
        elif all_granularities:
            time_granularity = next(iter(all_granularities))
        else:
            time_granularity = None

        # Geo aggregation
        all_geo_levels: set[str] = set()
        for d in dims.values():
            if d['dim_type'] in ('geo', 'residence'):
                all_geo_levels.update(d['geo_levels'])

        # Unit aggregation
        all_unit_types: set[str] = set()
        for d in dims.values():
            if d['dim_type'] == 'unit':
                all_unit_types.update(d['unit_types'])
        primary_unit = next(iter(all_unit_types - {'other'}), None) or next(iter(all_unit_types), None)

        # Parse coverage: fraction of this matrix's options with confidence ≥ 0.8
        nids = matrix_nids[matrix_code]
        high_conf = sum(1 for nid in nids if seen.get(nid, {}).get('parse_confidence', 0) >= 0.8)
        parse_coverage = high_conf / len(nids) if nids else 0.0

        archetype = assign_archetype(has_time, has_geo, has_gender, has_age, has_residence)
        archetype_counts[archetype] += 1

        profile_rows.append((
            matrix_code,
            has_time,
            time_granularity,
            time_year_min,
            time_year_max,
            has_geo,
            json.dumps(sorted(all_geo_levels)),
            has_gender,
            has_age,
            has_residence,
            json.dumps(sorted(all_unit_types)),
            primary_unit,
            len(dims),
            archetype,
            round(parse_coverage, 3),
        ))

    conn.executemany(
        "INSERT INTO matrix_profiles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        profile_rows
    )

    conn.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"\nUnique option IDs parsed : {len(seen):,}")
    print(f"Matrix profiles created  : {len(profile_rows):,}")

    print("\nArchetype distribution:")
    for archetype, count in sorted(archetype_counts.items(), key=lambda x: -x[1]):
        bar = '█' * (count * 30 // max(archetype_counts.values()))
        print(f"  {archetype:<20} {count:>5}  {bar}")

    if unknown_units:
        print(f"\nUnknown unit labels ({len(unknown_units)} unique) — add to UNIT_MAP:")
        for label, count in sorted(unknown_units.items(), key=lambda x: -x[1])[:25]:
            print(f"  {count:>4}x  {repr(label)}")

    if unknown_geo:
        print(f"\nUnknown geo labels ({len(unknown_geo)} unique, top 20):")
        for label, count in sorted(unknown_geo.items(), key=lambda x: -x[1])[:20]:
            print(f"  {count:>4}x  {repr(label)}")

    print("\n✓ Done. Verify with DuckDB queries:")
    print("  SELECT dim_type, COUNT(*) FROM dimension_options_parsed GROUP BY dim_type;")
    print("  SELECT archetype, COUNT(*) FROM matrix_profiles GROUP BY archetype ORDER BY 2 DESC;")
    print("  SELECT raw_label, year, quarter, month FROM dimension_options_parsed")
    print("    WHERE dim_type='time' LIMIT 20;")


def _debug_summary(p: dict) -> str:
    """Compact one-line summary of parsed fields for debug output."""
    parts = []
    if p.get('year'):        parts.append(f"year={p['year']}")
    if p.get('quarter'):     parts.append(f"q={p['quarter']}")
    if p.get('month'):       parts.append(f"m={p['month']}")
    if p.get('geo_level'):   parts.append(f"geo={p['geo_level']}")
    if p.get('gender'):      parts.append(f"gender={p['gender']}")
    if p.get('age_min') is not None: parts.append(f"age={p['age_min']}-{p['age_max']}")
    if p.get('unit_type'):   parts.append(f"unit={p['unit_type']}×{p.get('unit_scale',1)}")
    return ' '.join(parts) if parts else '(indicator)'


if __name__ == '__main__':
    main()
