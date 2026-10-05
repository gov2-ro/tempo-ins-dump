"""FIX-01 phase 2: one SDMX code registry for DSD, data and keys.

Synthetic data only. The DSD is checked with a real XML parser plus a small
SDMX 2.1 structure validator (element names/namespaces, child order, required
children, ID syntax, reference resolution). No SDMX library is installed in the
project environment, and the official XSDs are not vendored, so this stands in
for schema validation.
"""
import re
import xml.etree.ElementTree as ET

import duckdb
import pytest

from fix01_corpus import make_client

NS = {
    "m": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "c": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
    "g": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic",
}
ID_RE = re.compile(r"^[A-Za-z0-9_@$\-]+$")


def q(p, n):
    return f"{{{NS[p]}}}{n}"


# --------------------------------------------------------------------------
# Synthetic corpus
# --------------------------------------------------------------------------
LONG_A = "Activitati de servicii administrative si activitati de suport " \
         "pentru intretinerea cladirilor - varianta A"
LONG_B = LONG_A[:-1] + "B"
CATS = ["Total", "O'Brien & <Co>", 'Quote "x" and Åş', "A B", "A_B",
        "A/B", "a; b (c) [d]", LONG_A, LONG_B, "Ctl\x01char"]
MONTHS = ["2020-01", "2020-02", "2020-03", "Luna aprilie 2020"]


def _syn_rows():
    rows = []
    for i, cat in enumerate(CATS):
        for t, per in enumerate(MONTHS):
            rows.append((cat, f"opt {i:04d}", per, float(i * 10 + t)))
    # values only present in data, absent from the metadata options
    rows.append(("Only in data", "opt 0599", "2020-01", 99.0))
    return rows


def _write_parquet(path, cols, rows, types):
    c = duckdb.connect()
    c.execute("CREATE TABLE t (" + ", ".join(f'"{n}" {t}' for n, t in zip(cols, types)) + ")")
    c.executemany(f"INSERT INTO t VALUES ({', '.join('?' for _ in cols)})", rows)
    c.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    c.close()


def add_datasets(corpus):
    pq = corpus / "parquet"
    # SYN1: canonical file, metadata carries a STALE column name for CAT.
    _write_parquet(pq / "SYN1.parquet", ["CAT", "AREA", "TIME_PERIOD", "OBS_VALUE"],
                   _syn_rows(), ["VARCHAR"] * 3 + ["DOUBLE"])
    # LEG1: legacy-shaped file (v2 column names, label-string values).
    _write_parquet(pq / "LEG1.parquet", ["cat_nom_id", "ani_nom_id", "value"],
                   [("Total", "Anul 2020", 1.0), ("Masculin", "Anul 2020", 2.0),
                    ("Total", "Anul 2021", 3.0)], ["VARCHAR", "VARCHAR", "DOUBLE"])
    db = duckdb.connect(str(corpus / "metadata.duckdb"))
    db.execute("""CREATE TABLE sdmx_codes (nom_item_id INTEGER, dim_type VARCHAR,
                  sdmx_value VARCHAR, display_label_ro VARCHAR,
                  display_label_en VARCHAR, standard_code VARCHAR, source VARCHAR)""")
    for code, name in (("SYN1", "Synthetic <&> dataset"), ("LEG1", "Legacy")):
        db.execute("INSERT INTO matrices (matrix_code, matrix_name, matrix_name_en, row_count)"
                   " VALUES (?, ?, ?, 10)", [code, name, name + " en"])
        db.execute("INSERT INTO matrix_profiles VALUES (?, 'count', 'x', 2020, 2021)", [code])
    db.execute("INSERT INTO dimensions VALUES (900, 'SYN1', 1, 'Categorie', 'cat_nom_id', 10)")
    db.execute("INSERT INTO dimensions VALUES (901, 'SYN1', 2, 'Zona', 'AREA', 600)")
    db.execute("INSERT INTO dimensions VALUES (902, 'SYN1', 3, 'Luni', 'TIME_PERIOD', 4)")
    db.execute("INSERT INTO sdmx_column_map (matrix_code, old_column_name, sdmx_column_name)"
               " VALUES ('SYN1', 'cat_nom_id', 'CAT')")
    nid = 1000
    for i, cat in enumerate(CATS):           # metadata labels: indented, no sdmx_codes row
        nid += 1
        db.execute("INSERT INTO dimension_options (dimension_id, nom_item_id, option_label)"
                   " VALUES (900, ?, ?)", [nid, "  " + cat if i % 2 else cat])
    for i in range(600):                      # > 500 options, with sdmx_codes labels
        nid += 1
        db.execute("INSERT INTO dimension_options (dimension_id, nom_item_id, option_label)"
                   " VALUES (901, ?, ?)", [nid, f"opt {i:04d}"])
        db.execute("INSERT INTO sdmx_codes VALUES (?, 'x', ?, ?, ?, NULL, 'parsed')",
                   [nid, f"opt {i:04d}", f"Optiunea {i}", f"Option {i}"])
    # LEG1 metadata uses SDMX names; the file uses *_nom_id (legacy).
    db.execute("INSERT INTO dimensions VALUES (910, 'LEG1', 1, 'Categorie', 'CAT', 2)")
    db.execute("INSERT INTO dimensions VALUES (911, 'LEG1', 2, 'Ani', 'TIME_PERIOD', 2)")
    db.execute("INSERT INTO sdmx_column_map (matrix_code, old_column_name, sdmx_column_name)"
               " VALUES ('LEG1', 'cat_nom_id', 'CAT'), ('LEG1', 'ani_nom_id', 'TIME_PERIOD'),"
               " ('LEG1', 'value', 'OBS_VALUE')")
    db.execute("INSERT INTO dimension_options (dimension_id, nom_item_id, option_label)"
               " VALUES (910, 1, 'Total'), (910, 2, 'Masculin')")
    db.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    c = make_client(tmp_path, monkeypatch)
    add_datasets(tmp_path / "corpus")
    return c


