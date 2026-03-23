"""
Split rules engine — detects and classifies datasets needing structural splits.

Patterns:
  A) multi_um      — Multiple units of measure in UM dimension
  B) mixed_metrics — First dimension contains fundamentally different variables
  C) slash_dims    — One dimension packs multiple semantic types (sex/age/region)
  D) hierarchy     — Parent-child geo columns (Judete + Localitati)
  E) age_granularity — Age dimension mixes single-year and grouped ages
  F) geo_hierarchy — Single dimension packs macroregions + dev regions + counties
  G) mixed_time_granularity — Perioade mixes annual and monthly options

Uses hybrid classification:
  1. dimension_options_parsed.dim_type (primary)
  2. Regex fallback for Romanian labels
  3. Manual overrides from split_overrides.json
"""

import json
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

OVERRIDES_FILE = Path(__file__).parent / "split_overrides.json"

# --- Regex classifiers for Romanian dimension labels ---

# Ordered list — checked sequentially, first match wins.
# More specific patterns go first; ambiguous labels like "Total" are handled separately.
SEMANTIC_PATTERNS = [
    ("varsta", [
        re.compile(r'\d+[-–]\d+\s*ani', re.IGNORECASE),
        re.compile(r'^\d+\s*ani\s*si\s*peste', re.IGNORECASE),
        re.compile(r'^Sub\s*\d+\s*ani', re.IGNORECASE),
        re.compile(r'grupe?\s*de\s*v[aâ]rst[aă]', re.IGNORECASE),
    ]),
    ("educatie", [
        re.compile(r'nivel\s*de\s*educatie', re.IGNORECASE),
        re.compile(r'educatie\s*(scazut|mediu|superior)', re.IGNORECASE),
        re.compile(r'(primar|gimnazial|liceal|universitar|postuniversitar)', re.IGNORECASE),
        re.compile(r'ISCED', re.IGNORECASE),
    ]),
    ("geo_regiune", [
        re.compile(r'^MACROREGIUNEA', re.IGNORECASE),
        re.compile(r'^Regiunea\s', re.IGNORECASE),
        re.compile(r'NORD.?(EST|VEST)', re.IGNORECASE),
        re.compile(r'SUD.?(EST|VEST|MUNTENIA)', re.IGNORECASE),
        re.compile(r'BUCURESTI\s*-\s*ILFOV', re.IGNORECASE),
        re.compile(r'^CENTRU$', re.IGNORECASE),
        re.compile(r'^VEST$', re.IGNORECASE),
    ]),
    ("geo_judet", [
        re.compile(r'^\d{2,5}\s+', re.IGNORECASE),  # SIRUTA code prefix
    ]),
    ("mediu_rezidenta", [
        re.compile(r'^(Urban|Rural)$', re.IGNORECASE),
        re.compile(r'^Mediul\s*(urban|rural)$', re.IGNORECASE),
    ]),
    ("sex", [
        re.compile(r'^(Masculin|Feminin)$', re.IGNORECASE),
        re.compile(r'^Barbati$', re.IGNORECASE),
        re.compile(r'^Femei$', re.IGNORECASE),
        # NOTE: "Total" is deliberately excluded — it's ambiguous across categories
    ]),
]


@dataclass
class SplitGroup:
    """A group of dimension option IDs that belong together."""
    label: str           # Human-readable suffix (e.g., "sex", "varsta")
    option_ids: list      # List of nom_item_ids
    option_labels: dict   # {nom_item_id: label} for display


@dataclass
class SplitRule:
    """Describes how to split one dataset."""
    matrix_code: str
    pattern: str                    # multi_um, mixed_metrics, slash_dims, hierarchy
    split_dimension: str            # dim_column_name to split on
    split_dimension_id: int         # dimension_id in DB
    groups: list                    # list of SplitGroup
    drop_columns: list = field(default_factory=list)  # columns to remove after split


def load_overrides() -> dict:
    """Load manual override rules from JSON file."""
    if OVERRIDES_FILE.exists():
        with open(OVERRIDES_FILE) as f:
            return json.load(f)
    return {}


def classify_option_label(label: str) -> str | None:
    """Classify a single option label by regex. Returns semantic type or None.
    'Total' is ambiguous and returns None (will be assigned to largest group later)."""
    if label.strip().lower() == "total":
        return None  # Ambiguous — let caller assign to dominant group
    for sem_type, patterns in SEMANTIC_PATTERNS:
        for pat in patterns:
            if pat.search(label):
                return sem_type
    return None


