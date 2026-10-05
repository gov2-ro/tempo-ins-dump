"""Complete-file exports (FIX-04): CSV streaming and XLSX via a temp file.

Exports are raw observations matching the validated explicit filters. They are
never bound by the chart cap (``MAX_DATA_ROWS``), never windowed and never drop
edge periods. Memory is bounded by ``EXPORT_BATCH_ROWS``: rows are pulled with
``fetchmany`` and written out immediately.

Spreadsheet safety (formula injection)
--------------------------------------
Only dimension label cells that are strings are affected; the OBS_VALUE column
and non-string dimension cells are never touched.
  * XLSX: label strings are written with an explicit string cell type, so a
    value such as ``=SUM(A1)`` is stored as text and never evaluated. The text
    itself is unchanged.
  * CSV: a label starting with ``= + - @`` TAB or CR (and not a plain number such
    as ``-5``) gets a leading apostrophe, the OWASP-recommended neutralisation,
    because CSV has no cell types. Pass ``safe=0`` to the endpoint for the
    verbatim labels (pipelines that never open the file in a spreadsheet).
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import tempfile

import app.config as cfg

log = logging.getLogger(__name__)

# Excel worksheet capacity, including the header row.
EXCEL_MAX_SHEET_ROWS = 1_048_576

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)$")


def csv_safe(value):
    """Neutralise a string label for spreadsheet use (see module docstring)."""
    if isinstance(value, str) and value.startswith(_FORMULA_START) \
            and not _PLAIN_NUMBER.match(value):
        return "'" + value
    return value


def xlsx_row_limit() -> int:
    """Max data rows (header excluded) an XLSX export may hold."""
    return min(cfg.EXPORT_XLSX_MAX_ROWS, EXCEL_MAX_SHEET_ROWS - 1)


def load_value_maps(conn, matrix_code: str, dimensions) -> dict:
    """RO label -> EN label maps per dimension column (lang=en)."""
    value_maps: dict = {}
    for d in dimensions:
        col = d['dim_column_name']
        mapping = conn.execute("""
            SELECT dopt.option_label, COALESCE(sc.display_label_en, dopt.option_label)
            FROM dimension_options dopt
            JOIN dimensions dim ON dim.dimension_id = dopt.dimension_id
            LEFT JOIN sdmx_codes sc ON sc.nom_item_id = dopt.nom_item_id
            WHERE dim.matrix_code = ? AND dim.dim_column_name = ?
        """, [matrix_code, col]).fetchall()
        if mapping:
            value_maps[col] = {ro: en for ro, en in mapping}
    return value_maps


def make_row_transform(col_names, value_maps, safe: bool, for_csv: bool):
    """Per-row translation + label safety. Last column is OBS_VALUE: untouched."""
    n = len(col_names) - 1
    names = col_names[:n]

    def transform(row):
        out = list(row)
        for i in range(n):
            v = out[i]
            if v is None:
                continue
            m = value_maps.get(names[i])
            if m:
                v = m.get(str(v), v)
            if safe and for_csv:
                v = csv_safe(v)
            out[i] = v
        return out
    return transform


def iter_csv(cur, col_names, transform, batch_rows: int, close):
    """Yield CSV text chunks. ``close`` always runs (done, error, disconnect)."""
    try:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(col_names)
        while True:
            batch = cur.fetchmany(batch_rows)
            if not batch:
                break
            for row in batch:
                w.writerow(transform(row))
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
        tail = buf.getvalue()
        if tail:
            yield tail
    finally:
        close()


def write_xlsx_tempfile(cur, matrix_code, col_names, transform, batch_rows: int,
                        max_rows: int, safe: bool) -> tuple[str, int]:
    """Write the result to a write-only workbook in a temp file.

    Returns (path, rows_written). Raises OverflowError if more than ``max_rows``
    rows arrive (the temp file is removed first): never truncates silently.
    """
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    fd, path = tempfile.mkstemp(prefix="tempo-export-", suffix=".xlsx")
    os.close(fd)
    try:
        wb = Workbook(write_only=True)
        ws = wb.create_sheet(title=matrix_code[:31])
        ws.append(col_names)
        n = 0
        while True:
            batch = cur.fetchmany(batch_rows)
            if not batch:
                break
            for row in batch:
                n += 1
                if n > max_rows:
                    raise OverflowError(n)
                cells = []
                for i, v in enumerate(transform(row)):
                    if v is None:
                        v = ""
                    elif isinstance(v, str):
                        # openpyxl rejects control chars XML cannot hold
                        v = ILLEGAL_CHARACTERS_RE.sub("", v)
                    if safe and isinstance(v, str) and i < len(col_names) - 1:
                        c = WriteOnlyCell(ws, value=v)
                        c.data_type = "s"
                        v = c
                    cells.append(v)
                ws.append(cells)
        wb.save(path)
        return path, n
    except BaseException:
        _unlink(path)
        raise


def _unlink(path: str):
    try:
        os.unlink(path)
    except OSError:
        pass


def iter_file_then_delete(path: str, close=lambda: None, chunk: int = 1 << 20):
    """Stream a temp file, then delete it (also on error / client disconnect)."""
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                yield b
    finally:
        _unlink(path)
        close()
