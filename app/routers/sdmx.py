"""SDMX 2.1 REST API endpoints for INS TEMPO data.

Provides the minimal endpoints required by the SDMX Dashboard Generator:
  GET /sdmx/2.1/data/INS,{flow}/{key}         → SDMX-ML 2.1 XML (GenericData)
  GET /sdmx/2.1/datastructure/INS/{flow}/1.0  → SDMX-ML 2.1 XML (DSD)
  GET /sdmx/2.1/dataflow/INS/{flow}/1.0       → SDMX-ML 2.1 XML (Dataflow)

Note: sdmxthon (used by the Dashboard Generator) only supports XML, not JSON.
"""
from __future__ import annotations

import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.db import get_conn
from app.config import PARQUET_DIR, PARQUET_V2_DIR

router = APIRouter()

AGENCY = "INS"


def _parquet_path(flow: str) -> str | None:
    """Return path to parquet file, preferring v3 over v2."""
    p = PARQUET_DIR / f"{flow}.parquet"
    if p.exists():
        return str(p)
    p2 = PARQUET_V2_DIR / f"{flow}.parquet"
    if p2.exists():
        return str(p2)
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
            break
        if part:  # non-empty = specific value(s)
            # SDMX allows '+' as OR separator
            filters[dim_names[i]] = part.split("+")
    return filters


# ---------------------------------------------------------------------------
# Data endpoint — returns SDMX-JSON 2.0
# ---------------------------------------------------------------------------

@router.get("/2.1/data/{agency_flow:path}")
def get_data(
    agency_flow: str,
    lastNObservations: Optional[int] = Query(None),
    startPeriod: Optional[str] = Query(None),
    endPeriod: Optional[str] = Query(None),
):
    """SDMX data endpoint.

    URL form: /sdmx/2.1/data/INS,ACC102B/..
    The path after the flow ID is the dimension key (dot-separated).
    """
    import duckdb as _duckdb

    # Parse "INS,ACC102B/key" or "INS,ACC102B"
    if "/" in agency_flow:
        flow_part, key = agency_flow.split("/", 1)
        key = key.rstrip("/")
    else:
        flow_part, key = agency_flow, ""

    # Strip agency prefix (e.g. "INS,ACC102B" → "ACC102B")
    flow = flow_part.split(",")[-1].strip()

    parquet = _parquet_path(flow)
    if not parquet:
        raise HTTPException(404, f"Dataset {flow} not found")

    conn_meta = get_conn()
    dims = conn_meta.execute(
        "SELECT dim_label, dim_column_name, dim_code FROM dimensions WHERE matrix_code = ? ORDER BY dim_code",
        [flow]
    ).fetchall()
    if not dims:
        raise HTTPException(404, f"No dimensions found for {flow}")

    dim_names = [d[1] for d in dims]   # column names in parquet
    dim_labels = [d[0] for d in dims]  # human-readable labels

    # Build WHERE clauses
    key_filters = _parse_key(key, dim_names)

    conn_data = _duckdb.connect()
    where_clauses: list[str] = []
    for col, vals in key_filters.items():
        quoted = ", ".join(f"'{v.replace(chr(39), chr(39)*2)}'" for v in vals)
        where_clauses.append(f'"{col}" IN ({quoted})')

    if startPeriod:
        where_clauses.append(f'"TIME_PERIOD" >= \'{startPeriod}\'')
    if endPeriod:
        where_clauses.append(f'"TIME_PERIOD" <= \'{endPeriod}\'')

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # For lastNObservations: get last N distinct TIME_PERIOD values
    time_filter_sql = ""
    if lastNObservations:
        time_rows = conn_data.execute(
            f"SELECT DISTINCT TIME_PERIOD FROM read_parquet('{parquet}') {where_sql} ORDER BY TIME_PERIOD DESC LIMIT {lastNObservations}"
        ).fetchall()
        if time_rows:
            time_vals = ", ".join(f"'{r[0]}'" for r in time_rows)
            if where_clauses:
                where_sql += f' AND "TIME_PERIOD" IN ({time_vals})'
            else:
                where_sql = f'WHERE "TIME_PERIOD" IN ({time_vals})'

    col_select = ", ".join(f'"{c}"' for c in dim_names) + ', "OBS_VALUE"'
    sql = f"SELECT {col_select} FROM read_parquet('{parquet}') {where_sql} LIMIT 50000"

    try:
        rows = conn_data.execute(sql).fetchall()
    except Exception as e:
        raise HTTPException(500, f"Query error: {e}")

    # -----------------------------------------------------------------------
    # Build SDMX-ML 2.1 GenericData XML
    # sdmxthon requires: GenericData root, Header with Structure element,
    # DataSet with generic:Obs children (flat "AllDimensions" format).
    # -----------------------------------------------------------------------

    def _esc(v: str) -> str:
        return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    obs_lines: list[str] = []
    for row in rows:
        values = "".join(
            f'<generic:Value id="{dim_names[i]}" value="{_esc(row[i] if row[i] is not None else "")}"/>'
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
        <structure:Name>{label}</structure:Name>{code_items}
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
      <structure:Dataflow id="{flow}" version="{version}" agencyID="{AGENCY}">
        <structure:Name xml:lang="ro">{safe_name}</structure:Name>
        <structure:Structure>
          <Ref id="{flow}" version="1.0" agencyID="{AGENCY}" package="datastructure" class="DataStructure"/>
        </structure:Structure>
      </structure:Dataflow>
    </structure:Dataflows>
  </message:Structures>
</message:Structure>"""

    return Response(content=xml, media_type="application/xml")
