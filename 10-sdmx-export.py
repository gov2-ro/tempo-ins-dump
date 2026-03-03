#!/usr/bin/env python3
"""
10-sdmx-export.py — Convert INS TEMPO compacted CSVs to SDMX-CSV 2.0 format.

Input:  data/5-compact-datasets/ro/{id}.csv  (nomItemId integers)
        data/2-metas/ro/{id}.json            (dimension definitions)
Output: data/6-sdmx-csv/ro/{id}.csv          (SDMX-CSV 2.0)
        data/6-sdmx-csv/validation_report.csv

Usage:
    python 10-sdmx-export.py                    # process all datasets
    python 10-sdmx-export.py --matrix ACC101B   # single dataset
    python 10-sdmx-export.py --debug            # verbose logging
    python 10-sdmx-export.py --force            # re-process existing output files
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG = {
    "metas_dir": "data/2-metas/ro",
    "compact_csv_dir": "data/5-compact-datasets/ro",
    "output_dir": "data/6-sdmx-csv/ro",
    "matrices_csv": "data/1-indexes/ro/matrices.csv",
    "validation_report": "data/6-sdmx-csv/validation_report.csv",
    "skip_existing": True,
    "debug": False,
}

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Time Period Parser ─────────────────────────────────────────────────────────

ROMANIAN_ORDINALS = {"I": 1, "II": 2, "III": 3, "IV": 4}

# Romanian month names → month number
ROMANIAN_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}

# Compiled patterns (order matters — most specific first)
_TIME_PATTERNS = [
    # Trimestrul I/II/III/IV YYYY
    (re.compile(r"^Trimestrul\s+(I{1,3}V?|IV)\s+(\d{4})$"), "quarterly"),
    # Luna <name> YYYY  (e.g. "Luna ianuarie 1991")
    (re.compile(r"^Luna\s+([a-zA-Z]+)\s+(\d{4})$"), "monthly_name"),
    # Luna N YYYY  (N = 1-12, numeric)
    (re.compile(r"^Luna\s+(\d{1,2})\s+(\d{4})$"), "monthly"),
    # Cincinal YYYY-YYYY
    (re.compile(r"^Cincinal\s+(\d{4})-(\d{4})$"), "quinquennial"),
    # La 2 ani YYYY
    (re.compile(r"^La\s+2\s+ani\s+(\d{4})$"), "biennial"),
    # Semestrul I/II YYYY  (semi-annual)
    (re.compile(r"^Semestrul\s+(I{1,2})\s+(\d{4})$"), "semi_annual"),
    # Decada N YYYY  (decade of month, used in some datasets)
    (re.compile(r"^Decada\s+(\d)\s+(\d{4}-\d{2})$"), "decade"),
    # Anul YYYY
    (re.compile(r"^Anul\s+(\d{4})$"), "annual"),
    # Anii YYYY - YYYY  (multi-year range, e.g. "Anii 1901 - 2000")
    (re.compile(r"^Anii\s+(\d{4})\s*-\s*(\d{4})$"), "year_range"),
]


def parse_time_period(label: str) -> str | None:
    """Convert Romanian time period label to ISO 8601 string.

    Returns None if the label cannot be parsed.
    """
    s = label.strip()

    for pattern, freq in _TIME_PATTERNS:
        m = pattern.match(s)
        if not m:
            continue

        if freq == "annual":
            return m.group(1)

        elif freq == "quarterly":
            roman = m.group(1)
            year = m.group(2)
            q = ROMANIAN_ORDINALS.get(roman)
            if q is None:
                return None
            return f"{year}-Q{q}"

        elif freq == "monthly_name":
            month_name = m.group(1).lower()
            year = m.group(2)
            month = ROMANIAN_MONTHS.get(month_name)
            if month is None:
                return None
            return f"{year}-{month:02d}"

        elif freq == "monthly":
            month = int(m.group(1))
            year = m.group(2)
            if not 1 <= month <= 12:
                return None
            return f"{year}-{month:02d}"

        elif freq == "quinquennial":
            # SDMX duration: start year + P5Y
            start_year = m.group(1)
            return f"{start_year}-P5Y"

        elif freq == "biennial":
            # Fallback to year (no standard SDMX biennial code)
            return m.group(1)

        elif freq == "year_range":
            # Multi-year range: encode as start/end pair using SDMX duration notation
            start = m.group(1)
            end = m.group(2)
            years = int(end) - int(start) + 1
            return f"{start}-P{years}Y"

        elif freq == "semi_annual":
            roman = m.group(1)
            year = m.group(2)
            s_num = ROMANIAN_ORDINALS.get(roman, 1)
            return f"{year}-S{s_num}"

        elif freq == "decade":
            # Decada N YYYY-MM — decade of month (10-day period)
            decade = m.group(1)
            ym = m.group(2)
            return f"{ym}-D{decade}"

    return None


def looks_like_time_period(label: str) -> bool:
    """Heuristic: does this string look like a time period label?"""
    return parse_time_period(label) is not None


# ── Dimension Classifier ───────────────────────────────────────────────────────

# Semantic mappings: (substring_lower, case_insensitive) → SDMX column name
_SEMANTIC_RULES = [
    # Time — checked first via option-value heuristic and label
    ("perioade", "TIME_PERIOD"),
    # Unit of measure
    ("um:", "UNIT_MEASURE"),
    # Geographic
    ("judete", "GEO"),
    ("regiuni", "GEO"),
    ("localitati", "GEO"),
    ("macroregiuni", "GEO"),
    ("comune", "GEO"),
    ("municipii", "GEO"),
    # Demographic
    ("sexe", "SEX"),
    # Age
    ("varsta", "AGE"),
    ("grupe de varsta", "AGE"),
    # Residence
    ("rezidenta", "RESIDENCE"),
    ("mediu de", "RESIDENCE"),
    # Education
    ("nivel de educatie", "EDU_LEVEL"),
    ("nivel educational", "EDU_LEVEL"),
    ("nivel instructie", "EDU_LEVEL"),
    # Economic activity
    ("activitati economice", "ECON_ACTIVITY"),
    ("activitate economica", "ECON_ACTIVITY"),
    # Nationality / citizenship
    ("nationalitate", "NATIONALITY"),
    # Occupation
    ("ocupatii", "OCCUPATION"),
    ("ocupatie", "OCCUPATION"),
]


def classify_dimensions(dimensions_map: list) -> dict:
    """Classify each dimension in dimensionsMap.

    Returns:
        {dim_code: {"sdmx_name": str, "role": str}}

    Roles: "time", "unit", "geo", "semantic", "generic"
    """
    result = {}
    used_names = set()

    def unique_name(name: str) -> str:
        if name not in used_names:
            used_names.add(name)
            return name
        # Disambiguate duplicates (rare)
        i = 2
        while f"{name}_{i}" in used_names:
            i += 1
        n = f"{name}_{i}"
        used_names.add(n)
        return n

    for dim in dimensions_map:
        code = dim["dimCode"]
        label = dim.get("label", "")
        label_lower = label.lower()
        options = dim.get("options", [])

        # --- Priority 1: Unit of measure (must precede time — "UM: Ani" has "ani") ---
        is_unit = (
            label_lower.startswith("um:")
            or " um" in label_lower
            or label_lower.strip() == "um"
            or "unitati de masura" in label_lower
            or label_lower.startswith("unitati")
        )
        if is_unit:
            result[code] = {"sdmx_name": unique_name("UNIT_MEASURE"), "role": "unit"}
            continue

        # --- Priority 2: Time dimension ---
        # Check label contains "perioade"/"luni"/"ani" OR sample options parse as time periods
        is_time = any(kw in label_lower for kw in ("perioade", "luni", " ani", "saptamani"))
        if not is_time and options:
            sample = [o["label"] for o in options[:5]]
            is_time = any(looks_like_time_period(s) for s in sample)

        if is_time:
            result[code] = {"sdmx_name": unique_name("TIME_PERIOD"), "role": "time"}
            continue

        # --- Priority 3: Semantic rules ---
        matched = False
        for substr, sdmx_name in _SEMANTIC_RULES:
            if substr in label_lower:
                role = "geo" if sdmx_name == "GEO" else "semantic"
                result[code] = {"sdmx_name": unique_name(sdmx_name), "role": role}
                matched = True
                break

        if matched:
            continue

        # --- Fallback: generic DIM_N ---
        result[code] = {"sdmx_name": unique_name(f"DIM_{code}"), "role": "generic"}

    return result


# ── Reverse lookup: nomItemId → label ─────────────────────────────────────────

def build_time_lookup(dimensions_map: list, classification: dict) -> dict:
    """Build nomItemId → ISO 8601 string for the TIME_PERIOD dimension."""
    lookup = {}
    for dim in dimensions_map:
        code = dim["dimCode"]
        if classification.get(code, {}).get("role") != "time":
            continue
        for opt in dim.get("options", []):
            parsed = parse_time_period(opt["label"])
            lookup[str(opt["nomItemId"])] = parsed  # may be None
    return lookup


# ── SDMX Row Builder ──────────────────────────────────────────────────────────

def build_sdmx_rows(
    matrix_id: str,
    compact_csv_path: Path,
    classification: dict,
    time_lookup: dict,
    debug: bool = False,
) -> tuple[list[dict], list[str], dict]:
    """Read compacted CSV and build SDMX-CSV rows.

    Returns:
        (rows, fieldnames, stats)
        stats: {row_count, confidential_count, time_parse_failures, has_obs_status}
    """
    rows = []
    stats = {
        "row_count": 0,
        "confidential_count": 0,
        "time_parse_failures": 0,
        "has_obs_status": False,
    }

    # Determine column order for non-time, non-unit dims
    time_col = None    # 0-based index
    unit_col = None
    other_cols = []    # [(0-based index, sdmx_name)]

    for dim_code, info in sorted(classification.items()):
        idx = dim_code - 1  # dimCode is 1-based
        if info["role"] == "time":
            time_col = idx
        elif info["role"] == "unit":
            unit_col = idx
        else:
            other_cols.append((idx, info["sdmx_name"]))

    # Build fieldnames
    fieldnames = ["STRUCTURE", "STRUCTURE_ID", "ACTION"]
    fieldnames += [name for _, name in other_cols]
    fieldnames += ["TIME_PERIOD", "UNIT_MEASURE", "OBS_VALUE"]

    has_conf = False
    n_cols_expected = max(classification.keys())  # number of dim columns

    with open(compact_csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)  # skip original header

        for line_num, raw in enumerate(reader, start=2):
            if not raw or all(v.strip() == "" for v in raw):
                continue

            # raw = [dim1_id, dim2_id, ..., dimN_id, value]
            # last column is the observation value
            n_dims = len(raw) - 1

            # TIME_PERIOD
            time_val = None
            if time_col is not None and time_col < n_dims:
                time_id = raw[time_col].strip()
                time_val = time_lookup.get(time_id)
                if time_val is None:
                    # Fallback: CSV may not be fully compacted — try parsing as raw label
                    time_val = parse_time_period(time_id)
                if time_val is None:
                    stats["time_parse_failures"] += 1
                    if debug:
                        log.debug(f"[{matrix_id}] line {line_num}: unmapped time id {time_id!r}")

            # UNIT_MEASURE
            unit_val = ""
            if unit_col is not None and unit_col < n_dims:
                unit_val = raw[unit_col].strip()

            # OBS_VALUE — detect confidential markers
            raw_value = raw[-1].strip() if raw else ""
            obs_value = ""
            obs_status = ""
            if raw_value.lower() in ("c", "x", "-"):
                obs_value = ""
                obs_status = "C" if raw_value.lower() == "c" else "S"
                stats["confidential_count"] += 1
                has_conf = True
            elif raw_value:
                try:
                    obs_value = float(raw_value.replace(",", "."))
                    # Format: int if whole number, float otherwise
                    if obs_value == int(obs_value):
                        obs_value = int(obs_value)
                except ValueError:
                    obs_value = ""
                    if debug:
                        log.debug(f"[{matrix_id}] line {line_num}: non-numeric value {raw_value!r}")

            row = {
                "STRUCTURE": matrix_id,
                "STRUCTURE_ID": matrix_id,
                "ACTION": "A",
            }
            for idx, name in other_cols:
                row[name] = raw[idx].strip() if idx < n_dims else ""
            row["TIME_PERIOD"] = time_val or ""
            row["UNIT_MEASURE"] = unit_val
            row["OBS_VALUE"] = obs_value

            if obs_status:
                row["OBS_STATUS"] = obs_status

            rows.append(row)
            stats["row_count"] += 1

    if has_conf:
        fieldnames.append("OBS_STATUS")
        stats["has_obs_status"] = True

    return rows, fieldnames, stats


# ── Validation ────────────────────────────────────────────────────────────────

def validate_dataset(
    matrix_id: str,
    rows: list[dict],
    classification: dict,
    stats: dict,
    fieldnames: list[str],
) -> dict:
    """Run compliance checks and return a validation result dict."""
    result = {
        "matrix_id": matrix_id,
        "row_count": stats["row_count"],
        "confidential_count": stats["confidential_count"],
        "time_parse_failures": stats["time_parse_failures"],
        "has_obs_status": stats["has_obs_status"],
        "time_dim_identified": False,
        "unit_dim_identified": False,
        "multi_unit": False,
        "time_parse_ok": True,
        "obs_value_numeric": True,
        "no_duplicate_keys": True,
        "errors": [],
        "warnings": [],
    }

    # Check dimension identification
    roles = {info["role"] for info in classification.values()}
    result["time_dim_identified"] = "time" in roles
    result["unit_dim_identified"] = "unit" in roles

    if not result["time_dim_identified"]:
        result["errors"].append("TIME_PERIOD dimension not identified")
    if not result["unit_dim_identified"]:
        result["warnings"].append("UNIT_MEASURE dimension not identified")

    # Time parse failures
    if stats["time_parse_failures"] > 0:
        result["time_parse_ok"] = False
        result["errors"].append(f"{stats['time_parse_failures']} TIME_PERIOD parse failures")

    # OBS_VALUE numeric check
    bad_values = sum(1 for r in rows if r.get("OBS_VALUE") == "" and not r.get("OBS_STATUS"))
    if bad_values > 0:
        result["obs_value_numeric"] = False
        result["warnings"].append(f"{bad_values} empty OBS_VALUE without OBS_STATUS")

    # Multi-unit check
    if "UNIT_MEASURE" in fieldnames:
        units = {r.get("UNIT_MEASURE", "") for r in rows}
        result["multi_unit"] = len(units) > 1

    # Duplicate key check (dim values + TIME_PERIOD)
    dim_cols = [f for f in fieldnames if f not in (
        "STRUCTURE", "STRUCTURE_ID", "ACTION", "OBS_VALUE", "OBS_STATUS"
    )]
    seen = set()
    for r in rows:
        key = tuple(str(r.get(c, "")) for c in dim_cols)
        if key in seen:
            result["no_duplicate_keys"] = False
            result["warnings"].append("Duplicate observation keys found")
            break
        seen.add(key)

    result["errors"] = "; ".join(result["errors"]) or ""
    result["warnings"] = "; ".join(result["warnings"]) or ""
    return result


# ── I/O Helpers ───────────────────────────────────────────────────────────────

def load_meta(matrix_id: str, metas_dir: str) -> dict | None:
    path = Path(metas_dir) / f"{matrix_id}.json"
    if not path.exists():
        log.warning(f"[{matrix_id}] metadata not found: {path}")
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_matrix_list(matrices_csv: str) -> list[str]:
    ids = []
    with open(matrices_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("code", "").strip()
            if code:
                ids.append(code)
    return ids


def write_sdmx_csv(output_path: Path, rows: list[dict], fieldnames: list[str]):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_validation_report(results: list[dict], report_path: str):
    if not results:
        return
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(results[0].keys())
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    log.info(f"Validation report written → {report_path}")


# ── Per-Dataset Processing ────────────────────────────────────────────────────

def process_matrix(matrix_id: str, config: dict) -> dict:
    """Process one matrix. Returns validation result dict."""
    output_path = Path(config["output_dir"]) / f"{matrix_id}.csv"

    if config["skip_existing"] and output_path.exists():
        if config["debug"]:
            log.debug(f"[{matrix_id}] skipping (output exists)")
        return {"matrix_id": matrix_id, "skipped": True, "errors": "", "warnings": ""}

    # Load metadata
    meta = load_meta(matrix_id, config["metas_dir"])
    if meta is None:
        return {"matrix_id": matrix_id, "skipped": False, "errors": "metadata missing", "warnings": ""}

    dimensions_map = meta.get("dimensionsMap", [])
    if not dimensions_map:
        return {"matrix_id": matrix_id, "skipped": False, "errors": "empty dimensionsMap", "warnings": ""}

    # Classify dimensions
    classification = classify_dimensions(dimensions_map)
    if config["debug"]:
        for code, info in classification.items():
            log.debug(f"[{matrix_id}] dim {code}: {info}")

    # Build time lookup
    time_lookup = build_time_lookup(dimensions_map, classification)

    # Load compacted CSV
    compact_path = Path(config["compact_csv_dir"]) / f"{matrix_id}.csv"
    if not compact_path.exists():
        return {"matrix_id": matrix_id, "skipped": False, "errors": "compacted CSV missing", "warnings": ""}

    # Build SDMX rows
    try:
        rows, fieldnames, stats = build_sdmx_rows(
            matrix_id, compact_path, classification, time_lookup, debug=config["debug"]
        )
    except Exception as e:
        log.error(f"[{matrix_id}] build_sdmx_rows failed: {e}")
        return {"matrix_id": matrix_id, "skipped": False, "errors": str(e), "warnings": ""}

    # Validate
    val = validate_dataset(matrix_id, rows, classification, stats, fieldnames)

    # Write output
    write_sdmx_csv(output_path, rows, fieldnames)
    if config["debug"]:
        log.debug(f"[{matrix_id}] wrote {stats['row_count']} rows → {output_path}")

    return val


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Export INS TEMPO data to SDMX-CSV 2.0")
    parser.add_argument("--matrix", help="Process a single matrix ID (e.g. ACC101B)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--force", action="store_true", help="Re-process already exported files")
    args = parser.parse_args()

    config = dict(CONFIG)
    config["debug"] = args.debug
    if args.force:
        config["skip_existing"] = False

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load matrix list
    if args.matrix:
        matrices = [args.matrix]
    else:
        matrices = load_matrix_list(config["matrices_csv"])
        log.info(f"Found {len(matrices)} matrices to process")

    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)

    results = []
    skipped = 0
    errors = 0

    for i, mid in enumerate(matrices, start=1):
        val = process_matrix(mid, config)
        results.append(val)

        if val.get("skipped"):
            skipped += 1
        elif val.get("errors"):
            errors += 1
            log.warning(f"[{mid}] ERROR: {val['errors']}")
        else:
            if not args.matrix and i % 100 == 0:
                log.info(f"  Progress: {i}/{len(matrices)} ({errors} errors so far)")

    # Summary
    processed = len(results) - skipped
    log.info(f"Done. Processed: {processed}, Skipped: {skipped}, Errors: {errors}")

    # Write validation report (exclude skipped rows — they have a different shape)
    non_skipped = [r for r in results if not r.get("skipped")]
    # Normalise: ensure all rows have the same keys before writing
    report_rows = [
        {k: v for k, v in r.items() if k != "skipped"}
        for r in non_skipped
    ]
    if report_rows:
        write_validation_report(report_rows, config["validation_report"])

    # Print single-matrix summary if requested
    if args.matrix and results:
        r = results[0]
        print("\n── Validation Result ──────────────────────────────")
        for k, v in r.items():
            print(f"  {k}: {v}")
        if not r.get("errors"):
            out = Path(config["output_dir"]) / f"{args.matrix}.csv"
            print(f"\n  Output: {out}")


if __name__ == "__main__":
    main()
