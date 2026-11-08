"""Unit-type overrides for matrices whose profile misreports the kind of value (PKG-TOOLS F5).

INS publishes the IPC102 consumer-price tables as indices (the base period is 100: 100.32 means
+0.32% on the previous month) with the unit label "Procente". The profile therefore says
`percentage`. A reader who takes 100.32 for a percentage rate gets the answer wrong. Tools
report `index` for these matrices. The override changes what the envelope says only; the
aggregation policy keeps reading the profile.
"""
from __future__ import annotations

INDEX_PREFIXES = ("IPC102",)


def unit_type(code: str | None, current: str | None) -> str | None:
    """`index` for an IPC102 matrix (or a split child of one), else `current`."""
    if code and str(code).startswith(INDEX_PREFIXES):
        return "index"
    return current


def apply(env: dict) -> dict:
    """Correct `unit_type` in the cited sources of an envelope, in place."""
    for src in ((env.get("provenance") or {}).get("sources") or []):
        if isinstance(src, dict) and "unit_type" in src:
            src["unit_type"] = unit_type(src.get("dataset"), src["unit_type"])
    return env
