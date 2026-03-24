#!/usr/bin/env python3
"""
11-build-sdmx-codes.py — Build SDMX code mapping tables in DuckDB.

Creates two tables:
  1. sdmx_codes: nom_item_id → sdmx_value (human-readable string for parquet-v3)
  2. sdmx_column_map: (matrix_code, old_column_name) → sdmx_column_name

These tables enable the parquet-v2 → parquet-v3 transformation (12-parquet-to-sdmx.py).

Usage:
    python 11-build-sdmx-codes.py              # build both tables
    python 11-build-sdmx-codes.py --debug       # verbose logging
    python 11-build-sdmx-codes.py --dry-run     # preview without writing to DB
"""

import argparse
import logging
import re
import sys
from collections import Counter
from pathlib import Path

import duckdb

from duckdb_config import DB_FILE

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Time Period Parser (from 10-sdmx-export.py) ─────────────────────────────

ROMANIAN_ORDINALS = {"I": 1, "II": 2, "III": 3, "IV": 4}
ROMANIAN_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}

_TIME_PATTERNS = [
    (re.compile(r"^Trimestrul\s+(I{1,3}V?|IV)\s+(\d{4})$"), "quarterly"),
    (re.compile(r"^Luna\s+([a-zA-ZăâîșțĂÂÎȘȚ]+)\s+(\d{4})$"), "monthly_name"),
    (re.compile(r"^Luna\s+(\d{1,2})\s+(\d{4})$"), "monthly"),
    (re.compile(r"^Cincinal\s+(\d{4})-(\d{4})$"), "quinquennial"),
    (re.compile(r"^La\s+2\s+ani\s+(\d{4})$"), "biennial"),
    (re.compile(r"^Semestrul\s+(I{1,2})\s+(\d{4})$"), "semi_annual"),
    (re.compile(r"^Decada\s+(\d)\s+(\d{4}-\d{2})$"), "decade"),
    (re.compile(r"^Anul\s+(\d{4})$"), "annual"),
    (re.compile(r"^Anii\s+(\d{4})\s*-\s*(\d{4})$"), "year_range"),
    # Bare year (common in some datasets)
    (re.compile(r"^(\d{4})$"), "bare_year"),
]


def parse_time_period(label: str) -> str | None:
    """Convert Romanian time period label to ISO 8601 string."""
    s = label.strip()
    for pattern, freq in _TIME_PATTERNS:
        m = pattern.match(s)
        if not m:
            continue
        if freq == "annual" or freq == "bare_year":
            return m.group(1)
        elif freq == "quarterly":
            q = ROMANIAN_ORDINALS.get(m.group(1))
            return f"{m.group(2)}-Q{q}" if q else None
        elif freq == "monthly_name":
            month = ROMANIAN_MONTHS.get(m.group(1).lower())
            return f"{m.group(2)}-{month:02d}" if month else None
        elif freq == "monthly":
            month = int(m.group(1))
            return f"{m.group(2)}-{month:02d}" if 1 <= month <= 12 else None
        elif freq == "quinquennial":
            return f"{m.group(1)}-P5Y"
        elif freq == "biennial":
            return m.group(1)
        elif freq == "year_range":
            years = int(m.group(2)) - int(m.group(1)) + 1
            return f"{m.group(1)}-P{years}Y"
        elif freq == "semi_annual":
            s_num = ROMANIAN_ORDINALS.get(m.group(1), 1)
            return f"{m.group(2)}-S{s_num}"
        elif freq == "decade":
            return f"{m.group(2)}-D{m.group(1)}"
    return None


# ── SDMX Concept Mapping ────────────────────────────────────────────────────

# dim_type → SDMX concept ID
DIM_TYPE_TO_SDMX = {
    "time": "TIME_PERIOD",
    "geo": "REF_AREA",
    "gender": "SEX",
    "age": "AGE",
    "unit": "UNIT_MEASURE",
    "residence": "RESIDENCE",
    "indicator": None,  # use descriptive name or DIM_N
}

# Semantic rules for indicator dimensions → descriptive SDMX names
# (substring in dim_label_lower → SDMX column name)
_INDICATOR_RULES = [
    ("nivel de educatie", "EDU_LEVEL"),
    ("nivel educational", "EDU_LEVEL"),
    ("nivel instructie", "EDU_LEVEL"),
    ("activitati economice", "ECON_ACTIVITY"),
    ("activitate economica", "ECON_ACTIVITY"),
    ("activitati ale economiei", "ECON_ACTIVITY"),
    ("nationalitate", "NATIONALITY"),
    ("cetatenie", "NATIONALITY"),
    ("ocupatii", "OCCUPATION"),
    ("ocupatie", "OCCUPATION"),
    ("stare civila", "MARITAL_STATUS"),
    ("statut profesional", "PROF_STATUS"),
    ("forma de proprietate", "OWNERSHIP"),
    ("clase de marime", "SIZE_CLASS"),
    ("tipuri de", "TYPE"),
    ("categorii de", "CATEGORY"),
    ("cauze de", "CAUSE"),
]


