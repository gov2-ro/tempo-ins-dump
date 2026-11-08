"""Audit E4: the ranking sentence names its pinned slice, or is withheld.

FOM106E-like datasets have dimensions with no Total and no verified partition,
so the composer holds them at one option. The 'latest' KPI is already withheld
as arbitrary_pin; the "highest value" sentence must follow the same rule.
"""
import itertools

import duckdb

from fix02b_corpus import _write, make_client

COUNTIES = {'Cluj': 30.0, 'Timis': 50.0, 'Iasi': 10.0}


def _add(corpus, code, dims, rows):
    """Add one dataset to the fix02b corpus. dims: [(col, label, dtype, [(opt, parsed)])]."""
    cols = ', '.join(f'{c} VARCHAR' for c, *_ in dims)
    _write(corpus / 'parquet' / f'{code}.parquet', f'{cols}, OBS_VALUE DOUBLE', rows)
    db = duckdb.connect(str(corpus / 'metadata.duckdb'))
    did = db.execute('SELECT max(dimension_id) FROM dimensions').fetchone()[0] + 100
    nid = db.execute('SELECT max(nom_item_id) FROM dimension_options').fetchone()[0] + 100
    db.execute('INSERT INTO matrices (matrix_code, matrix_name, matrix_name_en, row_count, '
               'definitie) VALUES (?, ?, ?, ?, ?)',
               [code, 'Castigul salarial mediu net', 'Average net earnings', len(rows), 'Castig'])
    # an average: the composer pins a dim with no Total instead of summing it
    db.execute("INSERT INTO matrix_profiles VALUES (?, 'currency', 'x', 2023, 2024, '[]')", [code])
    for i, (col, label, dtype, opts) in enumerate(dims, 1):
        did += 1
        db.execute('INSERT INTO dimensions VALUES (?, ?, ?, ?, ?, ?)',
                   [did, code, i, label, col, len(opts)])
        for off, (olabel, parsed) in enumerate(opts):
            nid += 1
            db.execute('INSERT INTO dimension_options VALUES (?, ?, ?, ?, NULL)',
                       [did, nid, olabel, off])
            db.execute('INSERT INTO dimension_options_parsed VALUES '
                       '(?, ?, ?, NULL, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, 0.9)',
                       [nid, dtype, parsed.get('year'), parsed.get('geo_level')])
            db.execute('INSERT INTO sdmx_codes VALUES (?, ?, ?)', [nid, olabel, olabel])
    db.close()


def _client(tmp_path, monkeypatch, n_pinned):
    client = make_client(tmp_path, monkeypatch)
    corpus = tmp_path / 'corpus'
    caen = ('CAEN', 'Activitati CAEN', 'indicator', [('Agricultura', {}), ('Industrie', {})])
    forma = ('FORMA', 'Forma de proprietate', 'indicator', [('Publica', {}), ('Privata', {})])
    geo = ('REF_AREA', 'Judete', 'geo', [(c, {'geo_level': 'county'}) for c in COUNTIES])
    time_ = ('TIME_PERIOD', 'Ani', 'time', [('2023', {'year': 2023}), ('2024', {'year': 2024})])
    extra = [caen, forma][:n_pinned]
    dims = extra + [geo, time_]
    # The first option of every pinned dim carries the county's known value;
    # other options add 100 per step, so a sum would show in the sentence.
    rows = []
    for combo in itertools.product(*[range(len(d[3])) for d in extra]):
        labels = tuple(d[3][k][0] for d, k in zip(extra, combo))
        for year in ('2023', '2024'):
            for county, v in COUNTIES.items():
                rows.append(labels + (county, year, v + 100.0 * sum(combo)))
    _add(corpus, 'RANKX', dims, rows)
    return client


def test_one_pin_is_named_in_the_ranking_sentence(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, 1)
    body = client.get('/api/datasets/RANKX/insights').json()
    # the pin stays withheld from the headline, as before
    assert {'key': 'latest', 'reason': 'arbitrary_pin'}.items() <= next(
        s for s in body['suppressed'] if s['key'] == 'latest').items()
    geo = [s for s in body['sentences'] if 'Timis' in s]
    assert geo == ['Pentru „Agricultura": Timis are cea mai ridicată valoare (50); '
                   'Iasi — cea mai scăzută (10).']
    en = client.get('/api/datasets/RANKX/insights', params={'lang': 'en'}).json()
    assert any(s.startswith('For "Agricultura": Timis has the highest value (50)')
               for s in en['sentences'])


def test_two_pins_withhold_the_ranking(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, 2)
    body = client.get('/api/datasets/RANKX/insights').json()
    assert not any('Timis' in s for s in body['sentences'])
    assert body['notables'] == []
    assert {'key': 'ranking', 'reason': 'arbitrary_pin'}.items() <= next(
        s for s in body['suppressed'] if s['key'] == 'ranking').items()


def test_no_pin_keeps_the_plain_sentence(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, 0)
    body = client.get('/api/datasets/RANKX/insights').json()
    assert 'Timis are cea mai ridicată valoare (50); Iasi — cea mai scăzută (10).' in body['sentences']
