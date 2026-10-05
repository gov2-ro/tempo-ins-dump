"""SDMX code registry (FIX-01 phase 2): one source of truth for the DSD, the
data messages and key parsing.

Design
------
* The stored parquet values are the canonical *values* (they are never
  renamed). Everything SDMX-facing is derived from them by pure functions:

  - ``code_id(value)``: the SDMX code ID. A value that already is a valid
    SDMX ID (``[A-Za-z0-9_@$-]+``, <= 64 chars, not ending ``_<12 hex>``)
    is used unchanged, so a
    canonical key and the legacy label key coincide for plain values such as
    ``Total``. Any other value gets ``<ascii slug>_<sha1[:12] of the FULL
    value>``: stable across rebuilds, independent of the other options,
    never truncated-label based, and collision-free (the hash covers the whole
    value; ``Registry`` verifies uniqueness and fails loudly otherwise).
  - labels are separate (RO always, EN when ``sdmx_codes`` has one).

* A dimension's codelist is the union of the metadata options (values taken
  from ``sdmx_codes.sdmx_value`` when present, else the cleaned option label)
  and every distinct value actually present in the parquet column, so every
  value the data endpoint can emit is declared. No size cutoff.
* TIME_PERIOD is a TimeDimension: no codelist; values are normalized with
  ``sdmx_labels.parse_time_period`` (already-ISO values pass through).
* File column names come from ``resolve_parquet_schema``/``adapt_to_parquet``
  (stale ``*_nom_id`` metadata names, legacy-shaped files); the SDMX-facing
  dimension ID is always the canonical column name.

Key compatibility policy
------------------------
Canonical: the code IDs from the DSD. Legacy: the raw stored value (what the
pre-registry API accepted). A segment resolves to the stored values whose
code ID equals it or which equal it verbatim. Exactly one distinct value ->
fine; more than one -> ``AmbiguousKey`` (HTTP 400); none -> kept verbatim and
simply matches no rows (unchanged behaviour).
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field

from fastapi import HTTPException

from app.services.query_builder import (
    adapt_to_parquet, quote_ident, resolve_parquet_schema)
from sdmx_labels import clean_label, parse_time_period

log = logging.getLogger(__name__)

TIME_DIM = "TIME_PERIOD"
_ID_RE = re.compile(r"^[A-Za-z0-9_@$\-]{1,64}$")
# Generated IDs always end like this; verbatim IDs never do (a value that
# happens to look generated is hashed itself), so the two classes cannot collide.
_HASHED_RE = re.compile(r"_[0-9a-f]{12}$")
_ISO_PERIOD_RE = re.compile(
    r"^\d{4}(-(Q[1-4]|S[12]|0[1-9]|1[0-2]|P\d+Y|D\d))?$")


class AmbiguousKey(HTTPException):
    def __init__(self, message: str):
        super().__init__(400, message)


# ---------------------------------------------------------------------------
# Pure derivations
# ---------------------------------------------------------------------------

def _slug(value: str) -> str:
    s = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s[:32]


def code_id(value: str) -> str:
    """Stable SDMX code ID for a stored value (see module docstring)."""
    value = str(value)
    if _ID_RE.match(value) and not _HASHED_RE.search(value):
        return value
    h = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    s = _slug(value)
    return f"{s}_{h}" if s else f"c_{h}"


def dim_id(name: str) -> str:
    """Valid SDMX ID for a dimension/concept/codelist name."""
    name = str(name)
    if _ID_RE.match(name):
        return name
    return code_id(name)


def normalize_period(value) -> str:
    """Normalized TIME_PERIOD. ISO-like values pass through; INS labels
    ('Luna ianuarie 2004') are parsed; anything else is returned unchanged."""
    v = "" if value is None else str(value).strip()
    if _ISO_PERIOD_RE.match(v):
        return v
    return parse_time_period(v) or v


# ---------------------------------------------------------------------------
# Registry objects
# ---------------------------------------------------------------------------

@dataclass
class Code:
    value: str            # stored parquet value
    id: str
    label_ro: str
    label_en: str | None = None


@dataclass
class DimInfo:
    id: str               # canonical SDMX dimension ID
    file_col: str         # column name in the parquet file
    label: str
    position: int         # 1-based key position
    is_time: bool
    codes: list[Code] = field(default_factory=list)

    @property
    def codelist_id(self) -> str:
        return f"CL_{self.id}"


@dataclass
class Registry:
    flow: str
    dims: list[DimInfo]
    value_col: str
    has_data: bool

    def by_id(self, dim: str) -> DimInfo:
        return next(d for d in self.dims if d.id == dim)

    # -- key parsing ------------------------------------------------------
    def parse_key(self, key: str, conn, parquet: str) -> dict[str, list[str]]:
        """SDMX dot key -> {file_col: [stored values]}; see module policy."""
        if not key or key in (".", "/"):
            return {}
        parts = key.split(".")
        filters: dict[str, list[str]] = {}
        for i, part in enumerate(parts):
            if i >= len(self.dims):
                if part:
                    raise HTTPException(
                        400, "Key has more segments than the dataset has dimensions")
                continue
            segs = [s for s in part.split("+") if s]
            if not segs:
                continue
            dim = self.dims[i]
            universe = _distinct_values(conn, parquet, dim.file_col)
            out: list[str] = []
            for seg in segs:
                out.extend(self._resolve_segment(dim, seg, universe))
            filters[dim.file_col] = out
        return filters

    @staticmethod
    def _resolve_segment(dim: DimInfo, seg: str, universe: list[str]) -> list[str]:
        if dim.is_time:
            norm = normalize_period(seg)
            hits = {v for v in universe if v == seg or normalize_period(v) == norm}
            return sorted(hits) or [seg]
        by_code = {v for v in universe if code_id(v) == seg}
        by_raw = {seg} if seg in set(universe) else set()
        hits = by_code | by_raw
        if len(hits) > 1:
            raise AmbiguousKey(
                f"Ambiguous key segment {seg!r} for dimension {dim.id}: it matches "
                f"{len(hits)} different values; use the code IDs from the "
                f"datastructure endpoint")
        return list(hits) or [seg]

    # -- data encoding ----------------------------------------------------
    def encode_dim(self, dim: DimInfo, value) -> str:
        if value is None:
            return ""
        return normalize_period(value) if dim.is_time else code_id(value)


def _distinct_values(conn, parquet: str, col: str) -> list[str]:
    rows = conn.execute(
        f"SELECT DISTINCT CAST({quote_ident(col)} AS VARCHAR) "
        f"FROM read_parquet(?) WHERE {quote_ident(col)} IS NOT NULL",
        [str(parquet)]).fetchall()
    return [r[0] for r in rows]


def _option_rows(conn, flow: str, dimension_id) -> list[tuple]:
    """(value, label_ro, label_en) per metadata option of one dimension."""
    try:
        rows = conn.execute(
            """SELECT dopt.option_label, s.sdmx_value, s.display_label_ro,
                      s.display_label_en
               FROM dimension_options dopt
               LEFT JOIN sdmx_codes s ON s.nom_item_id = dopt.nom_item_id
               WHERE dopt.dimension_id = ? ORDER BY dopt.nom_item_id""",
            [dimension_id]).fetchall()
    except Exception:
        # No sdmx_codes table (scratch/synthetic DB): labels only.
        rows = [(r[0], None, None, None) for r in conn.execute(
            "SELECT option_label FROM dimension_options WHERE dimension_id = ? "
            "ORDER BY nom_item_id", [dimension_id]).fetchall()]
    out = []
    for opt, sval, ro, en in rows:
        value = sval if sval else clean_label(opt)
        out.append((value, clean_label(ro) if ro else clean_label(opt),
                    clean_label(en) if en else None))
    return out


def _drift_fallback(col: str, columns: list[str]) -> str:
    """Last resort when the shared resolver could not map a stale name: a
    ``foo_bar_nom_id`` metadata column whose file column is ``FOO_BAR``
    (sdmx_column_map is incomplete for some matrices, e.g. ART124A)."""
    if not columns or col in columns or not col.endswith("_nom_id"):
        return col
    guess = col[: -len("_nom_id")].upper()
    return guess if guess in columns else col


def build_registry(conn, flow: str, parquet: str | None) -> Registry | None:
    """Registry for ``flow`` or None when the dataset has no dimensions.

    ``parquet`` may be None (DSD still served from metadata alone).
    """
    dims = conn.execute(
        "SELECT dimension_id, dim_label, dim_column_name, dim_code "
        "FROM dimensions WHERE matrix_code = ? ORDER BY dim_code", [flow]).fetchall()
    if not dims:
        return None

    schema = resolve_parquet_schema(conn, flow) if parquet else {
        "is_legacy": False, "value_column": "OBS_VALUE", "columns": [],
        "to_file": {}, "to_sdmx": {}}
    meta_dims = [{"dim_column_name": d[2]} for d in dims]
    adapted, _, _ = adapt_to_parquet(schema, meta_dims)
    to_sdmx = schema.get("to_sdmx") or {}
    to_file = schema.get("to_file") or {}

    out: list[DimInfo] = []
    for (did, label, meta_col, _order), ad in zip(dims, adapted):
        file_col = _drift_fallback(ad["dim_column_name"], schema.get("columns") or [])
        # SDMX-facing ID: legacy file -> mapped canonical name; canonical file
        # with a stale metadata name -> the mapping's sdmx name.
        sid = to_sdmx.get(file_col) or (
            to_file.get(meta_col) if (not schema["is_legacy"]
                                      and meta_col.endswith("_nom_id")
                                      and to_file.get(meta_col)) else None
        ) or file_col
        info = DimInfo(id=dim_id(sid), file_col=file_col, label=clean_label(label),
                       position=len(out) + 1, is_time=(sid == TIME_DIM))
        if not info.is_time:
            codes: dict[str, Code] = {}
            for value, ro, en in _option_rows(conn, flow, did):
                if value not in codes:
                    codes[value] = Code(value, code_id(value), ro, en)
            if parquet and (not schema["columns"] or file_col in schema["columns"]):
                for v in _distinct_values(conn, parquet, file_col):
                    if v not in codes:
                        codes[v] = Code(v, code_id(v), v)
            info.codes = list(codes.values())
            seen: dict[str, str] = {}
            for c in info.codes:
                if seen.setdefault(c.id, c.value) != c.value:
                    raise RuntimeError(
                        f"SDMX code collision in {flow}/{info.id}: {c.id!r}")
        out.append(info)
    ids = [d.id for d in out]
    if len(set(ids)) != len(ids):
        raise RuntimeError(f"Duplicate SDMX dimension IDs in {flow}")
    cols = schema.get("columns") or []
    has_data = bool(parquet) and all(d.file_col in cols for d in out) if cols else bool(parquet)
    return Registry(flow=flow, dims=out, value_col=schema["value_column"],
                    has_data=has_data)