# --------------------------------------------------------------------------
# SDMX 2.1 structure validation (stand-in for XSD validation)
# --------------------------------------------------------------------------
def kids(el):
    return [(ch.tag, ch) for ch in el]


def tags(el):
    return [t for t, _ in kids(el)]


def check_order(el, allowed_order):
    """Children must appear in the sequence given by allowed_order."""
    idx = [allowed_order.index(t) for t in tags(el)]
    assert idx == sorted(idx), f"{el.tag}: bad child order {tags(el)}"


def check_name(el):
    names = [ch for ch in el if ch.tag == q("c", "Name")]
    assert names, f"{el.tag} lacks common:Name"
    for n in names:
        assert n.get("{http://www.w3.org/XML/1998/namespace}lang")
        assert (n.text or "").strip()


def check_header(root):
    h = root[0]
    assert h.tag == q("m", "Header")
    assert tags(h)[:4] == [q("m", "ID"), q("m", "Test"), q("m", "Prepared"), q("m", "Sender")]
    assert h.find("m:Sender", NS).get("id")


def validate_dsd(xml_bytes):
    """Parse + structurally validate; returns {dim_id: [code ids] | None, ...}."""
    root = ET.fromstring(xml_bytes)
    assert root.tag == q("m", "Structure")
    check_header(root)
    st = root.find("m:Structures", NS)
    check_order(st, [q("s", "Codelists"), q("s", "Concepts"), q("s", "DataStructures")])

    codelists = {}
    for cl in st.find("s:Codelists", NS):
        assert cl.tag == q("s", "Codelist")
        assert ID_RE.match(cl.get("id")) and cl.get("agencyID") and cl.get("version")
        check_order(cl, [q("c", "Name"), q("s", "Code")])
        check_name(cl)
        ids = []
        for code in cl.findall("s:Code", NS):
            assert ID_RE.match(code.get("id")), code.get("id")
            check_name(code)
            ids.append(code.get("id"))
        assert len(ids) == len(set(ids)), f"duplicate code IDs in {cl.get('id')}"
        codelists[cl.get("id")] = ids

    concepts = {}
    for cs in st.find("s:Concepts", NS):
        assert cs.tag == q("s", "ConceptScheme")
        check_name(cs)
        concepts[cs.get("id")] = {c.get("id") for c in cs.findall("s:Concept", NS)}
        for c in cs.findall("s:Concept", NS):
            assert ID_RE.match(c.get("id"))
            check_name(c)

    dsd = st.find("s:DataStructures/s:DataStructure", NS)
    check_name(dsd)
    comps = dsd.find("s:DataStructureComponents", NS)
    check_order(comps, [q("s", "DimensionList"), q("s", "AttributeList"), q("s", "MeasureList")])
    dl = comps.find("s:DimensionList", NS)
    assert dl.get("id") == "DimensionDescriptor"
    dim_tags = tags(dl)
    td = [t for t in dim_tags if t == q("s", "TimeDimension")]
    assert len(td) <= 1 and (not td or dim_tags[-1] == q("s", "TimeDimension"))
    assert all(t in (q("s", "Dimension"), q("s", "TimeDimension")) for t in dim_tags)

    def check_concept_ref(el):
        ref = el.find("s:ConceptIdentity/Ref", NS)
        assert ref is not None and ref.get("class") == "Concept"
        assert ref.get("id") in concepts[ref.get("maintainableParentID")]

    dims = {}
    positions = []
    for d in dl:
        assert ID_RE.match(d.get("id"))
        positions.append(int(d.get("position")))
        check_order(d, [q("s", "ConceptIdentity"), q("s", "LocalRepresentation")])
        check_concept_ref(d)
        lr = d.find("s:LocalRepresentation", NS)
        if d.tag == q("s", "TimeDimension"):
            tf = lr.find("s:TextFormat", NS)
            assert tf is not None and tf.get("textType") == "ObservationalTimePeriod"
            assert lr.find("s:Enumeration", NS) is None
            dims[d.get("id")] = None
        else:
            ref = lr.find("s:Enumeration/Ref", NS)
            assert ref is not None and ref.get("class") == "Codelist"
            assert ref.get("id") in codelists, "dimension references undeclared codelist"
            dims[d.get("id")] = codelists[ref.get("id")]
    assert sorted(positions) == list(range(1, len(positions) + 1))
    pm = comps.find("s:MeasureList/s:PrimaryMeasure", NS)
    assert pm.get("id") == "OBS_VALUE"
    check_concept_ref(pm)
    return dims


