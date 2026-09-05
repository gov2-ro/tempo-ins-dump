"""
sdmx_labels.py — Shared label/time-period normalisation for the SDMX pipeline.

Used by 11-build-sdmx-codes.py and 9-csv-to-parquet.py so the two only match
labels one way. See docs/stage9-sdmx-migration-spec.md §2.1-2.2.
"""
import re

# ── Label normalisation ──────────────────────────────────────────────────────

def norm_label(s: str) -> str:
    """Normalise a dimension label for matching.

    INS emits comma-delimited CSVs and replaces commas inside values with
    spaces, so 'De calatori, de cale normala' arrives as
    'De calatori  de cale normala'. Metadata labels also carry leading
    indentation that encodes hierarchy depth. Neither survives a literal
    comparison.
    """
    return re.sub(r"\s+", " ", str(s or "").replace(",", " ")).strip().lower()


def norm_label_cs(s: str) -> str:
    """Case-preserving twin of norm_label() — same comma/whitespace cleanup,
    no lowercasing.

    Some dimensions use ALL CAPS for a section header and Title Case for an
    unrelated line item that happens to share the same words (INS's own
    metadata carries both as distinct nom_item_ids — e.g. AGR208A has both
    'PLANTATII' and 'Plantatii'). norm_label() alone would silently merge
    them. Try this exact-case match first; fall back to norm_label() only
    when it misses, so a genuine case-only mismatch (CSV vs metadata) still
    resolves without conflating two real, distinct options.
    """
    return re.sub(r"\s+", " ", str(s or "").replace(",", " ")).strip()


def clean_label(s: str) -> str:
    """Whitespace-collapse a label for display/storage, preserving case.

    Same shape as norm_label() minus the lowercasing — used when a value has
    no code match and the cleaned original text is written out as-is.
    """
    return re.sub(r"\s+", " ", str(s or "").replace(",", " ")).strip()


# ── Time Period Parser (originally from 10-sdmx-export.py) ──────────────────

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
