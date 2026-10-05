"""SDMX 2.1 REST API endpoints for INS TEMPO data.

Provides the minimal endpoints required by the SDMX Dashboard Generator:
  GET /sdmx/2.1/data/INS,{flow}/{key}         → SDMX-ML 2.1 XML (GenericData)
  GET /sdmx/2.1/datastructure/INS/{flow}/1.0  → SDMX-ML 2.1 XML (DSD)
  GET /sdmx/2.1/dataflow/INS/{flow}/1.0       → SDMX-ML 2.1 XML (Dataflow)

Note: sdmxthon (used by the Dashboard Generator) only supports XML, not JSON.
"""
from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.db import get_conn
from app.config import PARQUET_DIR
from app.services.request_validation import (
    parse_period_range, period_span_sql, quote_ident, valid_matrix_code)

router = APIRouter()
log = logging.getLogger(__name__)

AGENCY = "INS"


def _esc(v) -> str:
    """Escape text for use in XML element content or a double-quoted attribute."""
    return (str(v).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _parquet_path(flow: str) -> str | None:
    """Return path to v3 parquet file."""
    p = PARQUET_DIR / f"{flow}.parquet"
    if p.exists():
        return str(p)
    return None


def _parse_key(key: str, dim_names: list[str]) -> dict[str, list[str]]:
    """Parse SDMX dot-notation key into {column: [values]} filter dict.

    E.g. "Total.Bucuresti." with dims [CATEGORY, REF_AREA, TIME_PERIOD]
    → {"CATEGORY": ["Total"], "REF_AREA": ["Bucuresti"]}
    Empty segments mean 'all values' (wildcard).
    """
    filters: dict[str, list[str]] = {}
    if not key or key in (".", "/"):
        return filters
    parts = key.split(".")
    for i, part in enumerate(parts):
        if i >= len(dim_names):
            if part:
                raise HTTPException(
                    400, "Key has more segments than the dataset has dimensions")
            continue
        if part:  # non-empty = specific value(s)
            # SDMX allows '+' as OR separator
            vals = [v for v in part.split("+") if v]
            if vals:
                filters[dim_names[i]] = vals
    return filters


# ---------------------------------------------------------------------------
# Data endpoint — returns SDMX-JSON 2.0
# ---------------------------------------------------------------------------

@router.get("/2.1/data/{agency_flow:path}")
def get_data(
    agency_flow: str,
    lastNObservations: Optional[int] = Query(None, ge=1, le=10000),
    startPeriod: Optional[str] = Query(None),
    endPeriod: Optional[str] = Query(None),
):
    """SDMX data endpoint.

    URL form: /sdmx/2.1/data/INS,ACC102B/..
    The path after the flow ID is the dimension key (dot-separated).

    4xx responses: 400 malformed/reversed startPeriod/endPeriod or a key with
    more non-empty segments than dimensions; 404 unknown dataset; 422 invalid
    lastNObservations (must be >= 1). See docs/SDMX-API.md.
    """
    # Parse "INS,ACC102B/key" or "INS,ACC102B"
    if "/" in agency_flow:
        flow_part, key = agency_flow.split("/", 1)
        key = key.rstrip("/")
    else:
        flow_part, key = agency_flow, ""

    # Strip agency prefix (e.g. "INS,ACC102B" → "ACC102B")
    flow = flow_part.split(",")[-1].strip()

    # Validate request shape before touching the database.
    if not valid_matrix_code(flow):
        raise HTTPException(404, "Dataset not found")
    start_m, end_m = parse_period_range(startPeriod, endPeriod)

    parquet = _parquet_path(flow)
    if not parquet:
        raise HTTPException(404, f"Dataset {flow} not found")

    # One request-owned cursor on the shared, memory-limited connection
    # (app/db.py) — never an unconstrained in-memory connection.
    conn = get_conn()
    try:
        dims = conn.execute(
            "SELECT dim_label, dim_column_name, dim_code FROM dimensions WHERE matrix_code = ? ORDER BY dim_code",
            [flow]
        ).fetchall()
        if not dims:
            raise HTTPException(404, f"No dimensions found for {flow}")

        dim_names = [d[1] for d in dims]   # column names in parquet
        key_filters = _parse_key(key, dim_names)

        # All user values are bound parameters; identifiers come from the
        # dimensions table and are quoted.
        where_clauses: list[str] = []
        params: list = []
        for col, vals in key_filters.items():
            marks = ", ".join("?" for _ in vals)
            where_clauses.append(f"{quote_ident(col)} IN ({marks})")
            params.extend(vals)

        tp = quote_ident("TIME_PERIOD")
        first_sql, last_sql = period_span_sql(tp)
        if start_m is not None:
            where_clauses.append(f"({first_sql}) >= ?")
            params.append(start_m)
        if end_m is not None:
            where_clauses.append(f"({last_sql}) <= ?")
            params.append(end_m)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # For lastNObservations: get last N distinct TIME_PERIOD values
        if lastNObservations:
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

        col_select = ", ".join(quote_ident(c) for c in dim_names) + ', "OBS_VALUE"'
        sql = f"SELECT {col_select} FROM read_parquet(?) {where_sql} LIMIT 50000"

        try:
            rows = conn.execute(sql, [str(parquet), *params]).fetchall()
        except Exception:
            log.exception("sdmx data query failed flow=%s", flow)
            raise HTTPException(500, "Query failed")
    finally:
        conn.close()

    # -----------------------------------------------------------------------
    # Build SDMX-ML 2.1 GenericData XML
    # sdmxthon requires: GenericData root, Header with Structure element,
    # DataSet with generic:Obs children (flat "AllDimensions" format).
    # -----------------------------------------------------------------------

    obs_lines: list[str] = []
    for row in rows:
        values = "".join(
            f'<generic:Value id="{_esc(dim_names[i])}" value="{_esc(row[i] if row[i] is not None else "")}"/>'
            for i in range(len(dim_names))
        )
        obs_val = "" if row[-1] is None else str(row[-1])
        obs_lines.append(
            f"<generic:Obs>"
            f"<generic:ObsKey>{values}</generic:ObsKey>"
            f"<generic:ObsValue value=\"{_esc(obs_val)}\"/>"
            f"</generic:Obs>"
        )

    dataset_body = "".join(obs_lines)

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<message:GenericData'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"'
        ' xmlns:generic="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/generic"'
        ' xmlns:common="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">'
        f'<message:Header>'
        f'<message:ID>{flow}</message:ID>'
        f'<message:Test>false</message:Test>'
        f'<message:Prepared>2024-01-01T00:00:00</message:Prepared>'
        f'<message:Sender id="{AGENCY}"/>'
        f'<message:Structure structureID="{flow}" dimensionAtObservation="AllDimensions">'
        f'<common:Structure>'
        f'<Ref agencyID="{AGENCY}" id="{flow}" version="1.0" class="DataStructure" package="datastructure"/>'
        f'</common:Structure>'
        f'</message:Structure>'
        f'</message:Header>'
        f'<message:DataSet structureRef="{flow}" action="Replace">'
        f'{dataset_body}'
        f'</message:DataSet>'
        f'</message:GenericData>'
    )

    return Response(content=xml, media_type="application/xml")




