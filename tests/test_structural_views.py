"""Category × category heatmap tiles open as bars and list only honest views."""
from app.services.dashboard_composer import compose_dashboard


def _dim(col, dtype, labels):
    return {'dim_column_name': col, 'dim_label': col, 'dim_type': dtype,
            'option_count': len(labels),
            'options': [{'label': l, 'sdmx_value': l.strip()} for l in labels]}


BREAKDOWN = _dim('BRK', 'indicator', ['Total', 'Masculin', 'Feminin', 'Urban', 'Rural',
                                      '18-24 ani', '25-34 ani', 'Superior', 'Mediu'])
RATES = _dim('RATA', 'indicator', ['Rata formala sau non-formala', 'Rata formala',
                                   'Rata non-formala'])
ONE = _dim('PONDERE', 'indicator', ['Ponderea participantilor'])
TIME = _dim('TIME_PERIOD', 'time', ['Anul 2022'])


def _actual(*dims):
    return {d['dim_column_name']: {o['sdmx_value'] for o in d['options']} for d in dims}


def _compose(series, unit, measure, ranked_extra=()):
    dims = [BREAKDOWN, series, TIME]
    ranked = [*ranked_extra,
              {'chart_type': 'heatmap', 'score': 0.8,
               'roles': {'x_axis': 'BRK', 'series': series['dim_column_name']}}]
    sig = {'primary_unit_type': unit, '_measure': measure, 'time_points': 1}
    return compose_dashboard(sig, ranked, dims, actual_values=_actual(*dims))


def _tile(comp, chart_id):
    return next(c for c in comp['charts'] if c['id'] == chart_id)


def test_rates_open_as_bars_and_never_stack():
    tile = _tile(_compose(RATES, 'percentage', 'non_additive'), 'heatmap')
    assert tile['chart_type'] == 'heatmap'          # layout stays full-width
    assert tile['default_view'] == 'bars'
    assert tile['views'] == ['bars', 'grouped', 'heatmap']


SEX = _dim('SEX', 'gender', ['Total', 'Masculin', 'Feminin'])


def test_counts_by_sex_may_stack():
    tile = _tile(_compose(SEX, 'count', 'additive'), 'heatmap')
    assert tile['views'] == ['bars', 'grouped', 'stacked', 'heatmap']


def test_unverified_flat_series_never_stacks():
    # AED103A: "Formala" sits inside "Formala sau non-formala" with no
    # indentation; the profiler calls that flat. Only a verified partition stacks.
    tile = _tile(_compose(RATES, 'count', 'additive'), 'heatmap')
    assert 'stacked' not in tile['views']
    dims = [BREAKDOWN, RATES, TIME]
    ranked = [{'chart_type': 'heatmap', 'score': 0.8,
               'roles': {'x_axis': 'BRK', 'series': 'RATA'}}]
    comp = compose_dashboard({'primary_unit_type': 'count', '_measure': 'additive'},
                             ranked, dims, actual_values=_actual(*dims),
                             struct={'RATA': {'additive': True, 'n_levels': 1}})
    assert 'stacked' in _tile(comp, 'heatmap')['views']


def test_hierarchical_series_never_stacks():
    nested = _dim('RATA', 'indicator', ['Cheltuieli - total', '  Hrana', '  Locuinta'])
    tile = _tile(_compose(nested, 'count', 'additive'), 'heatmap')
    assert 'stacked' not in tile['views']


def test_wider_dim_becomes_the_bar_categories():
    dims = [BREAKDOWN, RATES, TIME]
    ranked = [{'chart_type': 'heatmap', 'score': 0.8,
               'roles': {'x_axis': 'RATA', 'series': 'BRK'}}]
    comp = compose_dashboard({'primary_unit_type': 'percentage', '_measure': 'non_additive'},
                             ranked, dims, actual_values=_actual(*dims))
    tile = _tile(comp, 'heatmap')
    assert (tile['roles']['x_axis'], tile['roles']['series']) == ('BRK', 'RATA')
    assert tile['views'] == ['bars', 'grouped', 'heatmap']    # 3 rates as series


def test_one_row_heatmap_becomes_bars():
    comp = _compose(ONE, 'percentage', 'non_additive')
    tile = _tile(comp, 'heatmap')
    assert tile['chart_type'] == 'horizontal_bar' and not tile.get('views')
    assert tile['roles']['series'] is None


def test_one_row_heatmap_is_dropped_when_bars_already_show_it():
    ranking = {'chart_type': 'horizontal_bar', 'score': 0.9, 'roles': {'x_axis': 'BRK'}}
    comp = _compose(ONE, 'percentage', 'non_additive', [ranking])
    assert [c['id'] for c in comp['charts']].count('heatmap') == 0


def test_default_view_avoids_repeating_the_ranking_bars():
    ranking = {'chart_type': 'horizontal_bar', 'score': 0.9, 'roles': {'x_axis': 'BRK'}}
    tile = _tile(_compose(RATES, 'percentage', 'non_additive', [ranking]), 'heatmap')
    assert tile['default_view'] == 'grouped'
