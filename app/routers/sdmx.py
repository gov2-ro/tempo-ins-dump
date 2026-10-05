"""SDMX 2.1 REST API endpoints for INS TEMPO data.

  GET /sdmx/2.1/data/INS,{flow}/{key}         -> SDMX-ML 2.1 GenericData
  GET /sdmx/2.1/datastructure/INS/{flow}/1.0  -> SDMX-ML 2.1 DataStructure
                                                 (+ codelists, concept scheme)
  GET /sdmx/2.1/dataflow/INS/{flow}/1.0       -> SDMX-ML 2.1 Dataflow

Codes, keys, the DSD and the data all come from one registry
(app/services/sdmx_registry.py). XML is built with ElementTree, never string
formatting. sdmxthon (the Dashboard Generator) only parses XML.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from xml.sax.saxutils import quoteattr

from app.db import get_conn
from app.config import PARQUET_DIR, SDMX_MAX_OBS, EXPORT_BATCH_ROWS as SDMX_BATCH_ROWS
from app.services.request_validation import (
    parse_period_range, period_span_sql, quote_ident, valid_matrix_code)
from app.services.sdmx_registry import build_registry
from app.services.export import try_acquire, busy_error

router = APIRouter()
log = logging.getLogger(__name__)

AGENCY = "INS"
_OBS_MARK = "@@OBS-STREAM@@"

NS = {
    "message": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message",
    "structure": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "common": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
    "generic": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
for _p, _u in NS.items():
    ET.register_namespace(_p, _u)

# Characters not allowed in XML 1.0 documents (would make the output unparseable).
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _q(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def _text(v) -> str:
    return _XML_ILLEGAL.sub("", "" if v is None else str(v))


def _sub(parent, prefix: str, name: str, text=None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, _q(prefix, name), {k: _text(v) for k, v in attrs.items()})
    if text is not None:
        el.text = _text(text)
    return el


def _name(parent, text, lang="ro", tag="Name"):
    el = ET.SubElement(parent, _q("common", tag))
    el.set(XML_LANG, lang)
    el.text = _text(text)
    return el


def _ref(parent, **attrs):
    # SDMX 2.1 Ref elements are unqualified (no namespace).
    return ET.SubElement(parent, "Ref", {k: _text(v) for k, v in attrs.items()})


def _serialize(root: ET.Element) -> Response:
    body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=body, media_type="application/xml")


def _header(root, flow: str):
    h = _sub(root, "message", "Header")
    _sub(h, "message", "ID", flow)
    _sub(h, "message", "Test", "false")
    _sub(h, "message", "Prepared",
         datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
    _sub(h, "message", "Sender", id=AGENCY)
    return h


def _parquet_path(flow: str) -> str | None:
    """Return path to the dataset parquet file."""
    p = PARQUET_DIR / f"{flow}.parquet"
    if p.exists():
        return str(p)
    return None


# ---------------------------------------------------------------------------
# Data endpoint
# ---------------------------------------------------------------------------

@router.get("/2.1/data/{agency_flow:path}")
def get_data(
    agency_flow: str,
    lastNObservations: Optional[int] = Query(None, ge=1, le=10000),
    startPeriod: Optional[str] = Query(None),
    endPeriod: Optional[str] = Query(None),
):
    """SDMX data endpoint.

    URL form: /sdmx/2.1/data/INS,ACC102B/{key}. The key is dot-separated, one
    segment per dimension (canonical: the code IDs of the DSD; legacy: the raw
    stored value when unambiguous).

    4xx responses: 400 malformed/reversed startPeriod/endPeriod, a key with
    more non-empty segments than dimensions, or an ambiguous key segment;
    404 unknown dataset; 422 invalid lastNObservations (must be >= 1).
    See docs/SDMX-API.md.
    """
    if "/" in agency_flow:
        flow_part, key = agency_flow.split("/", 1)
        key = key.rstrip("/")
    else:
        flow_part, key = agency_flow, ""
    flow = flow_part.split(",")[-1].strip()

    # Validate request shape before touching the database.
    if not valid_matrix_code(flow):
        raise HTTPException(404, "Dataset not found")
    start_m, end_m = parse_period_range(startPeriod, endPeriod)

    parquet = _parquet_path(flow)
    if not parquet:
        raise HTTPException(404, f"Dataset {flow} not found")

    # One request-owned cursor on the shared, memory-limited connection.
    conn = get_conn()
    try:
        try:
            reg = build_registry(conn, flow, parquet)
            if reg is not None:
                if not reg.has_data:
                    log.error("sdmx metadata/parquet column mismatch flow=%s", flow)
                    raise HTTPException(500, "Query failed")
                key_filters = reg.parse_key(key, conn, parquet)
        except HTTPException:
            raise
        except Exception:
            log.exception("sdmx registry build failed flow=%s", flow)
            raise HTTPException(500, "Query failed")
        if reg is None:
            raise HTTPException(404, f"No dimensions found for {flow}")

        where_clauses: list[str] = []
        params: list = []
        for col, vals in key_filters.items():
            marks = ", ".join("?" for _ in vals)
            where_clauses.append(f"CAST({quote_ident(col)} AS VARCHAR) IN ({marks})")
            params.extend(vals)

        time_dim = next((d for d in reg.dims if d.is_time), None)
        if time_dim is not None:
            tp = quote_ident(time_dim.file_col)
            first_sql, last_sql = period_span_sql(tp)
            if start_m is not None:
                where_clauses.append(f"({first_sql}) >= ?")
                params.append(start_m)
            if end_m is not None:
                where_clauses.append(f"({last_sql}) <= ?")
                params.append(end_m)
        elif start_m is not None or end_m is not None or lastNObservations:
            raise HTTPException(
                400, "Dataset has no TIME_PERIOD dimension; period parameters "
                     "and lastNObservations are not applicable")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        if lastNObservations and time_dim is not None:
            try:
                time_rows = conn.execute(
                    f"SELECT DISTINCT {tp} FROM read_parquet(?) {where_sql} "
                    f"ORDER BY {tp} DESC LIMIT ?",
                    [str(parquet), *params, int(lastNObservations)],
                ).fetchall()
            except Exception:
                log.exception("sdmx lastN query failed flow=%s", flow)
                raise HTTPException(500, "Query failed")
            if time_rows:
                marks = ", ".join("?" for _ in time_rows)
                clause = f"{tp} IN ({marks})"
                where_sql = (f"{where_sql} AND {clause}" if where_clauses
                             else f"WHERE {clause}")
                params.extend(r[0] for r in time_rows)

        # Complete-or-reject (FIX-04): never a silently capped document.
        try:
            total = conn.execute(
                f"SELECT count(*) FROM read_parquet(?) {where_sql}",
                [str(parquet), *params]).fetchone()[0]
        except Exception:
            log.exception("sdmx count failed flow=%s", flow)
            raise HTTPException(500, "Query failed")
        if total > SDMX_MAX_OBS:
            raise HTTPException(
                413, f"Selection has {total} observations, more than the SDMX "
                     f"limit of {SDMX_MAX_OBS}. Narrow it with a key, "
                     f"startPeriod/endPeriod or lastNObservations, or download "
                     f"CSV (no row limit).")

        # Concurrency slot: non-blocking, before any headers are sent.
        slot = try_acquire("sdmx")
        if slot is None:
            raise busy_error()
        col_select = ", ".join(quote_ident(d.file_col) for d in reg.dims)
        col_select += f", {quote_ident(reg.value_col)}"
        sql = f"SELECT {col_select} FROM read_parquet(?) {where_sql}"
        try:
            cur = conn.execute(sql, [str(parquet), *params])
        except Exception:
            slot()
            log.exception("sdmx data query failed flow=%s", flow)
            raise HTTPException(500, "Query failed")
    except BaseException:
        conn.close()
        raise

    root = ET.Element(_q("message", "GenericData"))
    _header_data(root, flow)
    ds = _sub(root, "message", "DataSet", structureRef=flow, action="Replace")
    ds.text = _OBS_MARK
    head, tail = ET.tostring(root, encoding="utf-8", xml_declaration=True) \
        .decode("utf-8").split(_OBS_MARK)
    gp = "generic"
    head = head.replace("<message:DataSet ",
                        f'<message:DataSet xmlns:generic="{NS["generic"]}" ', 1)

    def stream():
        try:
            yield head
            n = len(reg.dims)
            while True:
                batch = cur.fetchmany(SDMX_BATCH_ROWS)
                if not batch:
                    break
                out = []
                for row in batch:
                    vals = "".join(
                        f"<{gp}:Value id={quoteattr(_text(d.id))} "
                        f"value={quoteattr(_text(reg.encode_dim(d, row[i])))}/>"
                        for i, d in enumerate(reg.dims))
                    ov = row[n]
                    out.append(f"<{gp}:Obs><{gp}:ObsKey>{vals}</{gp}:ObsKey>"
                               f"<{gp}:ObsValue value="
                               f"{quoteattr('' if ov is None else str(ov))}/></{gp}:Obs>")
                yield "".join(out)
            yield tail
        finally:
            slot()
            conn.close()

    return StreamingResponse(
        stream(), media_type="application/xml",
        headers={"X-Export-Matching-Rows": str(total), "X-Export-Complete": "true"})


def _header_data(root, flow: str):
    h = _header(root, flow)
    st = _sub(h, "message", "Structure", structureID=flow,
              dimensionAtObservation="AllDimensions")
    cs = _sub(st, "common", "Structure")
    _ref(cs, agencyID=AGENCY, id=flow, version="1.0",
         **{"class": "DataStructure", "package": "datastructure"})


# ---------------------------------------------------------------------------
# DSD endpoint
# ---------------------------------------------------------------------------

@router.get("/2.1/datastructure/{agency}/{flow}/{version}")
def get_datastructure(agency: str, flow: str, version: str):
    """SDMX-ML 2.1 DataStructure with codelists and a concept scheme."""
    if not valid_matrix_code(flow):
        raise HTTPException(404, "Dataset not found")
    conn = get_conn()
    try:
        parquet = _parquet_path(flow)
        reg = build_registry(conn, flow, parquet)
        if reg is None:
            raise HTTPException(404, f"Dataset {flow} not found")
        matrix = conn.execute(
            "SELECT matrix_name FROM matrices WHERE matrix_code = ?", [flow]
        ).fetchone()
    except HTTPException:
        raise
    except Exception:
        log.exception("sdmx DSD build failed flow=%s", flow)
        raise HTTPException(500, "Query failed")
    finally:
        conn.close()
    name = matrix[0] if matrix and matrix[0] else flow

    root = ET.Element(_q("message", "Structure"))
    _header(root, flow)
    structures = _sub(root, "message", "Structures")

    # Codelists (enumerated dimensions only; TIME_PERIOD is a TimeDimension).
    cls = _sub(structures, "structure", "Codelists")
    for d in reg.dims:
        if d.is_time:
            continue
        cl = _sub(cls, "structure", "Codelist", id=d.codelist_id,
                  version="1.0", agencyID=AGENCY)
        _name(cl, d.label)
        for c in d.codes:
            code = _sub(cl, "structure", "Code", id=c.id)
            _name(code, c.label_ro)
            if c.label_en and c.label_en != c.label_ro:
                _name(code, c.label_en, lang="en")

    # Concept scheme referenced by every dimension and the measure.
    concepts = _sub(structures, "structure", "Concepts")
    cs = _sub(concepts, "structure", "ConceptScheme", id=f"{flow}_CS",
              version="1.0", agencyID=AGENCY)
    _name(cs, f"Concepts of {flow}", lang="en")
    for d in reg.dims:
        con = _sub(cs, "structure", "Concept", id=d.id)
        _name(con, d.label)
    con = _sub(cs, "structure", "Concept", id="OBS_VALUE")
    _name(con, "Observation value", lang="en")

    dsds = _sub(structures, "structure", "DataStructures")
    dsd = _sub(dsds, "structure", "DataStructure", id=flow, version="1.0", agencyID=AGENCY)
    _name(dsd, name)
    comps = _sub(dsd, "structure", "DataStructureComponents")
    dl = _sub(comps, "structure", "DimensionList", id="DimensionDescriptor")

    def concept_ref(parent, cid):
        ci = _sub(parent, "structure", "ConceptIdentity")
        _ref(ci, id=cid, maintainableParentID=f"{flow}_CS",
             maintainableParentVersion="1.0", agencyID=AGENCY,
             package="conceptscheme", **{"class": "Concept"})

    # SDMX 2.1: Dimension* first, TimeDimension last. position keeps the key order.
    for d in (x for x in reg.dims if not x.is_time):
        el = _sub(dl, "structure", "Dimension", id=d.id, position=d.position)
        concept_ref(el, d.id)
        lr = _sub(el, "structure", "LocalRepresentation")
        en = _sub(lr, "structure", "Enumeration")
        _ref(en, id=d.codelist_id, version="1.0", agencyID=AGENCY,
             package="codelist", **{"class": "Codelist"})
    for d in (x for x in reg.dims if x.is_time):
        el = _sub(dl, "structure", "TimeDimension", id=d.id, position=d.position)
        concept_ref(el, d.id)
        lr = _sub(el, "structure", "LocalRepresentation")
        _sub(lr, "structure", "TextFormat", textType="ObservationalTimePeriod")

    _sub(comps, "structure", "AttributeList", id="AttributeDescriptor")
    ml = _sub(comps, "structure", "MeasureList", id="MeasureDescriptor")
    pm = _sub(ml, "structure", "PrimaryMeasure", id="OBS_VALUE")
    concept_ref(pm, "OBS_VALUE")
    return _serialize(root)


# ---------------------------------------------------------------------------
# Dataflow endpoint
# ---------------------------------------------------------------------------

@router.get("/2.1/dataflow/{agency}/{flow}/{version}")
def get_dataflow(agency: str, flow: str, version: str):
    """SDMX-ML 2.1 Dataflow definition."""
    if not valid_matrix_code(flow):
        raise HTTPException(404, "Dataset not found")
    conn = get_conn()
    try:
        matrix = conn.execute(
            "SELECT matrix_name, matrix_name_en FROM matrices WHERE matrix_code = ?",
            [flow]).fetchone()
    finally:
        conn.close()
    if not matrix:
        raise HTTPException(404, f"Dataset {flow} not found")

    root = ET.Element(_q("message", "Structure"))
    _header(root, flow)
    structures = _sub(root, "message", "Structures")
    flows = _sub(structures, "structure", "Dataflows")
    # The version in the URL is echoed only if it is a valid SDMX version.
    ver = version if re.fullmatch(r"[0-9]+(\.[0-9]+){0,2}", version) else "1.0"
    df = _sub(flows, "structure", "Dataflow", id=flow, version=ver, agencyID=AGENCY)
    _name(df, matrix[0] or flow)
    if matrix[1]:
        _name(df, matrix[1], lang="en")
    st = _sub(df, "structure", "Structure")
    _ref(st, id=flow, version="1.0", agencyID=AGENCY,
         package="datastructure", **{"class": "DataStructure"})
    return _serialize(root)