def parse_data(xml_bytes):
    root = ET.fromstring(xml_bytes)
    assert root.tag == q("m", "GenericData")
    check_header(root)
    struct = root.find("m:Header/m:Structure", NS)
    assert struct.get("dimensionAtObservation") == "AllDimensions"
    assert struct.find("c:Structure/Ref", NS).get("class") == "DataStructure"
    ds = root.find("m:DataSet", NS)
    out = []
    for obs in ds.findall("g:Obs", NS):
        check_order(obs, [q("g", "ObsKey"), q("g", "ObsValue")])
        key = [(v.get("id"), v.get("value")) for v in obs.find("g:ObsKey", NS)]
        out.append((key, obs.find("g:ObsValue", NS).get("value")))
    return out


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def test_dsd_is_valid_and_complete(client):
    r = client.get("/sdmx/2.1/datastructure/INS/SYN1/1.0")
    assert r.status_code == 200
    dims = validate_dsd(r.content)
    assert list(dims) == ["CAT", "AREA", "TIME_PERIOD"]   # stale name -> canonical
    assert dims["TIME_PERIOD"] is None                    # time dimension, no codelist
    assert len(dims["AREA"]) == 600                       # no 500 cutoff
    # metadata options + the value that exists only in the data
    assert len(dims["CAT"]) == len(CATS) + 1


def test_xml_special_chars_and_names_roundtrip(client):
    r = client.get("/sdmx/2.1/datastructure/INS/SYN1/1.0")
    root = ET.fromstring(r.content)
    name = root.find(".//s:DataStructure/c:Name", NS).text
    assert name == "Synthetic <&> dataset"
    labels = {n.text for n in root.iter(q("c", "Name"))}
    assert "O'Brien & <Co>" in labels and 'Quote "x" and Åş' in labels
    assert "Optiunea 7" in labels and "Option 7" in labels      # RO + EN labels
    assert not any("\x01" in (t or "") for t in labels)          # illegal char stripped
    assert b"&lt;Co&gt;" in r.content


def test_code_ids_have_no_collisions_and_are_not_truncated_labels(client):
    dims = validate_dsd(client.get("/sdmx/2.1/datastructure/INS/SYN1/1.0").content)
    cat = dims["CAT"]
    assert len(set(cat)) == len(cat)
    # the two long labels share a >50-char prefix but get distinct IDs
    longs = [c for c in cat if c.startswith("Activitati_de_servicii")]
    assert len(longs) == 2 and longs[0] != longs[1]
    # "A B", "A_B" and "A/B" stay distinct
    assert {"A_B"} <= set(cat) and len([c for c in cat if c.startswith("A_B")]) == 3
    assert "Total" in cat           # plain values are their own code