def detect_multi_um(conn) -> list[SplitRule]:
    """Pattern A: Find datasets with multiple UM values."""
    rows = conn.execute("""
        SELECT d.matrix_code, d.dimension_id, d.dim_column_name, d.dim_label,
               dopt.nom_item_id, dopt.option_label
        FROM dimensions d
        JOIN dimension_options dopt ON d.dimension_id = dopt.dimension_id
        WHERE (LOWER(d.dim_label) LIKE 'um:%' OR LOWER(d.dim_label) LIKE 'unitati de masura%')
        ORDER BY d.matrix_code, dopt.option_label
    """).fetchall()

    # Group by matrix
    from collections import defaultdict
    by_matrix = defaultdict(list)
    for r in rows:
        by_matrix[r[0]].append(r)

    rules = []
    for mc, opts in by_matrix.items():
        if len(opts) <= 1:
            continue

        dim_id = opts[0][1]
        dim_col = opts[0][2]
        groups = []
        for o in opts:
            suffix = _label_to_suffix(o[5])
            groups.append(SplitGroup(
                label=suffix,
                option_ids=[o[4]],
                option_labels={o[4]: o[5]},
            ))

        rules.append(SplitRule(
            matrix_code=mc,
            pattern="multi_um",
            split_dimension=dim_col,
            split_dimension_id=dim_id,
            groups=groups,
            drop_columns=[dim_col],  # UM col becomes single-valued, drop it
        ))

    logger.info(f"Pattern A (multi_um): {len(rules)} datasets")
    return rules


def detect_mixed_metrics(conn) -> list[SplitRule]:
    """Pattern B: First dimension contains fundamentally different measured variables
    that pair with different units of measure.

    Key indicator: the first dimension's option labels contain words like
    'numar', 'salariu', 'venit', 'rata', 'procent' — signaling distinct metric types.
    Simply having multiple product categories (wheat, corn, ...) doesn't qualify.
    """
    # Heuristic: find datasets where first dim has few options (<=10) and multi-UM,
    # AND the first dim label suggests mixed variable types
    METRIC_KEYWORDS = re.compile(
        r'(numar|salariu|venit|rata|procent|pondere|indice|cheltuiel|cost|pret|'
        r'productie|consum|export|import|stoc|sold|cifra|valoare|durata|suprafata)',
        re.IGNORECASE
    )

    rows = conn.execute("""
        WITH um_dims AS (
            SELECT matrix_code, dimension_id as um_dim_id, dim_column_name as um_col
            FROM dimensions
            WHERE (LOWER(dim_label) LIKE 'um:%' OR LOWER(dim_label) LIKE 'unitati de masura%')
        ),
        multi_um AS (
            SELECT ud.matrix_code, ud.um_dim_id, ud.um_col
            FROM um_dims ud
            JOIN dimension_options dopt ON ud.um_dim_id = dopt.dimension_id
            GROUP BY ud.matrix_code, ud.um_dim_id, ud.um_col
            HAVING COUNT(DISTINCT dopt.option_label) > 1
        ),
        first_dim AS (
            SELECT d.matrix_code, d.dimension_id, d.dim_column_name, d.dim_label,
                   d.dim_code, d.option_count
            FROM dimensions d
            WHERE d.dim_code = 1
              AND LOWER(d.dim_label) NOT LIKE 'um:%' AND LOWER(d.dim_label) NOT LIKE 'unitati de masura%'
              AND LOWER(d.dim_label) NOT LIKE '%perioade%'
              AND d.option_count <= 10
        )
        SELECT fd.matrix_code, fd.dimension_id, fd.dim_column_name, fd.dim_label,
               dopt.nom_item_id, dopt.option_label
        FROM first_dim fd
        JOIN multi_um mu ON fd.matrix_code = mu.matrix_code
        JOIN dimension_options dopt ON fd.dimension_id = dopt.dimension_id
        ORDER BY fd.matrix_code, dopt.option_label
    """).fetchall()

    from collections import defaultdict
    by_matrix = defaultdict(list)
    for r in rows:
        by_matrix[r[0]].append(r)

    # Also get UM column names for drop_columns
    um_cols = {}
    for r in conn.execute("""
        SELECT matrix_code, dim_column_name FROM dimensions
        WHERE (LOWER(dim_label) LIKE 'um:%' OR LOWER(dim_label) LIKE 'unitati de masura%')
    """).fetchall():
        um_cols[r[0]] = r[1]

    rules = []
    for mc, opts in by_matrix.items():
        if len(opts) <= 1:
            continue

        # Check if option labels suggest mixed metric types
        labels = [o[5] for o in opts]
        metric_matches = sum(1 for l in labels if METRIC_KEYWORDS.search(l))
        if metric_matches < 2:
            # Not enough metric-type labels — skip (likely just product categories)
            continue

        dim_id = opts[0][1]
        dim_col = opts[0][2]
        groups = []
        for o in opts:
            suffix = _label_to_suffix(o[5])
            groups.append(SplitGroup(
                label=suffix,
                option_ids=[o[4]],
                option_labels={o[4]: o[5]},
            ))

        drop = [dim_col]
        if mc in um_cols:
            drop.append(um_cols[mc])

        rules.append(SplitRule(
            matrix_code=mc,
            pattern="mixed_metrics",
            split_dimension=dim_col,
            split_dimension_id=dim_id,
            groups=groups,
            drop_columns=drop,
        ))

    logger.info(f"Pattern B (mixed_metrics): {len(rules)} datasets")
    return rules


