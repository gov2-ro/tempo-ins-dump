"""Generate chart configuration based on dataset archetype and dimensions."""
import json


def build_chart_config(profile: dict, dimensions: list) -> dict:
    """Build chart configuration from matrix_profiles + dimensions metadata.

    Args:
        profile: Row from matrix_profiles table
        dimensions: List of dimension dicts with dim_type, dim_column_name, etc.

    Returns:
        Chart config dict for the frontend
    """
    archetype = profile.get('archetype', 'time_series')

    time_dim = _find_dim(dimensions, 'time')
    geo_dim = _find_dim(dimensions, 'geo')
    gender_dim = _find_dim(dimensions, 'gender')
    age_dim = _find_dim(dimensions, 'age')
    residence_dim = _find_dim(dimensions, 'residence')
    unit_dim = _find_dim(dimensions, 'unit')

    # Indicator dims = everything that's not time/geo/gender/age/residence/unit
    indicator_dims = [d for d in dimensions if d.get('dim_type') == 'indicator']

    # Parse unit_types from profile (stored as JSON string)
    unit_types_raw = profile.get('unit_types', '[]')
    if isinstance(unit_types_raw, str):
        try:
            unit_types = json.loads(unit_types_raw)
        except (json.JSONDecodeError, TypeError):
            unit_types = []
    else:
        unit_types = unit_types_raw or []

    multi_unit = len(unit_types) > 1

    config = {
        'archetype': archetype,
        'multi_unit': multi_unit,
        'unit_types': unit_types,
        'primary_unit_type': profile.get('primary_unit_type', 'count'),
        'supports': ['table'],  # All archetypes support table view
    }

    if archetype == 'geo_time':
        # For line chart fallback, use geo as series dimension
        # If there are also indicator dims, prefer geo (more meaningful on map)
        series_dim = geo_dim or (indicator_dims[0] if indicator_dims else None)
        config.update({
            'primary_chart': 'choropleth',
            'secondary_chart': 'line',
            'geo_dim': geo_dim['dim_column_name'] if geo_dim else None,
            'time_dim': time_dim['dim_column_name'] if time_dim else None,
            'series_dim': series_dim['dim_column_name'] if series_dim else None,
            'default_time': 'latest',
            'default_geo_level': 'county',
            'supports': ['choropleth', 'line', 'bar', 'table'],
        })
        # Parse geo_levels
        geo_levels_raw = profile.get('geo_levels', '[]')
        if isinstance(geo_levels_raw, str):
            try:
                config['geo_levels'] = json.loads(geo_levels_raw)
            except (json.JSONDecodeError, TypeError):
                config['geo_levels'] = []
        else:
            config['geo_levels'] = geo_levels_raw or []

    elif archetype == 'demographic':
        config.update({
            'primary_chart': 'grouped_bar',
            'time_dim': time_dim['dim_column_name'] if time_dim else None,
            'gender_dim': gender_dim['dim_column_name'] if gender_dim else None,
            'age_dim': age_dim['dim_column_name'] if age_dim else None,
            'supports': ['grouped_bar', 'line', 'table'],
        })

    elif archetype == 'time_residence':
        config.update({
            'primary_chart': 'line',
            'time_dim': time_dim['dim_column_name'] if time_dim else None,
            'series_dim': residence_dim['dim_column_name'] if residence_dim else None,
            'supports': ['line', 'bar', 'table'],
        })

    else:  # time_series (default)
        series_dim = indicator_dims[0] if indicator_dims else None
        config.update({
            'primary_chart': 'line',
            'time_dim': time_dim['dim_column_name'] if time_dim else None,
            'series_dim': series_dim['dim_column_name'] if series_dim else None,
            'default_series_limit': 5,
            'supports': ['line', 'area', 'bar', 'table'],
        })

    return config


def _find_dim(dimensions: list, dim_type: str) -> dict | None:
    """Find first dimension matching the given type."""
    for d in dimensions:
        if d.get('dim_type') == dim_type:
            return d
    return None
