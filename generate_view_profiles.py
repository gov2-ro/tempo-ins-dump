#!/usr/bin/env python3
"""
Generate per-dataset view profiles for the INS TEMPO explorer UI.

Produces a JSON file per dataset in data/view-profiles/{CODE}.json
that drives the 4-view UI: Timeline, Snapshot, Table, Custom Charts.

Rules reference: docs/view-profile-rules.md

Usage:
    python generate_view_profiles.py                    # all datasets
    python generate_view_profiles.py --matrix TUR105G   # single dataset
    python generate_view_profiles.py --debug            # verbose output
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = Path("data/tempo_metadata.duckdb")
OUTPUT_DIR = Path("data/view-profiles")
PROFILE_VERSION = 1

# Cardinality bands
CARD_LOW = (2, 5)
CARD_MEDIUM = (6, 25)
CARD_HIGH = (26, 100)
# >100 = very_high

# CAEN detection patterns (case-insensitive)
CAEN_PATTERNS = [
    re.compile(r'caen', re.IGNORECASE),
    re.compile(r'activit\w+\s+(ale\s+)?economiei', re.IGNORECASE),
    re.compile(r'sectoare\s+de\s+activitate', re.IGNORECASE),
]

# Total detection patterns
TOTAL_PATTERNS = [
    re.compile(r'^total\s*$', re.IGNORECASE),
    re.compile(r'^total\s*,', re.IGNORECASE),
    re.compile(r'^total\s+\(', re.IGNORECASE),
    re.compile(r'^ambele\s+sexe', re.IGNORECASE),
]

# Composite dimension detection: column name has 2+ of these keywords
COMPOSITE_KEYWORDS = {
    'gender':    re.compile(r'\bsexe?\b', re.IGNORECASE),
    'age':       re.compile(r'grupe_de_varst|varst', re.IGNORECASE),
    'education': re.compile(r'nivel_de_educ|educatie', re.IGNORECASE),
    'region':    re.compile(r'regi(uni)?', re.IGNORECASE),
}

SUBGROUP_LABELS = {
    'gender': 'Gen',
    'age': 'Grupe de varsta',
    'education': 'Nivel de educatie',
    'region': 'Regiuni',
}

# Option label → sub-group classification
OPTION_LABEL_PATTERNS = [
    ('gender',    re.compile(r'^(masculin|feminin|b[aă]rba[tț]i|femei)$', re.IGNORECASE)),
    ('age',       re.compile(r'^\d{1,3}\s*[-\u2013]\s*\d{1,3}\s*ani|\d+\s*ani\s*(si|și)\s*peste', re.IGNORECASE)),
    ('education', re.compile(r'nivel\s*de\s*educa', re.IGNORECASE)),
    ('region',    re.compile(r'^(macroregiunea|regiunea)\s', re.IGNORECASE)),
]

log = logging.getLogger("view-profiler")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

class MetadataLoader:
    """Load all metadata from DuckDB in one pass."""

    def __init__(self, db_path: Path):
        self.conn = duckdb.connect(str(db_path), read_only=True)

    def close(self):
        self.conn.close()

    def load_profiles(self) -> dict:
        """Load matrix_profiles keyed by matrix_code."""
        rows = self.conn.execute("""
            SELECT matrix_code, has_time, time_granularity, time_year_min, time_year_max,
                   has_geo, geo_levels, has_gender, has_age, has_residence,
                   unit_types, primary_unit_type, dim_count, archetype, parse_coverage
            FROM matrix_profiles
        """).fetchall()
        cols = ['matrix_code', 'has_time', 'time_granularity', 'time_year_min', 'time_year_max',
                'has_geo', 'geo_levels', 'has_gender', 'has_age', 'has_residence',
                'unit_types', 'primary_unit_type', 'dim_count', 'archetype', 'parse_coverage']
        return {r[0]: dict(zip(cols, r)) for r in rows}

    def load_matrices(self) -> dict:
        """Load matrix names."""
        rows = self.conn.execute("SELECT matrix_code, matrix_name FROM matrices").fetchall()
        return {r[0]: r[1] for r in rows}

    def load_dimensions(self) -> dict:
        """Load dimensions grouped by matrix_code."""
        rows = self.conn.execute("""
            SELECT d.dimension_id, d.matrix_code, d.dim_code, d.dim_label,
                   d.dim_column_name, d.option_count
            FROM dimensions d
            ORDER BY d.matrix_code, d.dim_code
        """).fetchall()
        cols = ['dimension_id', 'matrix_code', 'dim_code', 'dim_label',
                'dim_column_name', 'option_count']
        result = {}
        for r in rows:
            d = dict(zip(cols, r))
            result.setdefault(d['matrix_code'], []).append(d)
        return result

    def load_dim_types(self) -> dict:
        """Load majority dim_type per dimension_id from dimension_options_parsed."""
        rows = self.conn.execute("""
            SELECT do2.dimension_id, dop.dim_type, COUNT(*) as cnt
            FROM dimension_options do2
            JOIN dimension_options_parsed dop ON dop.nom_item_id = do2.nom_item_id
            GROUP BY do2.dimension_id, dop.dim_type
        """).fetchall()
        # Pick majority type per dimension
        dim_types = {}
        for dim_id, dtype, cnt in rows:
            if dim_id not in dim_types or cnt > dim_types[dim_id][1]:
                dim_types[dim_id] = (dtype, cnt)
        return {k: v[0] for k, v in dim_types.items()}

    def load_has_total(self) -> set:
        """Return set of dimension_ids that have a Total-like option."""
        rows = self.conn.execute("""
            SELECT DISTINCT do2.dimension_id
            FROM dimension_options do2
            WHERE do2.option_label IN ('Total', 'TOTAL', 'Total ', 'Ambele sexe')
               OR do2.option_label LIKE 'Total,%'
               OR do2.option_label LIKE 'Total (%'
               OR do2.option_label LIKE 'TOTAL (%'
        """).fetchall()
        return {r[0] for r in rows}

    def load_options_for_dims(self, dim_ids: list) -> dict:
        """Returns {dimension_id: [(nom_item_id, option_label), ...]} for given dim IDs."""
        if not dim_ids:
            return {}
        placeholders = ', '.join(['?' for _ in dim_ids])
        rows = self.conn.execute(f"""
            SELECT dimension_id, nom_item_id, option_label
            FROM dimension_options
            WHERE dimension_id IN ({placeholders})
            ORDER BY dimension_id, option_id
        """, dim_ids).fetchall()
        result = {}
        for dim_id, nom_item_id, label in rows:
            result.setdefault(dim_id, []).append((nom_item_id, label))
        return result

    def load_hierarchy_dims(self) -> set:
        """Return set of dimension_ids where >50% options have parent_id."""
        rows = self.conn.execute("""
            SELECT dimension_id,
                   COUNT(*) as total,
                   SUM(CASE WHEN parent_id IS NOT NULL AND parent_id != 0 THEN 1 ELSE 0 END) as with_parent
            FROM dimension_options
            GROUP BY dimension_id
        """).fetchall()
        return {dim_id for dim_id, total, with_parent in rows
                if total > 0 and with_parent / total > 0.5}

    def load_splits(self) -> dict:
        """Load dataset_splits: {parent_code: [{code, label, pattern, row_count}, ...]}"""
        rows = self.conn.execute("""
            SELECT parent_matrix_code, sub_matrix_code, suffix_label, split_pattern, row_count
            FROM dataset_splits
            ORDER BY parent_matrix_code, sub_matrix_code
        """).fetchall()
        result = {}
        for parent, sub, label, pattern, row_count in rows:
            result.setdefault(parent, []).append({
                'code': sub, 'label': label or sub,
                'split_pattern': pattern, 'row_count': row_count,
            })
        return result

    def load_split_matrices(self) -> dict:
        """Load is_split=TRUE matrices with their parent_matrix_code."""
        rows = self.conn.execute("""
            SELECT matrix_code, matrix_name, parent_matrix_code
            FROM matrices WHERE is_split = TRUE
        """).fetchall()
        return {r[0]: {'matrix_name': r[1], 'parent_matrix_code': r[2]} for r in rows}

    def load_coverage(self) -> dict:
        """Load dataset_coverage keyed by matrix_code."""
        rows = self.conn.execute("""
            SELECT matrix_code, time_dim_column, time_min_year, time_max_year,
                   time_year_count, time_granularity, geo_dim_column, geo_county_count,
                   geo_has_national, geo_has_locality, fill_rate, freshness_years, dim_count
            FROM dataset_coverage
        """).fetchall()
        cols = ['matrix_code', 'time_dim_column', 'time_min_year', 'time_max_year',
                'time_year_count', 'time_granularity', 'geo_dim_column', 'geo_county_count',
                'geo_has_national', 'geo_has_locality', 'fill_rate', 'freshness_years', 'dim_count']
        return {r[0]: dict(zip(cols, r)) for r in rows}

    def load_value_profiles(self) -> dict:
        """Load dataset_value_profiles keyed by matrix_code."""
        rows = self.conn.execute("""
            SELECT matrix_code, row_count, val_min, val_max, val_mean,
                   null_pct, zero_pct, negative_pct, coeff_variation,
                   magnitude, distribution_shape
            FROM dataset_value_profiles
        """).fetchall()
        cols = ['matrix_code', 'row_count', 'val_min', 'val_max', 'val_mean',
                'null_pct', 'zero_pct', 'negative_pct', 'coeff_variation',
                'magnitude', 'distribution_shape']
        return {r[0]: dict(zip(cols, r)) for r in rows}

    def load_trends(self) -> dict:
        """Load dataset_trends keyed by matrix_code."""
        rows = self.conn.execute("""
            SELECT matrix_code, trend_direction, trend_slope, yoy_growth_latest,
                   has_seasonality
            FROM dataset_trends
        """).fetchall()
        cols = ['matrix_code', 'trend_direction', 'trend_slope', 'yoy_growth_latest',
                'has_seasonality']
        return {r[0]: dict(zip(cols, r)) for r in rows}


# ---------------------------------------------------------------------------
# Dimension classifier
# ---------------------------------------------------------------------------

def classify_cardinality(option_count: int) -> str:
    if option_count <= CARD_LOW[1]:
        return "low"
    if option_count <= CARD_MEDIUM[1]:
        return "medium"
    if option_count <= CARD_HIGH[1]:
        return "high"
    return "very_high"


def detect_composite_keys(col_name: str) -> list:
    """Return list of sub-category keys found in column name. Composite if len >= 2."""
    return [key for key, pat in COMPOSITE_KEYWORDS.items() if pat.search(col_name or '')]


def classify_option_label(label: str) -> str | None:
    """Classify an option label into a sub-category key, or None if unclassified."""
    for key, pat in OPTION_LABEL_PATTERNS:
        if pat.search(label or ''):
            return key
    return None


def build_subgroups(options: list) -> list:
    """Classify (nom_item_id, label) pairs into sub-groups. Returns [{key, label, ids}]."""
    groups = {}
    order = []
    for nom_item_id, label in options:
        key = classify_option_label(label)
        if key is None:
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(nom_item_id)
    return [
        {'key': k, 'label': SUBGROUP_LABELS.get(k, k), 'ids': groups[k]}
        for k in order if groups[k]
    ]


def is_caen_label(label: str) -> bool:
    return any(p.search(label) for p in CAEN_PATTERNS)


def is_singleton(option_count: int, has_total: bool) -> bool:
    """A dim is singleton if it has 1 option, or 2 options where one is Total."""
    if option_count <= 1:
        return True
    if option_count == 2 and has_total:
        return True
    return False


def classify_dimension(dim: dict, dim_type: str, has_total: bool, has_hierarchy: bool) -> dict:
    """Classify a single dimension into a structured dict."""
    oc = dim['option_count'] or 0
    singleton = is_singleton(oc, has_total)

    return {
        'column': dim['dim_column_name'],
        'label': dim['dim_label'],
        'dim_type': dim_type,
        'option_count': oc,
        'cardinality': classify_cardinality(oc),
        'has_total': has_total,
        'has_hierarchy': has_hierarchy,
        'is_caen': is_caen_label(dim['dim_label'] or ''),
        'is_singleton': singleton,
    }


# ---------------------------------------------------------------------------
# Control builder
# ---------------------------------------------------------------------------

def control_type_for_dim(dim_info: dict, role: str = "filter") -> str:
    """Determine the UI control type for a dimension based on cardinality and role."""
    if dim_info['is_caen'] or dim_info['cardinality'] == 'very_high':
        return "typeahead_select"
    if dim_info['has_hierarchy']:
        return "tree_select"
    if role == "series":
        if dim_info['cardinality'] in ('high', 'very_high'):
            return "typeahead_select"
        if dim_info['cardinality'] == 'medium':
            return "multi_select"
        return "pill_group"
    # filter role
    if dim_info['dim_type'] == 'geo':
        return "multi_select"
    if dim_info['cardinality'] == 'low':
        return "pill_group"
    if dim_info['cardinality'] == 'medium':
        return "multi_select"
    if dim_info['cardinality'] == 'high':
        return "single_select"
    return "typeahead_select"


def default_for_dim(dim_info: dict) -> str:
    """Determine default selection for a dimension."""
    if dim_info['dim_type'] == 'geo':
        return "all"
    if dim_info['has_total']:
        return "total"
    return "first"


def build_control(dim_info: dict, scope: str = "view", role: str = "filter",
                  max_selected: int | None = None) -> dict:
    ctrl = {
        "type": control_type_for_dim(dim_info, role),
        "column": dim_info['column'],
        "label": dim_info['label'],
        "scope": scope,
        "default": default_for_dim(dim_info),
    }
    if max_selected:
        ctrl["max_selected"] = max_selected
    return ctrl


# ---------------------------------------------------------------------------
# View builders
# ---------------------------------------------------------------------------

def pick_series_dim(analysis_dims: list, exclude_cols: set = None) -> dict | None:
    """Pick the best dimension for chart series from analysis dims.

    Preference: gender > residence > smallest indicator (≤8) > age (≤8) > None
    """
    exclude = exclude_cols or set()
    candidates = [d for d in analysis_dims if d['column'] not in exclude and not d['is_singleton']]
    if not candidates:
        return None

    # Priority 1: gender
    for d in candidates:
        if d['dim_type'] == 'gender':
            return d
    # Priority 2: residence
    for d in candidates:
        if d['dim_type'] == 'residence':
            return d
    # Priority 3: smallest indicator ≤ 8
    indicators = [d for d in candidates if d['dim_type'] == 'indicator' and d['option_count'] <= 8]
    if indicators:
        return min(indicators, key=lambda d: d['option_count'])
    # Priority 4: age ≤ 8
    for d in candidates:
        if d['dim_type'] == 'age' and d['option_count'] <= 8:
            return d
    # Priority 5: any dim ≤ 15
    small = [d for d in candidates if d['option_count'] <= 15]
    if small:
        return min(small, key=lambda d: d['option_count'])
    # Fallback: any (will need typeahead)
    return min(candidates, key=lambda d: d['option_count'])


def build_timeline_view(time_dim: dict, analysis_dims: list, geo_dim: dict | None,
                        unit_dim: dict | None, profile: dict, vp: dict,
                        coverage: dict) -> dict | None:
    """Build timeline view specification."""
    time_points = coverage.get('time_year_count') or 0
    if time_points == 0 and profile.get('time_year_min') and profile.get('time_year_max'):
        time_points = profile['time_year_max'] - profile['time_year_min'] + 1

    if not profile.get('has_time') or time_points < 3:
        return None

    charts = []
    controls = []
    non_singleton = [d for d in analysis_dims if not d['is_singleton']]

    # --- Primary line chart ---
    series_dim = pick_series_dim(non_singleton)
    filter_dims = [d for d in non_singleton if d != series_dim]

    roles = {"x_axis": time_dim['column']}
    if series_dim:
        roles["series"] = series_dim['column']
    roles["filter"] = [d['column'] for d in filter_dims]

    # Add geo as filter if present
    if geo_dim and not geo_dim['is_singleton']:
        roles["filter"].append(geo_dim['column'])

    toggles = []
    has_neg = (vp.get('negative_pct') or 0) > 0
    if time_points < 5:
        toggles.append("bar_vertical")
    if not has_neg and series_dim and 2 <= series_dim['option_count'] <= 6:
        toggles.append("area_stacked")

    max_series = None
    if series_dim and series_dim['option_count'] > 8 and not series_dim.get('is_composite'):
        max_series = 8

    chart = {
        "chart_type": "line",
        "is_primary": True,
        "roles": roles,
    }
    if toggles:
        chart["toggles"] = toggles
    if max_series:
        chart["max_series"] = max_series
    charts.append(chart)

    # --- Variant line charts (one per unused analysis dim as series) ---
    if len(non_singleton) >= 2 and series_dim:
        for alt_dim in non_singleton:
            if alt_dim == series_dim:
                continue
            alt_filter = [d for d in non_singleton if d != alt_dim]
            alt_roles = {
                "x_axis": time_dim['column'],
                "series": alt_dim['column'],
                "filter": [d['column'] for d in alt_filter],
            }
            if geo_dim and not geo_dim['is_singleton']:
                alt_roles["filter"].append(geo_dim['column'])

            alt_chart = {
                "chart_type": "line",
                "is_primary": False,
                "variant": f"by_{alt_dim['column'].replace('_nom_id', '')}",
                "roles": alt_roles,
            }
            alt_ms = 8 if alt_dim['option_count'] > 8 else None
            if alt_ms:
                alt_chart["max_series"] = alt_ms
            charts.append(alt_chart)

    # --- Controls ---
    # Geo as single-select filter
    if geo_dim and not geo_dim['is_singleton']:
        controls.append(build_control(geo_dim, scope="view", role="filter"))

    # Analysis dims as filters
    for d in filter_dims:
        if d['is_singleton']:
            continue
        controls.append(build_control(d, scope="view", role="filter",
                                      max_selected=8 if d['option_count'] > 25 else None))

    return {
        "available": True,
        "charts": charts,
        "controls": controls,
    }


def build_snapshot_view(time_dim: dict | None, analysis_dims: list,
                        geo_dim: dict | None, unit_dim: dict | None,
                        profile: dict, vp: dict, coverage: dict) -> dict:
    """Build snapshot view specification."""
    charts = []
    controls = []
    non_singleton = [d for d in analysis_dims if not d['is_singleton']]

    has_geo = profile.get('has_geo', False)
    geo_county_count = coverage.get('geo_county_count') or 0
    # Use actual geo option_count if county count is 0 (regional datasets)
    geo_count = geo_county_count or (geo_dim['option_count'] if geo_dim else 0)
    has_neg = (vp.get('negative_pct') or 0) > 0
    fill_rate = coverage.get('fill_rate') or 1.0

    # Year range / period browser
    year_range = None
    granularity = coverage.get('time_granularity') or profile.get('time_granularity')
    time_points = coverage.get('time_year_count') or 0
    if time_dim and time_points >= 2:
        yr_min = coverage.get('time_min_year') or profile.get('time_year_min')
        yr_max = coverage.get('time_max_year') or profile.get('time_year_max')
        if yr_min and yr_max:
            year_range = [yr_min, yr_max]
        controls.append({
            "type": "period_browser",
            "column": time_dim['column'],
            "scope": "view",
            "granularity": granularity or "annual",
            "default": "latest",
        })

    # --- 1. Choropleth ---
    # Requires county-level geo (need GeoJSON polygons), not just regions
    if has_geo and geo_dim and geo_county_count >= 5 and not geo_dim['is_singleton']:
        geo_has_locality = coverage.get('geo_has_locality', False)
        if not geo_has_locality:  # Only if we have county/region level, not locality
            choropleth_roles = {"x_axis": geo_dim['column']}
            chart = {
                "chart_type": "choropleth",
                "is_primary": True,
                "roles": choropleth_roles,
            }
            charts.append(chart)
            # Choropleth needs single-select on analysis dims
            for d in non_singleton:
                controls.append(build_control(d, scope="chart:choropleth", role="filter"))

    # --- 2. Bar chart ---
    if has_geo and geo_dim and geo_count >= 5 and not geo_dim['is_singleton']:
        # Horizontal bar with geo ranking
        bar_roles = {"x_axis": geo_dim['column']}
        low_card = [d for d in non_singleton if d['option_count'] <= 6]
        bar_toggles = []
        if low_card:
            bar_roles["series"] = low_card[0]['column']
            if not has_neg and 2 <= low_card[0]['option_count'] <= 4:
                bar_toggles = ["stacked_bar"]
        bar_toggles.append("line")  # Line distribution curve toggle
        bar_chart = {
            "chart_type": "horizontal_bar",
            "is_primary": len(charts) == 0,  # primary if no choropleth
            "roles": bar_roles,
        }
        if bar_toggles:
            bar_chart["toggles"] = bar_toggles
        charts.append(bar_chart)
    elif non_singleton:
        # Bar without geo — use analysis dims
        sorted_dims = sorted(non_singleton, key=lambda d: d['option_count'], reverse=True)
        x_dim = sorted_dims[0]
        bar_roles = {"x_axis": x_dim['column']}
        bar_toggles = []
        series_candidates = [d for d in sorted_dims[1:] if d['option_count'] <= 6]
        if series_candidates:
            bar_roles["series"] = series_candidates[0]['column']
            if not has_neg and 2 <= series_candidates[0]['option_count'] <= 4:
                bar_toggles = ["stacked_bar"]
        # Choose chart type based on cardinality
        if x_dim['option_count'] > 20:
            chart_type = "horizontal_bar"  # long list → horizontal ranking
        elif "series" in bar_roles:
            chart_type = "grouped_bar"
        else:
            chart_type = "bar_vertical"
        bar_chart = {
            "chart_type": chart_type,
            "is_primary": len(charts) == 0,
            "roles": bar_roles,
        }
        bar_toggles.append("line")  # Line distribution curve toggle
        if bar_toggles:
            bar_chart["toggles"] = bar_toggles
        charts.append(bar_chart)

    # --- 3. Population pyramid ---
    has_age = profile.get('has_age', False)
    has_gender = profile.get('has_gender', False)
    age_dim = next((d for d in non_singleton if d['dim_type'] == 'age'), None)
    gender_dim = next((d for d in non_singleton if d['dim_type'] == 'gender'), None)

    if has_age and has_gender and age_dim and gender_dim:
        gc = gender_dim['option_count']
        if 2 <= gc <= 3:
            pyramid = {
                "chart_type": "population_pyramid",
                "is_primary": len(charts) == 0,
                "roles": {
                    "x_axis": age_dim['column'],
                    "series": gender_dim['column'],
                },
            }
            charts.append(pyramid)
            # If pyramid is present, promote it to primary over bar
            for c in charts:
                if c['chart_type'] in ('grouped_bar', 'bar_vertical'):
                    c['is_primary'] = False
            pyramid['is_primary'] = True

    # --- 3b. Variant snapshot bars (all dim pairs) ---
    if len(non_singleton) >= 2:
        primary_bar = next((c for c in charts
            if c['chart_type'] in ('grouped_bar', 'bar_vertical', 'horizontal_bar')), None)
        primary_x = primary_bar['roles'].get('x_axis') if primary_bar else None
        primary_s = primary_bar['roles'].get('series') if primary_bar else None

        for x_dim in non_singleton:
            for s_dim in non_singleton:
                if x_dim == s_dim:
                    continue
                if x_dim['column'] == primary_x and s_dim['column'] == primary_s:
                    continue  # Skip existing primary
                if s_dim['option_count'] > 8:
                    continue  # Series too large
                ct = "horizontal_bar" if x_dim['option_count'] > 20 else "grouped_bar"
                variant = {
                    "chart_type": ct,
                    "is_primary": False,
                    "variant": f"{x_dim['column']}_by_{s_dim['column']}",
                    "roles": {
                        "x_axis": x_dim['column'],
                        "series": s_dim['column'],
                    },
                }
                if 2 <= s_dim['option_count'] <= 4:
                    variant["toggles"] = ["stacked_bar"]
                charts.append(variant)

    # --- 4. Bubble/matrix ---
    qualifying = [d for d in non_singleton if d['option_count'] >= 3]
    if len(qualifying) >= 2:
        q_sorted = sorted(qualifying, key=lambda d: d['option_count'])
        bubble = {
            "chart_type": "bubble",
            "is_primary": False,
            "roles": {
                "x_axis": q_sorted[0]['column'],
                "series": q_sorted[1]['column'],
            },
        }
        if len(qualifying) > 2:
            bubble["dimension_pair_toggle"] = True
        charts.append(bubble)

    # --- 5. Heatmap ---
    heatmap_candidates = [d for d in non_singleton if d['option_count'] >= 5]
    has_large = any(d['option_count'] >= 10 for d in heatmap_candidates)
    if len(heatmap_candidates) >= 2 and has_large and fill_rate > 0.3:
        h_sorted = sorted(heatmap_candidates, key=lambda d: d['option_count'], reverse=True)
        heatmap = {
            "chart_type": "heatmap",
            "is_primary": False,
            "roles": {
                "x_axis": h_sorted[0]['column'],
                "series": h_sorted[1]['column'],
            },
        }
        charts.append(heatmap)

    # --- Controls for non-choropleth charts ---
    # Filter dims not already assigned as x_axis/series in the primary chart
    primary = next((c for c in charts if c.get('is_primary')), None)
    assigned_cols = set()
    if primary:
        assigned_cols.add(primary['roles'].get('x_axis'))
        assigned_cols.add(primary['roles'].get('series'))
    assigned_cols.discard(None)

    for d in non_singleton:
        if d['column'] in assigned_cols:
            continue
        # Skip if already added as choropleth control
        existing = {c['column'] for c in controls if c.get('type') != 'period_browser'}
        if d['column'] not in existing:
            controls.append(build_control(d, scope="view", role="filter"))

    # Geo as filter when not on axis
    if geo_dim and not geo_dim['is_singleton'] and geo_dim['column'] not in assigned_cols:
        existing = {c['column'] for c in controls}
        if geo_dim['column'] not in existing:
            controls.append(build_control(geo_dim, scope="view", role="filter"))

    result = {
        "available": True,
        "charts": charts,
        "controls": controls,
    }
    if year_range:
        result["year_range"] = year_range
        result["default_period"] = "latest"
        result["granularity"] = granularity or "annual"
    return result


# ---------------------------------------------------------------------------
# Warning generator
# ---------------------------------------------------------------------------

def generate_warnings(profile: dict, coverage: dict, vp: dict,
                      classified_dims: list) -> list:
    warnings = []
    fill_rate = coverage.get('fill_rate') or 1.0
    if fill_rate < 0.10:
        warnings.append({
            "type": "very_sparse",
            "message": f"Very sparse dataset ({fill_rate:.0%} data coverage)",
            "severity": "warning",
        })
    elif fill_rate < 0.25:
        warnings.append({
            "type": "sparse_data",
            "message": f"Sparse dataset ({fill_rate:.0%} data coverage)",
            "severity": "warning",
        })

    time_points = coverage.get('time_year_count') or 0
    if 0 < time_points < 3:
        warnings.append({
            "type": "short_series",
            "message": f"Only {time_points} time period(s) available",
            "severity": "info",
        })

    for d in classified_dims:
        if d['dim_type'] not in ('geo', 'time', 'unit') and d['option_count'] > 100:
            warnings.append({
                "type": "high_cardinality",
                "message": f"Large dimension '{d['label']}' ({d['option_count']} options)",
                "severity": "info",
            })

    # multi-unit
    unit_types_raw = profile.get('unit_types', '[]') or '[]'
    try:
        unit_types = json.loads(unit_types_raw) if isinstance(unit_types_raw, str) else (unit_types_raw or [])
    except (json.JSONDecodeError, TypeError):
        unit_types = []
    if len(unit_types) > 1:
        warnings.append({
            "type": "multi_unit",
            "message": f"Multiple measurement units: {', '.join(unit_types[:5])}",
            "severity": "info",
        })

    return warnings


# ---------------------------------------------------------------------------
# Main profile generator
# ---------------------------------------------------------------------------

class ProfileGenerator:

    def __init__(self, db_path: Path, debug: bool = False):
        self.debug = debug
        self.loader = MetadataLoader(db_path)
        log.info("Loading metadata from %s...", db_path)
        self.profiles = self.loader.load_profiles()
        self.matrices = self.loader.load_matrices()
        self.dimensions = self.loader.load_dimensions()
        self.dim_types = self.loader.load_dim_types()
        self.has_total_set = self.loader.load_has_total()
        self.hierarchy_set = self.loader.load_hierarchy_dims()
        self.coverage = self.loader.load_coverage()
        self.value_profiles = self.loader.load_value_profiles()
        self.trends = self.loader.load_trends()
        self.splits = self.loader.load_splits()
        self.split_matrices = self.loader.load_split_matrices()
        log.info("Loaded %d datasets, %d parents with splits",
                 len(self.profiles), len(self.splits))

        # Pre-detect composite dims and batch-load their options
        composite_dim_ids = []
        for dims_raw in self.dimensions.values():
            for d in dims_raw:
                if len(detect_composite_keys(d['dim_column_name'] or '')) >= 2:
                    composite_dim_ids.append(d['dimension_id'])
        self.composite_options = self.loader.load_options_for_dims(composite_dim_ids)
        log.info("Found %d composite dimensions", len(composite_dim_ids))

    def close(self):
        self.loader.close()

    def generate_profile(self, matrix_code: str) -> dict | None:
        profile = self.profiles.get(matrix_code)
        if not profile:
            log.warning("No profile for %s", matrix_code)
            return None

        dims_raw = self.dimensions.get(matrix_code, [])
        cov = self.coverage.get(matrix_code, {})
        vp = self.value_profiles.get(matrix_code, {})
        trend = self.trends.get(matrix_code, {})

        # --- Classify dimensions ---
        classified = []
        for d in dims_raw:
            dim_id = d['dimension_id']
            dtype = self.dim_types.get(dim_id, 'indicator')
            has_total = dim_id in self.has_total_set
            has_hier = dim_id in self.hierarchy_set
            cd = classify_dimension(d, dtype, has_total, has_hier)

            # Composite detection: column name has 2+ sub-category keywords
            comp_keys = detect_composite_keys(d['dim_column_name'] or '')
            if len(comp_keys) >= 2 and dim_id in self.composite_options:
                sg = build_subgroups(self.composite_options[dim_id])
                if len(sg) >= 2:
                    cd['is_composite'] = True
                    cd['subgroups'] = sg

            classified.append(cd)

        # Separate by type — prefer time dim with most options when multiple exist
        # (e.g. TIME_PERIOD=1 opt is indicator name, TIME_PERIOD_2=10 opts is actual years)
        _time_dims = [d for d in classified if d['dim_type'] == 'time']
        time_dim = max(_time_dims, key=lambda d: d['option_count']) if _time_dims else None
        geo_dim = next((d for d in classified if d['dim_type'] == 'geo'), None)
        unit_dim = next((d for d in classified if d['dim_type'] == 'unit'), None)
        gender_dim = next((d for d in classified if d['dim_type'] == 'gender'), None)
        age_dim = next((d for d in classified if d['dim_type'] == 'age'), None)
        residence_dim = next((d for d in classified if d['dim_type'] == 'residence'), None)

        analysis_dims = [d for d in classified
                         if d['dim_type'] in ('indicator', 'gender', 'age', 'residence')]
        singleton_dims = [d['column'] for d in classified if d['is_singleton']]

        # Multi-unit detection
        multi_unit = False
        if unit_dim and unit_dim['option_count'] > 1:
            multi_unit = True

        # --- Build dimensions section ---
        geo_levels_raw = profile.get('geo_levels', '[]') or '[]'
        try:
            geo_levels = json.loads(geo_levels_raw) if isinstance(geo_levels_raw, str) else (geo_levels_raw or [])
        except (json.JSONDecodeError, TypeError):
            geo_levels = []

        granularity = cov.get('time_granularity') or profile.get('time_granularity')
        yr_min = cov.get('time_min_year') or profile.get('time_year_min')
        yr_max = cov.get('time_max_year') or profile.get('time_year_max')

        dimensions_section = {
            "time": {
                "column": time_dim['column'],
                "label": time_dim['label'],
                "option_count": time_dim['option_count'],
                "granularity": granularity,
                "year_range": [yr_min, yr_max] if yr_min and yr_max else None,
            } if time_dim else None,
            "geo": {
                "column": geo_dim['column'],
                "label": geo_dim['label'],
                "option_count": geo_dim['option_count'],
                "geo_levels": geo_levels,
            } if geo_dim and not geo_dim['is_singleton'] else None,
            "categories": [
                {
                    "column": d['column'],
                    "label": d['label'],
                    "option_count": d['option_count'],
                    "has_total": d['has_total'],
                    "cardinality": d['cardinality'],
                    "is_caen": d['is_caen'],
                    "has_hierarchy": d['has_hierarchy'],
                    **({"is_composite": True, "subgroups": d['subgroups']} if d.get('is_composite') else {}),
                }
                for d in analysis_dims if not d['is_singleton']
            ],
            "unit": {
                "column": unit_dim['column'],
                "option_count": unit_dim['option_count'],
                "multi_unit": multi_unit,
            } if unit_dim else None,
            "gender": gender_dim['column'] if gender_dim and not gender_dim['is_singleton'] else None,
            "age": age_dim['column'] if age_dim and not age_dim['is_singleton'] else None,
            "residence": residence_dim['column'] if residence_dim and not residence_dim['is_singleton'] else None,
            "singleton_dims": singleton_dims,
        }

        # --- Build views ---
        timeline = build_timeline_view(
            time_dim, analysis_dims, geo_dim, unit_dim, profile, vp, cov
        ) if time_dim else None

        snapshot = build_snapshot_view(
            time_dim, analysis_dims, geo_dim, unit_dim, profile, vp, cov
        )

        # --- Page-level controls (multi-unit) ---
        page_controls = []
        if multi_unit and unit_dim:
            page_controls.append({
                "type": "single_select",
                "column": unit_dim['column'],
                "label": "Unitate de masura",
                "scope": "page",
                "default": "first",
                "mandatory": True,
            })

        # --- Warnings ---
        warnings = generate_warnings(profile, cov, vp, classified)

        # --- Assemble ---
        result = {
            "matrix_code": matrix_code,
            "matrix_name": self.matrices.get(matrix_code, ""),
            "archetype": profile.get('archetype', 'time_series'),
            "dim_count": profile.get('dim_count') or len(dims_raw),
            "dimensions": dimensions_section,
            "page_controls": page_controls if page_controls else None,
            "views": {
                "timeline": timeline if timeline else {"available": False},
                "snapshot": snapshot,
                "table": {"available": True},
            },
            "warnings": warnings,
            "meta": {
                "profile_version": PROFILE_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "fill_rate": round(cov.get('fill_rate') or 0, 3),
                "row_count": vp.get('row_count'),
                "trend_direction": trend.get('trend_direction'),
                "distribution_shape": vp.get('distribution_shape'),
            },
        }

        # Add sub_datasets reference if this parent has splits
        if matrix_code in self.splits:
            result["sub_datasets"] = self.splits[matrix_code]

        # Remove None values at top level for cleaner JSON
        result = {k: v for k, v in result.items() if v is not None}

        if self.debug:
            log.debug("Profile for %s: timeline=%s, snapshot_charts=%d, warnings=%d",
                      matrix_code,
                      "yes" if timeline else "no",
                      len(snapshot.get('charts', [])),
                      len(warnings))

        return result

    def generate_sub_profile(self, matrix_code: str) -> dict | None:
        """Generate a lightweight view profile for a sub-dataset (is_split=TRUE).

        Sub-datasets don't have matrix_profiles entries, so we build a profile
        from their dimensions and inherit coverage/trend from the parent.
        """
        split_info = self.split_matrices.get(matrix_code)
        if not split_info:
            return None

        parent_code = split_info['parent_matrix_code']
        parent_profile = self.profiles.get(parent_code)
        if not parent_profile:
            log.debug("No parent profile for sub-dataset %s (parent=%s)", matrix_code, parent_code)
            return None

        dims_raw = self.dimensions.get(matrix_code, [])
        if not dims_raw:
            log.debug("No dimensions for sub-dataset %s", matrix_code)
            return None

        # Use parent's coverage and value profile as fallback
        cov = self.coverage.get(matrix_code, self.coverage.get(parent_code, {}))
        vp = self.value_profiles.get(matrix_code, self.value_profiles.get(parent_code, {}))
        trend = self.trends.get(matrix_code, self.trends.get(parent_code, {}))

        # Classify dims
        classified = []
        for d in dims_raw:
            dim_id = d['dimension_id']
            dtype = self.dim_types.get(dim_id, 'indicator')
            has_total = dim_id in self.has_total_set
            has_hier = dim_id in self.hierarchy_set
            cd = classify_dimension(d, dtype, has_total, has_hier)
            classified.append(cd)

        # Separate by type — prefer time dim with most options when multiple exist
        # (e.g. TIME_PERIOD=1 opt is indicator name, TIME_PERIOD_2=10 opts is actual years)
        _time_dims = [d for d in classified if d['dim_type'] == 'time']
        time_dim = max(_time_dims, key=lambda d: d['option_count']) if _time_dims else None
        geo_dim = next((d for d in classified if d['dim_type'] == 'geo'), None)
        unit_dim = next((d for d in classified if d['dim_type'] == 'unit'), None)
        gender_dim = next((d for d in classified if d['dim_type'] == 'gender'), None)
        age_dim = next((d for d in classified if d['dim_type'] == 'age'), None)
        residence_dim = next((d for d in classified if d['dim_type'] == 'residence'), None)

        analysis_dims = [d for d in classified
                         if d['dim_type'] in ('indicator', 'gender', 'age', 'residence')]
        singleton_dims = [d['column'] for d in classified if d['is_singleton']]

        multi_unit = False
        if unit_dim and unit_dim['option_count'] > 1:
            multi_unit = True

        granularity = cov.get('time_granularity') or parent_profile.get('time_granularity')
        yr_min = cov.get('time_min_year') or parent_profile.get('time_year_min')
        yr_max = cov.get('time_max_year') or parent_profile.get('time_year_max')

        dimensions_section = {
            "time": {
                "column": time_dim['column'],
                "label": time_dim['label'],
                "option_count": time_dim['option_count'],
                "granularity": granularity,
                "year_range": [yr_min, yr_max] if yr_min and yr_max else None,
            } if time_dim else None,
            "geo": {
                "column": geo_dim['column'],
                "label": geo_dim['label'],
                "option_count": geo_dim['option_count'],
            } if geo_dim and not geo_dim['is_singleton'] else None,
            "categories": [
                {
                    "column": d['column'],
                    "label": d['label'],
                    "option_count": d['option_count'],
                    "has_total": d['has_total'],
                    "cardinality": d['cardinality'],
                    "is_caen": d['is_caen'],
                    "has_hierarchy": d['has_hierarchy'],
                }
                for d in analysis_dims if not d['is_singleton']
            ],
            "unit": {
                "column": unit_dim['column'],
                "option_count": unit_dim['option_count'],
                "multi_unit": multi_unit,
            } if unit_dim else None,
            "singleton_dims": singleton_dims,
        }

        # Build views using parent profile fields
        timeline = build_timeline_view(
            time_dim, analysis_dims, geo_dim, unit_dim, parent_profile, vp, cov
        ) if time_dim else None

        snapshot = build_snapshot_view(
            time_dim, analysis_dims, geo_dim, unit_dim, parent_profile, vp, cov
        )

        page_controls = []
        if multi_unit and unit_dim:
            page_controls.append({
                "type": "single_select",
                "column": unit_dim['column'],
                "label": "Unitate de masura",
                "scope": "page",
                "default": "first",
                "mandatory": True,
            })

        warnings = generate_warnings(parent_profile, cov, vp, classified)

        result = {
            "matrix_code": matrix_code,
            "matrix_name": split_info['matrix_name'],
            "parent_matrix_code": parent_code,
            "archetype": parent_profile.get('archetype', 'time_series'),
            "dim_count": len(dims_raw),
            "dimensions": dimensions_section,
            "page_controls": page_controls if page_controls else None,
            "views": {
                "timeline": timeline if timeline else {"available": False},
                "snapshot": snapshot,
                "table": {"available": True},
            },
            "warnings": warnings,
            "meta": {
                "profile_version": PROFILE_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "fill_rate": round(cov.get('fill_rate') or 0, 3),
                "row_count": vp.get('row_count'),
                "trend_direction": trend.get('trend_direction'),
                "distribution_shape": vp.get('distribution_shape'),
            },
        }

        result = {k: v for k, v in result.items() if v is not None}
        return result

    def generate_all(self) -> dict:
        results = {}
        errors = []

        # Parent datasets (from matrix_profiles)
        for code in sorted(self.profiles.keys()):
            try:
                p = self.generate_profile(code)
                if p:
                    results[code] = p
            except Exception as e:
                log.error("Error generating profile for %s: %s", code, e)
                errors.append((code, str(e)))

        # Sub-datasets (is_split=TRUE)
        sub_count = 0
        for code in sorted(self.split_matrices.keys()):
            try:
                p = self.generate_sub_profile(code)
                if p:
                    results[code] = p
                    sub_count += 1
            except Exception as e:
                log.error("Error generating sub-profile for %s: %s", code, e)
                errors.append((code, str(e)))
        log.info("Generated %d sub-dataset profiles", sub_count)

        if errors:
            log.warning("%d errors during generation", len(errors))
            for code, err in errors[:10]:
                log.warning("  %s: %s", code, err)
        return results


# ---------------------------------------------------------------------------
# Output & stats
# ---------------------------------------------------------------------------

def write_profiles(profiles: dict, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    for code, profile in profiles.items():
        path = output_dir / f"{code}.json"
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)
    log.info("Wrote %d profiles to %s/", len(profiles), output_dir)

    # Write index file for the preview UI
    index = []
    for code, p in sorted(profiles.items()):
        sn_charts = [c['chart_type'] for c in p['views']['snapshot'].get('charts', [])]
        tl_avail = p['views']['timeline'].get('available', False)
        index.append({
            "code": code,
            "name": p.get('matrix_name', ''),
            "archetype": p.get('archetype', ''),
            "dim_count": p.get('dim_count', 0),
            "snapshot_charts": sn_charts,
            "timeline": tl_avail,
            "warnings": len(p.get('warnings', [])),
        })
    index_path = output_dir / "_index.json"
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False)
    log.info("Wrote index (%d entries) to %s", len(index), index_path)


def print_stats(profiles: dict):
    total = len(profiles)
    timeline_available = sum(1 for p in profiles.values()
                            if p['views']['timeline'].get('available'))
    snapshot_charts = {}
    timeline_charts = {}
    control_types = {}
    warning_types = {}

    for p in profiles.values():
        # Snapshot chart types
        for c in p['views']['snapshot'].get('charts', []):
            ct = c['chart_type']
            snapshot_charts[ct] = snapshot_charts.get(ct, 0) + 1
        # Timeline chart types
        if p['views']['timeline'].get('available'):
            for c in p['views']['timeline'].get('charts', []):
                ct = c['chart_type']
                timeline_charts[ct] = timeline_charts.get(ct, 0) + 1
        # Controls
        for view in ('timeline', 'snapshot'):
            for ctrl in p['views'][view].get('controls', []):
                ct = ctrl['type']
                control_types[ct] = control_types.get(ct, 0) + 1
        # Warnings
        for w in p.get('warnings', []):
            wt = w['type']
            warning_types[wt] = warning_types.get(wt, 0) + 1

    print(f"\n{'='*60}")
    print(f"VIEW PROFILE STATISTICS")
    print(f"{'='*60}")
    print(f"Total datasets: {total}")
    print(f"Timeline available: {timeline_available} ({timeline_available/total:.0%})")
    print(f"Snapshot available: {total} (100%)")

    print(f"\nSnapshot chart distribution:")
    for ct, count in sorted(snapshot_charts.items(), key=lambda x: -x[1]):
        print(f"  {ct:25s} {count:5d} ({count/total:.0%})")

    print(f"\nTimeline chart distribution:")
    for ct, count in sorted(timeline_charts.items(), key=lambda x: -x[1]):
        print(f"  {ct:25s} {count:5d}")

    print(f"\nControl type distribution:")
    for ct, count in sorted(control_types.items(), key=lambda x: -x[1]):
        print(f"  {ct:25s} {count:5d}")

    print(f"\nWarning distribution:")
    for wt, count in sorted(warning_types.items(), key=lambda x: -x[1]):
        print(f"  {wt:25s} {count:5d} ({count/total:.0%})")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate view profiles for INS TEMPO datasets")
    parser.add_argument("--matrix", type=str, help="Generate for a single dataset")
    parser.add_argument("--output", type=str, default=str(OUTPUT_DIR), help="Output directory")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")

    if not DB_PATH.exists():
        log.error("Database not found: %s", DB_PATH)
        sys.exit(1)

    gen = ProfileGenerator(DB_PATH, debug=args.debug)

    try:
        if args.matrix:
            profile = gen.generate_profile(args.matrix)
            if not profile and args.matrix in gen.split_matrices:
                profile = gen.generate_sub_profile(args.matrix)
            if profile:
                out_dir = Path(args.output)
                out_dir.mkdir(parents=True, exist_ok=True)
                path = out_dir / f"{args.matrix}.json"
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(profile, f, indent=2, ensure_ascii=False)
                print(json.dumps(profile, indent=2, ensure_ascii=False))
                log.info("Wrote %s", path)
            else:
                log.error("No profile generated for %s", args.matrix)
                sys.exit(1)
        else:
            profiles = gen.generate_all()
            write_profiles(profiles, Path(args.output))
            print_stats(profiles)
    finally:
        gen.close()


if __name__ == "__main__":
    main()