def detect_slash_dims(conn) -> list[SplitRule]:
    """Pattern C: Dimensions with slash-notation combining multiple semantic types."""
    # Find dimensions with / in name that have >5 options (to exclude simple cases like "Da/Nu")
    rows = conn.execute("""
        SELECT d.matrix_code, d.dimension_id, d.dim_column_name, d.dim_label,
               dopt.nom_item_id, dopt.option_label
        FROM dimensions d
        JOIN dimension_options dopt ON d.dimension_id = dopt.dimension_id
        WHERE d.dim_label LIKE '%/%'
          AND d.option_count > 5
          AND LOWER(d.dim_label) NOT LIKE 'um:%' AND LOWER(d.dim_label) NOT LIKE 'unitati de masura%'
        ORDER BY d.matrix_code, d.dim_label, dopt.option_label
    """).fetchall()

    # Load parsed classifications
    parsed = {}
    try:
        for r in conn.execute("""
            SELECT nom_item_id, dim_type FROM dimension_options_parsed
            WHERE dim_type IS NOT NULL
        """).fetchall():
            parsed[r[0]] = r[1]
    except Exception:
        logger.warning("dimension_options_parsed not available, using regex only")

    overrides = load_overrides()
    from collections import defaultdict
    by_matrix_dim = defaultdict(list)
    for r in rows:
        by_matrix_dim[(r[0], r[1], r[2], r[3])].append((r[4], r[5]))

    rules = []
    for (mc, dim_id, dim_col, dim_name), opts in by_matrix_dim.items():
        # Classify each option
        classified = defaultdict(list)  # sem_type -> [(id, label)]

        # Check overrides first
        override_key = f"{mc}/{dim_name}"
        manual = overrides.get(override_key, {})

        for oid, olabel in opts:
            # 1. Manual override
            if str(oid) in manual:
                sem = manual[str(oid)]
            # 2. Regex first for slash dims (parsed table is unreliable for mixed dims —
            #    it often assigns the same type to all options in a mixed dimension)
            else:
                sem = classify_option_label(olabel)
            # 3. Fall back to parsed table only if regex found nothing
            if sem is None and oid in parsed:
                sem = _map_parsed_type(parsed[oid])

            if sem is None:
                sem = "other"

            classified[sem].append((oid, olabel))

        # Only split if we found >1 non-other semantic group
        real_groups = {k: v for k, v in classified.items() if k != "other"}
        if len(real_groups) <= 1:
            continue

        # "other" items (like "Total") get duplicated into every group
        # so each sub-dataset has its own "Total" row
        if "other" in classified:
            other_items = classified.pop("other")
            for sem_type in real_groups:
                classified[sem_type].extend(other_items)

        groups = []
        for sem_type, items in classified.items():
            if not items:
                continue
            groups.append(SplitGroup(
                label=sem_type,
                option_ids=[i[0] for i in items],
                option_labels={i[0]: i[1] for i in items},
            ))

        if len(groups) > 1:
            rules.append(SplitRule(
                matrix_code=mc,
                pattern="slash_dims",
                split_dimension=dim_col,
                split_dimension_id=dim_id,
                groups=groups,
            ))

    logger.info(f"Pattern C (slash_dims): {len(rules)} datasets")
    return rules