def classify_dim_to_sdmx(dim_type: str, dim_label: str, used_names: set) -> str:
    """Map a dimension's type + label to an SDMX column name, ensuring uniqueness."""
    label_lower = dim_label.lower().strip()

    # Check for unit of measure (highest priority — before time, since "UM: Ani" contains "ani")
    if label_lower.startswith("um:") or label_lower.startswith("unitati") or label_lower.strip() == "um":
        return _unique_name("UNIT_MEASURE", used_names)

    # Direct mapping for well-known types
    sdmx_name = DIM_TYPE_TO_SDMX.get(dim_type)
    if sdmx_name:
        return _unique_name(sdmx_name, used_names)

    # Indicator type: try semantic rules on dim_label
    if dim_type == "indicator":
        for substr, name in _INDICATOR_RULES:
            if substr in label_lower:
                return _unique_name(name, used_names)

    # Fallback: generate descriptive name from dim_label
    clean = _label_to_column_id(dim_label)
    if clean and clean not in ("dim", ""):
        return _unique_name(clean, used_names)

    # Last resort: generic DIM_N
    n = 1
    while f"DIM_{n}" in used_names:
        n += 1
    name = f"DIM_{n}"
    used_names.add(name)
    return name


def _unique_name(name: str, used: set) -> str:
    """Return name if unused, else append _2, _3, etc."""
    if name not in used:
        used.add(name)
        return name
    i = 2
    while f"{name}_{i}" in used:
        i += 1
    n = f"{name}_{i}"
    used.add(n)
    return n


def _label_to_column_id(label: str) -> str:
    """Convert a dim_label like 'Categorii de someri' to 'CATEGORII_DE_SOMERI'."""
    # Remove UM: prefix
    s = re.sub(r'^UM:\s*', '', label)
    # Remove diacritics (rough)
    s = s.replace('ă', 'a').replace('â', 'a').replace('î', 'i').replace('ș', 's').replace('ț', 't')
    s = s.replace('Ă', 'A').replace('Â', 'A').replace('Î', 'I').replace('Ș', 'S').replace('Ț', 'T')
    # Keep only alphanum + space
    s = re.sub(r'[^a-zA-Z0-9\s]', '', s)
    # Convert to uppercase, replace spaces with underscore
    s = '_'.join(s.upper().split())
    # Limit length
    if len(s) > 40:
        s = s[:40].rstrip('_')
    return s


# ── Build sdmx_codes table ──────────────────────────────────────────────────

def build_sdmx_codes(conn: duckdb.DuckDBPyConnection, debug: bool = False) -> int:
    """Build the sdmx_codes table mapping nom_item_id → sdmx_value.

    Returns number of rows inserted.
    """
    log.info("Building sdmx_codes table...")

    # Fetch all parsed options with their labels
    rows = conn.execute("""
        SELECT DISTINCT
            p.nom_item_id,
            p.dim_type,
            o.option_label,
            p.raw_label,
            p.parse_confidence,
            p.year,
            p.time_granularity,
            p.geo_name_clean
        FROM dimension_options_parsed p
        JOIN dimension_options o ON o.nom_item_id = p.nom_item_id
    """).fetchall()

    # Deduplicate: same nom_item_id may appear in multiple dimensions
    # Keep one row per nom_item_id (they should have consistent dim_type)
    seen = {}
    for nom_id, dim_type, label, raw_label, confidence, year, time_gran, geo_clean in rows:
        if nom_id in seen:
            continue
        seen[nom_id] = (dim_type, label, raw_label, confidence, year, time_gran, geo_clean)

    log.info(f"  Processing {len(seen)} unique nom_item_ids...")

    records = []
    time_parse_ok = 0
    time_parse_fail = 0

    for nom_id, (dim_type, label, raw_label, confidence, year, time_gran, geo_clean) in seen.items():
        label_clean = label.strip() if label else (raw_label or "").strip()

        if dim_type == "time":
            # Parse to ISO 8601
            sdmx_val = parse_time_period(label_clean)
            if sdmx_val is None:
                # Fallback: use cleaned label
                sdmx_val = label_clean
                time_parse_fail += 1
                if debug:
                    log.debug(f"  Time parse failed: {label_clean!r}")
            else:
                time_parse_ok += 1
        else:
            # For all other types: use the option_label as-is (trimmed)
            sdmx_val = label_clean

        records.append((
            nom_id,
            dim_type,
            sdmx_val,
            label_clean,  # display_label_ro (same as label for now)
            None,          # display_label_en (populated later)
            None,          # standard_code (populated later for NUTS/ISO)
            "parsed",      # source
        ))

    log.info(f"  Time parsing: {time_parse_ok} OK, {time_parse_fail} fallback to label")

    # Try to populate English labels from English dimension_options if available
    en_labels = {}
    try:
        en_rows = conn.execute("""
            SELECT DISTINCT o.nom_item_id, o.option_label
            FROM dimension_options o
            JOIN dimensions d ON d.dimension_id = o.dimension_id
            JOIN matrices m ON m.matrix_code = d.matrix_code
            WHERE m.lang = 'en'
        """).fetchall()
        for nom_id, en_label in en_rows:
            en_labels[nom_id] = en_label.strip()
        log.info(f"  Found {len(en_labels)} English labels")
    except Exception:
        log.info("  No English labels available (matrices may not have lang column or en data)")

    # Apply English labels
    final_records = []
    for nom_id, dim_type, sdmx_val, ro_label, _, std_code, source in records:
        en_label = en_labels.get(nom_id)
        final_records.append((nom_id, dim_type, sdmx_val, ro_label, en_label, std_code, source))

    return final_records