def test_emitted_values_are_in_declared_codelists(client):
    dims = validate_dsd(client.get("/sdmx/2.1/datastructure/INS/SYN1/1.0").content)
    obs = parse_data(client.get("/sdmx/2.1/data/INS,SYN1").content)
    assert len(obs) == len(CATS) * len(MONTHS) + 1
    for key, _ in obs:
        assert [k for k, _ in key] == list(dims)            # DSD order and ids
        for dim, value in key:
            if dims[dim] is not None:
                assert value in dims[dim], (dim, value)
    # periods are normalized (the 'Luna aprilie 2020' label becomes 2020-04)
    periods = {dict(k)["TIME_PERIOD"] for k, _ in obs}
    assert periods == {"2020-01", "2020-02", "2020-03", "2020-04"}


def test_parse_dsd_then_query_emitted_key_returns_matching_rows(client):
    dims = validate_dsd(client.get("/sdmx/2.1/datastructure/INS/SYN1/1.0").content)
    all_obs = parse_data(client.get("/sdmx/2.1/data/INS,SYN1").content)
    # every emitted category code, used as a canonical key, returns exactly its rows
    for code in dims["CAT"]:
        expected = [o for o in all_obs if dict(o[0])["CAT"] == code]
        got = parse_data(client.get(f"/sdmx/2.1/data/INS,SYN1/{code}..").content)
        assert sorted(got) == sorted(expected) and expected, code
    # multi-dimension key incl. a normalized period and '+' OR
    code = next(c for c in dims["CAT"] if c.startswith("Quote"))
    got = parse_data(client.get(f"/sdmx/2.1/data/INS,SYN1/{code}+Total..2020-04").content)
    assert len(got) == 2 and {dict(k)["TIME_PERIOD"] for k, _ in got} == {"2020-04"}
    # the stored (non-ISO) label also reaches the same rows
    got2 = parse_data(client.get(
        f"/sdmx/2.1/data/INS,SYN1/{code}+Total..Luna aprilie 2020").content)
    assert sorted(got2) == sorted(got)


def test_observation_values_match_stored_data(client):
    obs = parse_data(client.get("/sdmx/2.1/data/INS,SYN1/Total..2020-02").content)
    assert obs and obs[0][1] == "1.0"


def test_period_filters_use_the_stale_metadata_dataset(client):
    obs = parse_data(client.get(
        "/sdmx/2.1/data/INS,SYN1?startPeriod=2020-02&endPeriod=2020-03").content)
    assert {dict(k)["TIME_PERIOD"] for k, _ in obs} == {"2020-02", "2020-03"}
    last = parse_data(client.get("/sdmx/2.1/data/INS,SYN1?lastNObservations=1").content)
    assert last and len({dict(k)["TIME_PERIOD"] for k, _ in last}) == 1


def test_legacy_label_keys_still_work_when_unambiguous(client):
    # raw stored values (the pre-registry key form)
    obs = parse_data(client.get("/sdmx/2.1/data/INS,SYN1/Total").content)
    assert len(obs) == len(MONTHS)
    raw = parse_data(client.get("/sdmx/2.1/data/INS,SYN1/O'Brien & <Co>").content)
    canon_code = next(dict(k)["CAT"] for k, _ in raw)
    assert canon_code != "O'Brien & <Co>"
    via_code = parse_data(client.get(f"/sdmx/2.1/data/INS,SYN1/{canon_code}").content)
    assert sorted(raw) == sorted(via_code) and len(raw) == len(MONTHS)
    # unknown value: no rows, not an error
    assert parse_data(client.get("/sdmx/2.1/data/INS,SYN1/Nope").content) == []


