"""Request-boundary validation shared by the API routers (FIX-01).

Everything here turns untrusted request values into safe, typed values or
raises ``HTTPException`` with a short, stable message (never SQL, never paths).

Period policy (SDMX startPeriod / endPeriod)
--------------------------------------------
Accepted bound formats, and nothing else:

  YYYY        annual     e.g. 2020
  YYYY-Qn     quarterly  n in 1..4, e.g. 2020-Q3
  YYYY-MM     monthly    MM in 01..12, e.g. 2020-03

Every period covers a span of months. A bound maps to a month index
(year*12 + month-1): ``startPeriod`` to the first month it covers and
``endPeriod`` to the last. A data row is returned when its own span lies
entirely inside [start, end]. This makes mixed granularity explicit and
chronologically correct instead of comparing raw strings:

  * startPeriod=2020 on monthly data  -> from 2020-01
  * endPeriod=2020   on monthly data  -> through 2020-12
  * startPeriod=2020-Q2 on annual data -> annual rows are excluded (an annual
    observation is not wholly inside a range starting mid-year)
  * rows whose TIME_PERIOD is not one of the three formats (legacy labels)
    never match a period bound.

startPeriod must not be later than endPeriod (compared as month spans).
"""
from __future__ import annotations

import json
import logging
import re

from fastapi import HTTPException

log = logging.getLogger("app.api")

MAX_FILTER_VALUES = 10_000

_MATRIX_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_ANNUAL_RE = re.compile(r"^(\d{4})$")
_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def bad_request(message: str, status: int = 400) -> HTTPException:
    return HTTPException(status, message)


def valid_matrix_code(code: str) -> bool:
    """Shape check only; existence is checked against the catalog by callers."""
    return bool(_MATRIX_CODE_RE.match(code or ""))


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

def parse_period_bound(value: str, param: str, *, end: bool) -> int:
    """Return the month index of a period bound (first month if not ``end``,
    last month if ``end``). Raises 400 on a malformed value."""
    v = (value or "").strip()
    m = _ANNUAL_RE.match(v)
    if m:
        base = int(m.group(1)) * 12
        return base + (11 if end else 0)
    m = _QUARTER_RE.match(v)
    if m:
        base = int(m.group(1)) * 12 + (int(m.group(2)) - 1) * 3
        return base + (2 if end else 0)
    m = _MONTH_RE.match(v)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2)) - 1
    raise bad_request(
        f"Invalid {param}: expected YYYY, YYYY-Q1..Q4 or YYYY-MM (month 01..12)")


def parse_period_range(start: str | None, end: str | None) -> tuple[int | None, int | None]:
    """Validate both bounds and their order. Returns (start_month, end_month)."""
    s = parse_period_bound(start, "startPeriod", end=False) if start else None
    e = parse_period_bound(end, "endPeriod", end=True) if end else None
    if s is not None and e is not None and s > e:
        raise bad_request("startPeriod must not be later than endPeriod")
    return s, e


def period_span_sql(col_sql: str) -> tuple[str, str]:
    """SQL expressions (first_month, last_month) for a TIME_PERIOD column.

    ``col_sql`` must already be a safely quoted identifier. Rows in none of
    the accepted formats yield NULL and so fail any bound comparison.
    """
    c = f"CAST({col_sql} AS VARCHAR)"
    year = f"CAST(substr({c}, 1, 4) AS INTEGER) * 12"

    def span(annual: int, quarter: int) -> str:
        return (
            f"CASE "
            f"WHEN regexp_full_match({c}, '[0-9]{{4}}') THEN {year} + {annual} "
            f"WHEN regexp_full_match({c}, '[0-9]{{4}}-Q[1-4]') "
            f"THEN {year} + (CAST(substr({c}, 7, 1) AS INTEGER) - 1) * 3 + {quarter} "
            f"WHEN regexp_full_match({c}, '[0-9]{{4}}-(0[1-9]|1[0-2])') "
            f"THEN {year} + CAST(substr({c}, 6, 2) AS INTEGER) - 1 "
            f"END"
        )
    return span(0, 0), span(11, 2)


def quote_ident(name: str) -> str:
    """Quote a SQL identifier (double any embedded double quote)."""
    return '"' + str(name).replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# Filters / group_by (JSON query parameters)
# ---------------------------------------------------------------------------

def _is_scalar(v) -> bool:
    return isinstance(v, (str, int, float)) and not isinstance(v, bool)


def parse_filters(raw: str | None, allowed_columns) -> dict[str, list]:
    """Parse the ``filters`` query parameter.

    Required shape: a JSON object mapping a known column name to an array of
    scalars (string, integer or float). An empty array means "no constraint
    on that column". Anything else is a 400 - never silently ignored:
    malformed JSON, a non-object (null, array, number...), an unknown column,
    a non-array value, or a non-scalar array member (null, bool, object,
    array).
    """
    if raw is None or raw == "":
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, RecursionError):
        raise bad_request("Invalid filters: not valid JSON")
    if not isinstance(data, dict):
        raise bad_request(
            "Invalid filters: expected a JSON object {column: [values]}")
    allowed = set(allowed_columns)
    total = 0
    out: dict[str, list] = {}
    for col, vals in data.items():
        if col not in allowed:
            raise bad_request(f"Invalid filters: unknown column {col!r}")
        if not isinstance(vals, list):
            raise bad_request(
                f"Invalid filters: values for {col!r} must be an array")
        if not all(_is_scalar(v) for v in vals):
            raise bad_request(
                f"Invalid filters: values for {col!r} must be strings or numbers")
        total += len(vals)
        if total > MAX_FILTER_VALUES:
            raise bad_request("Invalid filters: too many values")
        out[col] = vals
    return out


def parse_group_by(raw: str | None, allowed_columns) -> list[str] | None:
    """Parse the ``group_by`` query parameter: a JSON array of known column
    names. Empty/absent -> None (no aggregation). Malformed -> 400."""
    if raw is None or raw == "":
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, RecursionError):
        raise bad_request("Invalid group_by: not valid JSON")
    if not isinstance(data, list) or not all(isinstance(c, str) for c in data):
        raise bad_request("Invalid group_by: expected a JSON array of column names")
    allowed = set(allowed_columns)
    for c in data:
        if c not in allowed:
            raise bad_request(f"Invalid group_by: unknown column {c!r}")
    return data or None