def build_sdmx_column_map(conn: duckdb.DuckDBPyConnection, debug: bool = False) -> list:
    """Build the sdmx_column_map table mapping (matrix_code, old_column_name) → sdmx_column_name.

    Returns list of (matrix_code, old_column_name, sdmx_column_name, dim_type) tuples.
    """
    log.info("Building sdmx_column_map table...")

    # Get all dimensions with their majority dim_type
    rows = conn.execute("""
        WITH dim_types AS (
            SELECT
                d.matrix_code,
                d.dim_code,
                d.dim_label,
                d.dim_column_name,
                p.dim_type,
                COUNT(*) as cnt
            FROM dimensions d
            JOIN dimension_options o ON o.dimension_id = d.dimension_id
            JOIN dimension_options_parsed p ON p.nom_item_id = o.nom_item_id
            GROUP BY d.matrix_code, d.dim_code, d.dim_label, d.dim_column_name, p.dim_type
        ),
        majority AS (
            SELECT
                matrix_code,
                dim_code,
                dim_label,
                dim_column_name,
                dim_type,
                cnt,
                ROW_NUMBER() OVER (
                    PARTITION BY matrix_code, dim_code
                    ORDER BY cnt DESC
                ) as rn
            FROM dim_types
        )
        SELECT matrix_code, dim_code, dim_label, dim_column_name, dim_type
        FROM majority
        WHERE rn = 1
        ORDER BY matrix_code, dim_code
    """).fetchall()

    log.info(f"  Processing {len(rows)} dimension entries across matrices...")

    # Group by matrix_code
    matrices = {}
    for mc, dc, dl, dcn, dt in rows:
        matrices.setdefault(mc, []).append((dc, dl, dcn, dt))

    records = []
    dupes_skipped = 0
    for matrix_code, dims in matrices.items():
        used_names = set()
        used_old_cols = set()  # Track old_column_name to skip duplicates (truncation collisions)

        for dim_code, dim_label, old_col_name, dim_type in dims:
            if old_col_name in used_old_cols:
                dupes_skipped += 1
                if debug:
                    log.debug(f"  [{matrix_code}] SKIP duplicate old_col: {old_col_name} (dim_code={dim_code})")
                continue
            used_old_cols.add(old_col_name)

            sdmx_name = classify_dim_to_sdmx(dim_type, dim_label, used_names)
            records.append((matrix_code, old_col_name, sdmx_name, dim_type))

            if debug:
                log.debug(f"  [{matrix_code}] {old_col_name} → {sdmx_name} ({dim_type})")

    # Add the value → OBS_VALUE mapping for all matrices
    for matrix_code in matrices:
        records.append((matrix_code, "value", "OBS_VALUE", "measure"))

    if dupes_skipped:
        log.info(f"  Skipped {dupes_skipped} duplicate column names (truncation collisions)")
    log.info(f"  Generated {len(records)} column mappings for {len(matrices)} matrices")

    return records


# ── Schema ───────────────────────────────────────────────────────────────────

