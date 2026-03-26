#!/usr/bin/env python3
"""
Normalize verbose dimension labels in DuckDB metadata.

Targets:
  - sdmx_codes.display_label_ro / display_label_en
  - labels_i18n.label_ro / label_en

Transforms:
  1. Macroregions:  'MACROREGIUNEA UNU' → 'Macroregiunea 1'  (all 4 variants)
  2. Regions:       'REGIUNEA NORD-EST' / 'Regiunea Nord - Est' → 'Regiunea Nord-Est'
  3. TOTAL:         'TOTAL' → 'Total'  (in both tables)
  4. Whitespace:    trim leading/trailing spaces (age labels have hierarchy indentation)

Usage:
    python scripts/normalize-labels.py            # apply all transforms
    python scripts/normalize-labels.py --dry-run  # preview only, no DB writes
    python scripts/normalize-labels.py --debug    # verbose per-row output
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))
from duckdb_config import DB_FILE

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)


# ── Macroregion mapping ──────────────────────────────────────────────────────

MACRO_MAP_RO = {
    "MACROREGIUNEA UNU":   "Macroregiunea 1",
    "MACROREGIUNEA DOI":   "Macroregiunea 2",
    "MACROREGIUNEA TREI":  "Macroregiunea 3",
    "MACROREGIUNEA PATRU": "Macroregiunea 4",
    # lowercase word variants (some datasets use these)
    "Macroregiunea unu":   "Macroregiunea 1",
    "Macroregiunea doi":   "Macroregiunea 2",
    "Macroregiunea trei":  "Macroregiunea 3",
    "Macroregiunea patru": "Macroregiunea 4",
}

MACRO_MAP_EN = {
    "MACROREGION 1": "Macroregion 1",
    "MACROREGION 2": "Macroregion 2",
    "MACROREGION 3": "Macroregion 3",
    "MACROREGION 4": "Macroregion 4",
}

# ── Region canonical forms ───────────────────────────────────────────────────
# Keyed by a lowercase normalized key (strip prefix, collapse spaces, lowercase)

REGION_CANONICAL = {
    "nord-est":         ("Regiunea Nord-Est",        "North-East"),
    "nord - est":       ("Regiunea Nord-Est",        "North-East"),
    "nord -est":        ("Regiunea Nord-Est",        "North-East"),
    "nord-vest":        ("Regiunea Nord-Vest",       "North-West"),
    "nord - vest":      ("Regiunea Nord-Vest",       "North-West"),
    "nord -vest":       ("Regiunea Nord-Vest",       "North-West"),
    "sud-est":          ("Regiunea Sud-Est",         "South-East"),
    "sud - est":        ("Regiunea Sud-Est",         "South-East"),
    "sud-muntenia":     ("Regiunea Sud-Muntenia",    "South-Muntenia"),
    "sud - muntenia":   ("Regiunea Sud-Muntenia",    "South-Muntenia"),
    "sud-vest oltenia": ("Regiunea Sud-Vest Oltenia","South-West Oltenia"),
    "sud - vest oltenia":("Regiunea Sud-Vest Oltenia","South-West Oltenia"),
    "sud -vest - oltenia":("Regiunea Sud-Vest Oltenia","South-West Oltenia"),
    "sud - vest - oltenia":("Regiunea Sud-Vest Oltenia","South-West Oltenia"),
    "vest":             ("Regiunea Vest",            "West"),
    "centru":           ("Regiunea Centru",          "Center"),
    "bucuresti-ilfov":  ("Regiunea Bucuresti-Ilfov", "Bucharest-Ilfov"),
    "bucuresti - ilfov":("Regiunea Bucuresti-Ilfov", "Bucharest-Ilfov"),
    "bucharest - ilfov":("Regiunea Bucuresti-Ilfov", "Bucharest-Ilfov"),  # EN variant
    "bucharest-ilfov":  ("Regiunea Bucuresti-Ilfov", "Bucharest-Ilfov"),
}

REGION_PREFIX_RE = re.compile(r"^(REGIUNEA|Regiunea)\s+", re.IGNORECASE)


def normalize_region(label_ro: str, label_en: str | None) -> tuple[str, str] | None:
    """Return (canonical_ro, canonical_en) if label matches a region pattern, else None."""
    if not REGION_PREFIX_RE.match(label_ro or ""):
        return None
    raw = REGION_PREFIX_RE.sub("", label_ro).strip()
    key = raw.lower()
    if key in REGION_CANONICAL:
        return REGION_CANONICAL[key]
    # Fuzzy: try collapsing multiple spaces to single
    key2 = re.sub(r"\s+", " ", key)
    if key2 in REGION_CANONICAL:
        return REGION_CANONICAL[key2]
    return None


def normalize_label_ro(val: str | None) -> str | None:
    """Return normalized RO label or None if no change needed."""
    if val is None:
        return None
    v = val.strip()

    # Macroregion
    if v in MACRO_MAP_RO:
        return MACRO_MAP_RO[v]

    # Region
    region = normalize_region(v, None)
    if region:
        return region[0]

    # TOTAL
    if v == "TOTAL":
        return "Total"

    # Whitespace only
    if v != val:
        return v

    return None  # no change


def normalize_label_en(val: str | None, label_ro: str | None = None) -> str | None:
    """Return normalized EN label or None if no change needed."""
    if val is None:
        return None
    v = val.strip()

    # Macroregion EN
    if v in MACRO_MAP_EN:
        return MACRO_MAP_EN[v]

    # Region EN — derive canonical from RO if available
    if label_ro:
        region = normalize_region(label_ro, v)
        if region:
            return region[1]

    # TOTAL
    if v == "TOTAL":
        return "Total"

    # Whitespace only
    if v != val:
        return v

    return None  # no change


def run(dry_run: bool, debug: bool):
    mode = "DRY RUN" if dry_run else "LIVE"
    log.info(f"Starting label normalization ({mode})")

    conn = duckdb.connect(str(DB_FILE), read_only=dry_run)

    changes_sdmx = 0
    changes_i18n = 0

    # ── 1. sdmx_codes ────────────────────────────────────────────────────────
    log.info("Processing sdmx_codes ...")
    rows = conn.execute(
        "SELECT nom_item_id, display_label_ro, display_label_en FROM sdmx_codes"
    ).fetchall()

    updates_sdmx = []
    for nom_id, lro, len_ in rows:
        new_ro = normalize_label_ro(lro)
        new_en = normalize_label_en(len_, lro)
        if new_ro is not None or new_en is not None:
            final_ro = new_ro if new_ro is not None else lro
            final_en = new_en if new_en is not None else len_
            updates_sdmx.append((final_ro, final_en, nom_id))
            if debug:
                log.debug(f"  sdmx_codes [{nom_id}]: ro={lro!r} → {final_ro!r}, en={len_!r} → {final_en!r}")

    if updates_sdmx and not dry_run:
        conn.executemany(
            "UPDATE sdmx_codes SET display_label_ro = ?, display_label_en = ? WHERE nom_item_id = ?",
            updates_sdmx
        )
    changes_sdmx = len(updates_sdmx)
    log.info(f"  sdmx_codes: {changes_sdmx} rows updated")

    # ── 2. labels_i18n ───────────────────────────────────────────────────────
    log.info("Processing labels_i18n ...")
    rows = conn.execute(
        "SELECT nom_item_id, label_ro, label_en FROM labels_i18n"
    ).fetchall()

    updates_i18n = []
    for nom_id, lro, len_ in rows:
        new_ro = normalize_label_ro(lro)
        new_en = normalize_label_en(len_, lro)
        if new_ro is not None or new_en is not None:
            final_ro = new_ro if new_ro is not None else lro
            final_en = new_en if new_en is not None else len_
            updates_i18n.append((final_ro, final_en, nom_id))
            if debug:
                log.debug(f"  labels_i18n [{nom_id}]: ro={lro!r} → {final_ro!r}, en={len_!r} → {final_en!r}")

    if updates_i18n and not dry_run:
        conn.executemany(
            "UPDATE labels_i18n SET label_ro = ?, label_en = ? WHERE nom_item_id = ?",
            updates_i18n
        )
    changes_i18n = len(updates_i18n)
    log.info(f"  labels_i18n: {changes_i18n} rows updated")

    # ── Summary ──────────────────────────────────────────────────────────────
    total = changes_sdmx + changes_i18n
    if not dry_run and total:
        conn.execute("CHECKPOINT")

    log.info(f"{'[DRY RUN] Would update' if dry_run else 'Updated'} {total} rows total "
             f"({changes_sdmx} sdmx_codes, {changes_i18n} labels_i18n)")

    if dry_run and debug:
        # Show sample of what would change
        log.info("\nSample changes (first 20):")
        for final_ro, final_en, nom_id in (updates_sdmx + updates_i18n)[:20]:
            print(f"  [{nom_id}] → ro={final_ro!r}, en={final_en!r}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Normalize verbose dimension labels in DuckDB")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--debug", action="store_true", help="Log every row change")
    args = parser.parse_args()
    run(dry_run=args.dry_run, debug=args.debug)


if __name__ == "__main__":
    main()