def detect_hierarchy(conn) -> list[SplitRule]:
    """Pattern D: Datasets with both Judete and Localitati dimensions."""
    rows = conn.execute("""
        SELECT d1.matrix_code,
               d1.dimension_id as county_dim_id, d1.dim_column_name as county_col,
               d2.dimension_id as locality_dim_id, d2.dim_column_name as locality_col
        FROM dimensions d1
        JOIN dimensions d2 ON d1.matrix_code = d2.matrix_code
        WHERE (LOWER(d1.dim_label) LIKE '%judet%' OR LOWER(d1.dim_label) LIKE '%judete%')
          AND (LOWER(d2.dim_label) LIKE '%localit%')
          AND d1.dimension_id != d2.dimension_id
    """).fetchall()

    rules = []
    seen = set()
    for r in rows:
        mc = r[0]
        if mc in seen:
            continue
        seen.add(mc)

        rules.append(SplitRule(
            matrix_code=mc,
            pattern="hierarchy",
            split_dimension=r[4],       # locality column is what we split on
            split_dimension_id=r[3],    # locality dimension_id
            groups=[
                SplitGroup(label="judet", option_ids=[], option_labels={}),
                SplitGroup(label="localitate", option_ids=[], option_labels={}),
            ],
            drop_columns=[],  # Keep both columns; filtering is row-level
        ))

    logger.info(f"Pattern D (hierarchy): {len(rules)} datasets")
    return rules


def detect_age_granularity(conn) -> list[SplitRule]:
    """Pattern E: Age dimension with both single-year and grouped options.

    Creates two sub-datasets per affected parent:
      <code>_grupe  — 5-year age groups only (e.g. "0-4 ani", "5-9 ani")
      <code>_varste — single-year ages only   (e.g. "0 ani", "1 ani")
    "Total" is duplicated into both groups.

    Excludes already-split hierarchy variants (_judet, _localitate) to avoid
    3-level nesting complexity.
    """
    rows = conn.execute("""
        WITH age_dims AS (
            SELECT d.matrix_code, d.dimension_id, d.dim_column_name
            FROM dimensions d
            WHERE (LOWER(d.dim_label) LIKE '%varst%' OR LOWER(d.dim_label) LIKE '%grupe%')
              AND d.matrix_code NOT LIKE '%_judet'
              AND d.matrix_code NOT LIKE '%_localitate'
              AND d.matrix_code NOT LIKE '%_grupe'
              AND d.matrix_code NOT LIKE '%_varste'
        ),
        age_options AS (
            SELECT ad.matrix_code, ad.dimension_id, ad.dim_column_name,
                   dopt.nom_item_id, dopt.option_label,
                   dop.age_min, dop.age_max
            FROM age_dims ad
            JOIN dimension_options dopt ON dopt.dimension_id = ad.dimension_id
            JOIN dimension_options_parsed dop ON dop.nom_item_id = dopt.nom_item_id
            WHERE dop.dim_type = 'age' AND dop.age_min IS NOT NULL
        ),
        mixed AS (
            SELECT matrix_code, dimension_id, dim_column_name,
                   COUNT(CASE WHEN age_min = age_max AND age_min > 0 THEN 1 END) AS singles,
                   COUNT(CASE WHEN age_min != age_max AND NOT (age_min = 0 AND age_max = 999) THEN 1 END) AS groups
            FROM age_options
            GROUP BY matrix_code, dimension_id, dim_column_name
        )
        SELECT ao.matrix_code, ao.dimension_id, ao.dim_column_name,
               ao.nom_item_id, ao.option_label, ao.age_min, ao.age_max
        FROM age_options ao
        JOIN mixed m ON m.matrix_code = ao.matrix_code AND m.dimension_id = ao.dimension_id
        WHERE m.singles > 0 AND m.groups > 0
        ORDER BY ao.matrix_code, ao.age_min, ao.age_max
    """).fetchall()

    from collections import defaultdict
    by_matrix = defaultdict(list)
    for r in rows:
        by_matrix[(r[0], r[1], r[2])].append(r)

    rules = []
    for (mc, dim_id, dim_col), opts in by_matrix.items():
        grupe_ids, grupe_labels = [], {}
        varste_ids, varste_labels = [], {}
        total_ids, total_labels = [], {}

        for r in opts:
            oid, olabel, age_min, age_max = r[3], r[4], r[5], r[6]
            if age_min == 0 and age_max == 999:
                total_ids.append(oid)
                total_labels[oid] = olabel
            elif age_min == age_max:
                varste_ids.append(oid)
                varste_labels[oid] = olabel
            else:
                grupe_ids.append(oid)
                grupe_labels[oid] = olabel

        # Duplicate totals into both groups
        for oid, olabel in total_labels.items():
            grupe_ids.append(oid)
            grupe_labels[oid] = olabel
            varste_ids.append(oid)
            varste_labels[oid] = olabel

        if not grupe_ids or not varste_ids:
            continue

        groups = [
            SplitGroup(label="grupe", option_ids=grupe_ids, option_labels=grupe_labels),
            SplitGroup(label="varste", option_ids=varste_ids, option_labels=varste_labels),
        ]
        rules.append(SplitRule(
            matrix_code=mc,
            pattern="age_granularity",
            split_dimension=dim_col,
            split_dimension_id=dim_id,
            groups=groups,
        ))

    logger.info(f"Pattern E (age_granularity): {len(rules)} datasets")
    return rules