SDMX_SCHEMA_SQL = """
-- SDMX code mapping: nom_item_id → human-readable values
CREATE TABLE IF NOT EXISTS sdmx_codes (
    nom_item_id INTEGER PRIMARY KEY,
    dim_type VARCHAR NOT NULL,
    sdmx_value VARCHAR NOT NULL,
    display_label_ro VARCHAR,
    display_label_en VARCHAR,
    standard_code VARCHAR,
    source VARCHAR DEFAULT 'parsed'
);

CREATE INDEX IF NOT EXISTS idx_sdmx_codes_type ON sdmx_codes(dim_type);
CREATE INDEX IF NOT EXISTS idx_sdmx_codes_value ON sdmx_codes(sdmx_value);

-- SDMX column mapping: parquet-v2 column names → SDMX concept IDs
CREATE TABLE IF NOT EXISTS sdmx_column_map (
    matrix_code VARCHAR NOT NULL,
    old_column_name VARCHAR NOT NULL,
    sdmx_column_name VARCHAR NOT NULL,
    dim_type VARCHAR,
    PRIMARY KEY (matrix_code, old_column_name)
);

CREATE INDEX IF NOT EXISTS idx_sdmx_colmap_matrix ON sdmx_column_map(matrix_code);
CREATE INDEX IF NOT EXISTS idx_sdmx_colmap_sdmx ON sdmx_column_map(sdmx_column_name);
"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build SDMX code mapping tables")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    db_path = str(DB_FILE)
    log.info(f"Database: {db_path}")

    conn = duckdb.connect(db_path, read_only=args.dry_run)

    try:
        if not args.dry_run:
            # Drop and recreate tables
            conn.execute("DROP TABLE IF EXISTS sdmx_codes")
            conn.execute("DROP TABLE IF EXISTS sdmx_column_map")
            conn.execute(SDMX_SCHEMA_SQL)
            log.info("Created sdmx_codes and sdmx_column_map tables")

        # Phase 0: Build sdmx_codes
        code_records = build_sdmx_codes(conn, debug=args.debug)

        if not args.dry_run:
            conn.executemany(
                "INSERT INTO sdmx_codes VALUES (?, ?, ?, ?, ?, ?, ?)",
                code_records,
            )
            count = conn.execute("SELECT COUNT(*) FROM sdmx_codes").fetchone()[0]
            log.info(f"Inserted {count} rows into sdmx_codes")
        else:
            log.info(f"[DRY RUN] Would insert {len(code_records)} rows into sdmx_codes")

        # Phase 1: Build sdmx_column_map
        col_records = build_sdmx_column_map(conn, debug=args.debug)

        if not args.dry_run:
            conn.executemany(
                "INSERT INTO sdmx_column_map VALUES (?, ?, ?, ?)",
                col_records,
            )
            count = conn.execute("SELECT COUNT(*) FROM sdmx_column_map").fetchone()[0]
            log.info(f"Inserted {count} rows into sdmx_column_map")
        else:
            log.info(f"[DRY RUN] Would insert {len(col_records)} rows into sdmx_column_map")

        # Print summary statistics
        if not args.dry_run:
            print("\n── Summary ─────────────────────────────────────────")

            print("\nsdmx_codes by dim_type:")
            for row in conn.execute("""
                SELECT dim_type, COUNT(*) cnt,
                       SUM(CASE WHEN standard_code IS NOT NULL THEN 1 ELSE 0 END) has_std
                FROM sdmx_codes GROUP BY dim_type ORDER BY cnt DESC
            """).fetchall():
                print(f"  {row[0]:15s}  {row[1]:6d} rows  ({row[2]} with standard_code)")

            print("\nsdmx_column_map — top SDMX columns:")
            for row in conn.execute("""
                SELECT sdmx_column_name, COUNT(*) cnt
                FROM sdmx_column_map
                GROUP BY sdmx_column_name ORDER BY cnt DESC
                LIMIT 15
            """).fetchall():
                print(f"  {row[0]:25s}  {row[1]:5d} matrices")

            print("\nSample mappings (ACC101B):")
            for row in conn.execute("""
                SELECT old_column_name, sdmx_column_name, dim_type
                FROM sdmx_column_map WHERE matrix_code = 'ACC101B'
                ORDER BY old_column_name
            """).fetchall():
                print(f"  {row[0]:50s} → {row[1]:15s} ({row[2]})")

            print("\nSample sdmx_codes (time):")
            for row in conn.execute("""
                SELECT nom_item_id, sdmx_value, display_label_ro
                FROM sdmx_codes WHERE dim_type = 'time' LIMIT 5
            """).fetchall():
                print(f"  {row[0]:8d} → {row[1]:15s} (label: {row[2]})")

            print("\nSample sdmx_codes (geo):")
            for row in conn.execute("""
                SELECT nom_item_id, sdmx_value, display_label_ro
                FROM sdmx_codes WHERE dim_type = 'geo' LIMIT 5
            """).fetchall():
                print(f"  {row[0]:8d} → {row[1]:25s} (label: {row[2]})")

    finally:
        conn.close()

    log.info("Done.")


if __name__ == "__main__":
    sys.exit(main() or 0)
