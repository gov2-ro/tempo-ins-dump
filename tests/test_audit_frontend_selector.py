"""PKG-FRONTEND selector rules: C07 (choropleth needs a mappable geo level) and
E6 (a TIME_PERIOD dim with several options implies time)."""
from app.services.chart_selector import _eligible, build_signature, select_charts


def _profile(**kw):
    p = {'has_time': True, 'has_geo': True, 'geo_levels': '["county"]', 'dim_count': 3}
    p.update(kw)
    return p


def _dims(geo_n=42, time_n=10):
    return [
        {'dim_column_name': 'REF_AREA', 'dim_type': 'geo', 'option_count': geo_n},
        {'dim_column_name': 'TIME_PERIOD', 'dim_type': 'time', 'option_count': time_n},
    ]


def test_choropleth_needs_county_region_or_macroregion():
    for levels, ok in ((['county'], True), (['region'], True), (['macroregion'], True),
                       (['national', 'unknown'], False), (['unknown'], False),
                       (['county', 'locality', 'national'], True), (['locality'], False)):
        sig = build_signature(_profile(geo_levels=levels), _dims(), {'geo_county_count': 40})
        assert _eligible('choropleth', sig) is ok, levels


def test_non_romanian_geography_is_never_ranked_as_choropleth():
    sig = build_signature(_profile(geo_levels='["national", "unknown"]'), _dims(geo_n=30),
                          {'geo_county_count': 0})
    assert all(r['chart_type'] != 'choropleth' for r in select_charts(sig))


def test_time_period_dim_implies_has_time():
    sig = build_signature(_profile(has_time=False, geo_levels='["county"]'), _dims(time_n=29))
    assert sig['has_time'] is True
    assert sig['time_points'] == 29


def test_single_period_dim_stays_snapshot():
    sig = build_signature(_profile(has_time=False), _dims(time_n=1))
    assert sig['has_time'] is False


def test_profiled_time_points_win_over_option_count():
    sig = build_signature(_profile(has_time=False), _dims(time_n=29), {'time_year_count': 12})
    assert sig['has_time'] is True and sig['time_points'] == 12