def test_ambiguous_legacy_key_is_400(client, tmp_path):
    # Add a data value whose RAW text equals the canonical code of another value.
    from app.services.sdmx_registry import code_id
    clash = code_id("A B")                                  # e.g. 'A_B_<hash>'
    import app.config as config
    pq = config.CORPUS_DIR / "parquet" / "AMB1.parquet"
    _write_parquet(pq, ["CAT", "TIME_PERIOD", "OBS_VALUE"],
                   [("A B", "2020", 1.0), (clash, "2020", 2.0), ("Total", "2020", 3.0)],
                   ["VARCHAR", "VARCHAR", "DOUBLE"])
    db = duckdb.connect(str(config.CORPUS_DIR / "metadata.duckdb"))
    db.execute("INSERT INTO matrices (matrix_code, matrix_name, matrix_name_en, row_count)"
               " VALUES ('AMB1', 'amb', 'amb', 3)")
    db.execute("INSERT INTO dimensions VALUES (950, 'AMB1', 1, 'Cat', 'CAT', 3)")
    db.execute("INSERT INTO dimensions VALUES (951, 'AMB1', 2, 'T', 'TIME_PERIOD', 1)")
    db.close()
    r = client.get(f"/sdmx/2.1/data/INS,AMB1/{clash}")
    assert r.status_code == 400 and "Ambiguous" in r.json()["detail"]
    # other segments are unaffected and the DSD still has unique codes
    assert client.get("/sdmx/2.1/data/INS,AMB1/Total").status_code == 200
    dims = validate_dsd(client.get("/sdmx/2.1/datastructure/INS/AMB1/1.0").content)
    assert len(set(dims["CAT"])) == 3


def test_legacy_shaped_parquet_is_consistent(client):
    dims = validate_dsd(client.get("/sdmx/2.1/datastructure/INS/LEG1/1.0").content)
    assert list(dims) == ["CAT", "TIME_PERIOD"]
    obs = parse_data(client.get("/sdmx/2.1/data/INS,LEG1").content)
    assert len(obs) == 3
    for key, _ in obs:
        assert dict(key)["CAT"] in dims["CAT"]
    assert {dict(k)["TIME_PERIOD"] for k, _ in obs} == {"2020", "2021"}
    got = parse_data(client.get("/sdmx/2.1/data/INS,LEG1/Total.2021").content)
    assert len(got) == 1 and got[0][1] == "3.0"
    # period bounds on the legacy time labels: normalized values are not matched
    # against raw labels (documented: legacy labels never match a bound)
    assert client.get("/sdmx/2.1/data/INS,LEG1?startPeriod=2020").status_code == 200


def test_dataflow_is_valid(client):
    r = client.get("/sdmx/2.1/dataflow/INS/SYN1/1.0")
    root = ET.fromstring(r.content)
    check_header(root)
    df = root.find("m:Structures/s:Dataflows/s:Dataflow", NS)
    assert df.get("id") == "SYN1"
    check_name(df)
    assert df.find("s:Structure/Ref", NS).get("class") == "DataStructure"
    assert df.find("c:Name", NS).text == "Synthetic <&> dataset"


def test_registry_pure_functions():
    from app.services.sdmx_registry import code_id, normalize_period
    assert code_id("Total") == "Total"
    assert code_id("a b") == code_id("a b") != code_id("a_b")
    assert ID_RE.match(code_id("Ţară / judeţ 'x'"))
    assert code_id("x" * 200) != code_id("x" * 201)
    assert normalize_period("Luna martie 2004") == "2004-03"
    assert normalize_period("Trimestrul II 2020") == "2020-Q2"
    assert normalize_period("2020-Q1") == "2020-Q1" and normalize_period("2020") == "2020"


# --------------------------------------------------------------------------
# Real corpus, read-only (skipped on a clean checkout)
# --------------------------------------------------------------------------
@pytest.mark.corpus
@pytest.mark.parametrize("flow", ["AMG157G", "ART124A"])
def test_real_corpus_roundtrip_has_no_out_of_codelist_values(flow):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    dims = validate_dsd(c.get(f"/sdmx/2.1/datastructure/INS/{flow}/1.0").content)
    obs = parse_data(c.get(f"/sdmx/2.1/data/INS,{flow}?lastNObservations=3").content)
    assert obs
    bad = [(d, v) for key, _ in obs for d, v in key
           if dims[d] is not None and v not in dims[d]]
    assert bad == []
    # round trip: the first emitted observation's enumerated codes as a key
    key = ".".join(v if dims[d] is not None else "" for d, v in obs[0][0])
    again = parse_data(c.get(f"/sdmx/2.1/data/INS,{flow}/{key}?lastNObservations=3").content)
    assert obs[0] in again