# ---------------------------------------------------------------------------
# DSD endpoint — returns SDMX-ML 2.1 XML
# ---------------------------------------------------------------------------

@router.get("/2.1/datastructure/{agency}/{flow}/{version}")
def get_datastructure(agency: str, flow: str, version: str):
    """Minimal SDMX-ML 2.1 DataStructure definition."""
    if not valid_matrix_code(flow):
        raise HTTPException(404, "Dataset not found")
    conn = get_conn()

    dims = conn.execute(
        "SELECT dim_label, dim_column_name, dim_code FROM dimensions WHERE matrix_code = ? ORDER BY dim_code",
        [flow]
    ).fetchall()
    if not dims:
        raise HTTPException(404, f"Dataset {flow} not found")

    matrix = conn.execute(
        "SELECT matrix_name FROM matrices WHERE matrix_code = ?", [flow]
    ).fetchone()
    name = matrix[0] if matrix else flow

    dim_elements = ""
    codelist_elements = ""

    for label, col, order in dims:
        cl_id = f"CL_{col}"
        dim_elements += f"""
        <structure:Dimension id="{col}" position="{order}">
          <structure:ConceptIdentity>
            <Ref id="{col}" maintainableParentID="{flow}_CS" maintainableParentVersion="1.0"
                 agencyID="{AGENCY}" package="conceptscheme" class="Concept"/>
          </structure:ConceptIdentity>
          <structure:LocalRepresentation>
            <structure:Enumeration>
              <Ref id="{cl_id}" version="1.0" agencyID="{AGENCY}" package="codelist" class="Codelist"/>
            </structure:Enumeration>
          </structure:LocalRepresentation>
        </structure:Dimension>"""

        # Get codelist values via dimension_options (joined on dimension_id)
        opts = conn.execute("""
            SELECT DISTINCT dopt.option_label
            FROM dimension_options dopt
            JOIN dimensions d ON d.dimension_id = dopt.dimension_id
            WHERE d.matrix_code = ? AND d.dim_column_name = ?
            LIMIT 500
        """, [flow, col]).fetchall()

        code_items = ""
        for (opt_label,) in opts:
            safe = str(opt_label).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            code_id = safe.replace(" ", "_")[:50]
            code_items += f'\n        <structure:Code id="{code_id}"><structure:Name>{safe}</structure:Name></structure:Code>'

        codelist_elements += f"""
      <structure:Codelist id="{cl_id}" version="1.0" agencyID="{AGENCY}">
        <structure:Name>{_esc(label)}</structure:Name>{code_items}
      </structure:Codelist>"""

    safe_name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<message:Structure xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
  xmlns:structure="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
  xmlns:common="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
  <message:Structures>
    <structure:Codelists>{codelist_elements}
    </structure:Codelists>
    <structure:DataStructures>
      <structure:DataStructure id="{flow}" version="1.0" agencyID="{AGENCY}">
        <structure:Name>{safe_name}</structure:Name>
        <structure:DataStructureComponents>
          <structure:DimensionList id="DimensionDescriptor">{dim_elements}
          </structure:DimensionList>
          <structure:AttributeList id="AttributeDescriptor"/>
          <structure:MeasureList id="MeasureDescriptor">
            <structure:PrimaryMeasure id="OBS_VALUE">
              <structure:ConceptIdentity>
                <Ref id="OBS_VALUE" maintainableParentID="{flow}_CS" maintainableParentVersion="1.0"
                     agencyID="{AGENCY}" package="conceptscheme" class="Concept"/>
              </structure:ConceptIdentity>
            </structure:PrimaryMeasure>
          </structure:MeasureList>
        </structure:DataStructureComponents>
      </structure:DataStructure>
    </structure:DataStructures>
  </message:Structures>
