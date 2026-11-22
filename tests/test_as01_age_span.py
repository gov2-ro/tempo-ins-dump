"""AS-01: an age option that spans all the others is pinned as the aggregate row.

Metadata only. The other bands are never summed or compared to the span, so the
rule also holds for rates. The JS mirror is checked in test_static_parity.
"""
import pytest

from app.services.aggregation_policy import (
    decide, spanning_age_option, VALID_TOTAL, UNAVAILABLE)


def opt(label, lo=None, hi=None):
    return {'label': label, 'sdmx_value': label,
            'parsed': {'age_min': lo, 'age_max': hi}}


def dim(col, dtype, options):
    return {'dim_column_name': col, 'dim_type': dtype, 'options': options}


TIME = dim('TIME_PERIOD', 'time', [opt('2024')])
S = opt('15 - 74 ani', 15, 74)
A = opt('15 - 24 ani', 15, 24)
B = opt('25 - 74 ani', 25, 74)


def run(age_opts, unit_type='count', age_type='age', struct=None, **kw):
    dims = [TIME, dim('AGE', age_type, age_opts)]
    eff = {d['dim_column_name']: [(o, o['label']) for o in d['options']] for d in dims}
    return decide(dimensions=dims, effective=eff, group_by=['TIME_PERIOD'],
                  unit_type=unit_type, struct=struct, **kw)


def test_span_over_two_bands_is_pinned():
    d = run([A, S, B])
    assert d.outcome == VALID_TOTAL and d.method == 'aggregate_row'
    assert d.effective_filters == {'AGE': ['15 - 74 ani']}
    assert d.dimensions[-1]['treatment'] == 'pinned_aggregate'


def test_rate_unit_is_pinned_not_summed():
    d = run([A, S, B], unit_type='percent')
    assert d.outcome == VALID_TOTAL and d.method == 'aggregate_row'
    assert d.effective_filters == {'AGE': ['15 - 74 ani']}


def test_two_spanning_candidates_do_not_pin():
    twin = opt('15 - 74 ani (b)', 15, 74)
    assert spanning_age_option(dim('AGE', 'age', [A, S, twin]),
                               [(o, o['label']) for o in (A, S, twin)]) is None
    d = run([A, S, twin])
    assert d.outcome == UNAVAILABLE and d.reason == 'overlapping_levels'


def test_open_ended_band_does_not_pin():
    d = run([opt('15 - 24 ani', 15, 24), opt('15 ani si peste', 15, None), B])
    assert d.outcome == UNAVAILABLE and d.reason == 'overlapping_levels'


def test_unparsed_ages_do_not_pin():
    d = run([opt('x'), opt('y'), opt('z')])
    assert not (d.method == 'aggregate_row')


def test_non_age_dimension_unchanged():
    d = run([A, S, B], age_type='indicator')
    assert not (d.method == 'aggregate_row')


def test_aggregate_value_naming_another_option_wins():
    struct = {'AGE': {'aggregate_value': '25 - 74 ani', 'levels': [],
                      'default_level': None, 'confidence': 'flat'}}
    d = run([A, S, B], struct=struct)
    assert d.effective_filters == {'AGE': ['25 - 74 ani']}


def test_explicit_multi_band_selection_still_overlaps():
    d = run([A, S, B], filters={'AGE': ['15 - 74 ani', '15 - 24 ani']})
    assert d.outcome == UNAVAILABLE and d.reason == 'overlapping_levels'


def test_explicit_single_span_is_a_pinned_aggregate():
    d = run([A, S, B], filters={'AGE': ['15 - 74 ani']})
    assert d.outcome == VALID_TOTAL and d.method == 'aggregate_row'


def test_explicit_single_part_stays_a_slice():
    d = run([A, S, B], filters={'AGE': ['15 - 24 ani']})
    assert d.method == 'single_row'


def test_total_labelled_option_still_wins():
    d = run([opt('Total', 0, 999), S, A, B])
    assert d.effective_filters == {'AGE': ['Total']}


# --- the static engine mirror ---------------------------------------------------

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_JS = """
import { decide } from '%s/app/static/js/engine/policy.js';
const cases = JSON.parse(process.argv[2]);
const out = cases.map(c => {
  const dims = [{dim_column_name: 'TIME_PERIOD', dim_type: 'time', options: [{label: '2024', parsed: {}}]},
                {dim_column_name: 'AGE', dim_type: c.type, options: c.opts}];
  const eff = {};
  for (const d of dims) eff[d.dim_column_name] = d.options.map(o => [o, o.label]);
  const r = decide({dimensions: dims, effective: eff, groupBy: ['TIME_PERIOD'],
                    filters: c.filters, measure: c.measure});
  return [r.outcome, r.reason, r.method, r.filters];
});
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_static_engine_mirrors_the_span_rule(tmp_path):
    def o(label, lo, hi):
        return {'label': label, 'sdmx_value': label, 'parsed': {'age_min': lo, 'age_max': hi}}
    three = [o('15 - 24 ani', 15, 24), o('15 - 74 ani', 15, 74), o('25 - 74 ani', 25, 74)]
    cases = [
        dict(type='age', opts=three, filters={}, measure='additive'),
        dict(type='age', opts=three, filters={}, measure='non_additive'),
        dict(type='age', opts=[three[0], three[1], o('b', 15, 74)], filters={}, measure='additive'),
        dict(type='age', opts=[three[0], o('15 ani +', 15, None), three[2]], filters={},
             measure='additive'),
        dict(type='age', opts=three, filters={'AGE': ['15 - 74 ani']}, measure='additive'),
        dict(type='age', opts=three, filters={'AGE': ['15 - 74 ani', '15 - 24 ani']},
             measure='additive'),
        dict(type='indicator', opts=three, filters={}, measure='additive'),
    ]
    script = tmp_path / 'run.mjs'
    script.write_text(_JS % ROOT)
    r = subprocess.run(['node', str(script), json.dumps(cases)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for c, got in zip(cases, json.loads(r.stdout)):
        dims = [TIME, dim('AGE', c['type'], c['opts'])]
        eff = {d['dim_column_name']: [(x, x['label']) for x in d['options']] for d in dims}
        d = decide(dimensions=dims, effective=eff, group_by=['TIME_PERIOD'],
                   filters=c['filters'], measure=c['measure'], api_mode=True)
        assert got == [d.outcome, d.reason, d.method, d.effective_filters], c