def detect_geo_hierarchy(conn) -> list[SplitRule]:
    """Pattern F: Single dimension packs macroregions + dev regions + counties.

    Targets dimensions whose label contains 'macroregiuni' AND ('judete' OR 'regiuni'),
    e.g. "Macroregiuni, regiuni de dezvoltare si judete" (405 datasets)
    or   "Macroregiuni si regiuni de dezvoltare" (60 datasets, no county level).

    Creates up to 3 sub-datasets per parent:
      <code>_judete       — county-level rows only   (geo_level='county')
      <code>_regiuni      — dev-region rows only     (geo_level='region')
      <code>_macroregiuni — macroregion rows only    (geo_level='macroregion')

    Uses dimension_options_parsed.geo_level for classification.
    Excludes datasets that are already split sub-datasets.
    """
    # Find candidate dimensions
    dim_rows = conn.execute("""
        SELECT d.matrix_code, d.dimension_id, d.dim_column_name, d.dim_label
        FROM dimensions d
        JOIN matrices m ON m.matrix_code = d.matrix_code
        WHERE LOWER(d.dim_label) LIKE '%macroregiuni%'
          AND (LOWER(d.dim_label) LIKE '%judete%' OR LOWER(d.dim_label) LIKE '%regiuni%')
          AND (m.is_split IS NULL OR m.is_split = FALSE)
        ORDER BY d.matrix_code
    """).fetchall()

    if not dim_rows:
        logger.info("Pattern F (geo_hierarchy): 0 datasets")
        return []

    # Load geo_level classifications from dimension_options_parsed
    # geo_level values: 'county', 'region', 'macroregion', 'national'
    try:
        geo_parsed = {}
        for r in conn.execute("""
            SELECT nom_item_id, geo_level
            FROM dimension_options_parsed
            WHERE geo_level IS NOT NULL
        """).fetchall():
            geo_parsed[r[0]] = r[1]
    except Exception:
        logger.warning("dimension_options_parsed.geo_level not available — skipping Pattern F")
        return []

    rules = []
    seen = set()

    for mc, dim_id, dim_col, dim_label in dim_rows:
        if mc in seen:
            continue
        seen.add(mc)

        # Get all option IDs for this dimension
        opts = conn.execute(f"""
            SELECT nom_item_id, option_label
            FROM dimension_options
            WHERE dimension_id = {dim_id}
        """).fetchall()

        # Classify each option by geo_level
        by_level = {"county": {}, "region": {}, "macroregion": {}}
        for nom_id, label in opts:
            level = geo_parsed.get(nom_id)
            if level in by_level:
                by_level[level][nom_id] = label

        # Build groups — only emit levels that have options
        groups = []
        level_map = [
            ("judete",       "county"),
            ("regiuni",      "region"),
            ("macroregiuni", "macroregion"),
        ]
        for suffix, level in level_map:
            ids = by_level[level]
            if ids:
                groups.append(SplitGroup(
                    label=suffix,
                    option_ids=list(ids.keys()),
                    option_labels=ids,
                ))

        if len(groups) < 2:
            logger.debug(f"  {mc}: skipped (< 2 classifiable geo levels)")
            continue

        rules.append(SplitRule(
            matrix_code=mc,
            pattern="geo_hierarchy",
            split_dimension=dim_col,
            split_dimension_id=dim_id,
            groups=groups,
        ))

    logger.info(f"Pattern F (geo_hierarchy): {len(rules)} datasets")
    return rules