</message:Structure>"""

    return Response(content=xml, media_type="application/xml")


# ---------------------------------------------------------------------------
# Dataflow endpoint — returns SDMX-ML 2.1 XML
# ---------------------------------------------------------------------------

@router.get("/2.1/dataflow/{agency}/{flow}/{version}")
def get_dataflow(agency: str, flow: str, version: str):
    """Minimal SDMX-ML 2.1 Dataflow definition."""
    if not valid_matrix_code(flow):
        raise HTTPException(404, "Dataset not found")
    conn = get_conn()

    matrix = conn.execute(
        "SELECT matrix_name FROM matrices WHERE matrix_code = ?", [flow]
    ).fetchone()
    if not matrix:
        raise HTTPException(404, f"Dataset {flow} not found")

    name = matrix[0]
    safe_name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<message:Structure xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
  xmlns:structure="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
  xmlns:common="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
  <message:Structures>
    <structure:Dataflows>
      <structure:Dataflow id="{flow}" version="{_esc(version)}" agencyID="{AGENCY}">
        <structure:Name xml:lang="ro">{safe_name}</structure:Name>
        <structure:Structure>
          <Ref id="{flow}" version="1.0" agencyID="{AGENCY}" package="datastructure" class="DataStructure"/>
        </structure:Structure>
      </structure:Dataflow>
    </structure:Dataflows>
  </message:Structures>
</message:Structure>"""

    return Response(content=xml, media_type="application/xml")