def detect_mixed_time_granularity(conn) -> list[SplitRule]:
    """Pattern G: Perioade dimension has both annual and monthly options.

    Creates two sub-datasets per affected parent:
      <code>_anual — annual rows only  (time_granularity='annual')
      <code>_lunar — monthly rows only (time_granularity='monthly')

    Uses dimension_options_parsed.time_granularity for classification.
    Excludes datasets that are already split sub-datasets.
    """
    try:
        rows = conn.execute("""
            SELECT d.matrix_code, d.dimension_id, d.dim_column_name,
                   o.nom_item_id, o.option_label, p.time_granularity
            FROM dimensions d
            JOIN matrices m ON m.matrix_code = d.matrix_code
            JOIN dimension_options o ON o.dimension_id = d.dimension_id
            LEFT JOIN dimension_options_parsed p ON p.nom_item_id = o.nom_item_id
            WHERE LOWER(d.dim_label) LIKE '%perioade%'
              AND (m.is_split IS NULL OR m.is_split = FALSE)
              AND p.time_granularity IN ('annual', 'monthly')
            ORDER BY d.matrix_code, p.time_granularity, o.option_label
        """).fetchall()
    except Exception as e:
        logger.warning(f"Pattern G: query failed ({e}) — skipping")
        return []

    from collections import defaultdict
    by_matrix = defaultdict(lambda: {"dim_id": None, "dim_col": None, "annual": {}, "monthly": {}})
    for mc, dim_id, dim_col, nom_id, label, granularity in rows:
        entry = by_matrix[mc]
        entry["dim_id"] = dim_id
        entry["dim_col"] = dim_col
        entry[granularity][nom_id] = label

    rules = []
    for mc, data in by_matrix.items():
        if not data["annual"] or not data["monthly"]:
            continue
        groups = [
            SplitGroup(label="anual", option_ids=list(data["annual"].keys()), option_labels=data["annual"]),
            SplitGroup(label="lunar", option_ids=list(data["monthly"].keys()), option_labels=data["monthly"]),
        ]
        rules.append(SplitRule(
            matrix_code=mc,
            pattern="mixed_time_granularity",
            split_dimension=data["dim_col"],
            split_dimension_id=data["dim_id"],
            groups=groups,
        ))

    logger.info(f"Pattern G (mixed_time_granularity): {len(rules)} datasets")
    return rules


def detect_all(conn) -> list[SplitRule]:
    """Run all detectors. Deduplicates: if a dataset matches multi_um AND mixed_metrics,
    prefer mixed_metrics (more specific). Multiple rules per matrix_code are allowed
    when they target different dimensions (e.g. geo + time + um) — the executor will
    produce cross-product sub-datasets in that case."""
    multi_um = detect_multi_um(conn)
    mixed_metrics = detect_mixed_metrics(conn)
    slash_dims = detect_slash_dims(conn)
    hierarchy = detect_hierarchy(conn)
    age_gran = detect_age_granularity(conn)
    geo_hier = detect_geo_hierarchy(conn)
    mixed_time = detect_mixed_time_granularity(conn)

    # Deduplicate: mixed_metrics supersedes multi_um for the same dataset
    mixed_metric_codes = {r.matrix_code for r in mixed_metrics}
    multi_um = [r for r in multi_um if r.matrix_code not in mixed_metric_codes]

    all_rules = multi_um + mixed_metrics + slash_dims + hierarchy + age_gran + geo_hier + mixed_time
    total_datasets = len(set(r.matrix_code for r in all_rules))
    logger.info(f"Total split rules: {len(all_rules)} across {total_datasets} datasets")
    return all_rules


# --- Helpers ---

def _label_to_suffix(label: str, max_len: int = 30) -> str:
    """Convert a Romanian label to a clean ASCII suffix for filenames."""
    # Romanian diacritics mapping
    tr = str.maketrans('ăâîșțĂÂÎȘȚ', 'aaistAAIST')
    s = label.translate(tr).lower()
    # Keep only alphanumeric and spaces
    s = re.sub(r'[^a-z0-9\s]', '', s)
    # Collapse whitespace to underscore
    s = re.sub(r'\s+', '_', s).strip('_')
    # Truncate
    if len(s) > max_len:
        s = s[:max_len].rstrip('_')
    return s or "other"


def _map_parsed_type(dim_type: str) -> str:
    """Map dimension_options_parsed.dim_type to our semantic categories."""
    mapping = {
        "geo": "geo_regiune",
        "gender": "sex",
        "age": "varsta",
        "residence": "mediu_rezidenta",
        "time": "timp",
        "indicator": "indicator",
        "unit": "um",
    }
    return mapping.get(dim_type, dim_type)
