"""compare_periods: per-entity change between exact annual endpoints (AT-01e).

The statistics live in `app.services.period_changes` (shared with the evidence
route). This module is the tool adapter: it cuts the full result to the
requested `top_k` and a bounded exclusion sample, builds the envelope and
shrinks it to the byte budget without dropping provenance or warnings.
"""
from __future__ import annotations

from app.services import period_changes
from app.services.tools import contract
from app.services.tools import messages as M
from app.services.tools.contract import recovery


def _evidence_recovery(selection: dict | None, generation_id: str | None, lang: str) -> dict | None:
    if not selection or not generation_id:
        return None
    return recovery("tool_call", M.t(lang, "changes.evidence_link"),
                    "get_evidence_links", {"selection": selection, "generation_id": generation_id})


def compare_periods(args, ctx):
    r = period_changes.run(ctx.conn, args, ctx.lang, ctx=ctx)
    intervals, returned, eligible, cut = [], 0, 0, False
    # top_k is per interval; the whole table stays within the model-visible row cap
    per_interval = min(args.top_k, contract.MAX_TABLE_ROWS // max(1, len(r["intervals"])))
    for iv in r["intervals"]:
        rows = iv["rows"][:per_interval]
        sample = iv["excluded"][:period_changes.EXCLUDED_SAMPLE]
        truncated = len(sample) < len(iv["excluded"])
        cut = cut or len(rows) < len(iv["rows"]) or truncated
        returned += len(rows)
        eligible += iv["eligible_count"]
        intervals.append({"from": iv["from"], "to": iv["to"], "rows": rows,
                          "eligible_count": iv["eligible_count"],
                          "excluded_count": iv["excluded_count"], "excluded": sample,
                          "exclusion_counts": iv["exclusion_counts"],
                          "exclusions_truncated": truncated})
    data = {"dataset": r["dataset"], "entity_columns": r["entity_columns"],
            "key_columns": r["key_columns"], "period_column": r["time_column"],
            "metric": r["metric"], "order": r["order"], "top_k": r["top_k"],
            "unit": r["unit"], "intervals": intervals}
    cities = r.get("entity_class") == "cities"
    if cities:       # present only for the class, so the default result keeps its exact shape
        data.update(entity_class="cities", outside_class_count=r["outside_class_count"])
    limits = {"returned_rows": returned, "total_rows": eligible, "preview_truncated": cut,
              "source_complete": True, "time_windowed": False, "partial_period_dropped": None}
    rec = []
    if cut:
        e = _evidence_recovery(r["selection"], ctx.generation.get("id"), ctx.lang)
        if e:
            rec.append(e)
    lang = ctx.lang
    who = M.t(lang, "changes.who_class" if cities else "changes.who_entity")
    if r["status"] == "unavailable":
        message = M.t(lang, "changes.none_ranked")
        if cities:
            message = M.t(lang, "changes.none_ranked_cities", outside=r["outside_class_count"])
    else:
        excluded = sum(iv["excluded_count"] for iv in intervals)
        unit = r["unit"] or M.t(lang, "changes.source_unit")
        message = M.t(lang, "changes.ranked", unit=unit, n=len(intervals), dataset=r["dataset"], who=who,
                      eligible=eligible, returned=returned)
        if cities:
            message += M.t(lang, "changes.outside_class", outside=r["outside_class_count"])
        if excluded:
            message += M.t(lang, "changes.pairs_excluded", excluded=excluded)
        scope = r["provenance"].get("scope") or {}
        if scope.get("domain_complete") is False:
            message += M.t(lang, "changes.restricted", desc=scope.get("description"))
        elif scope.get("domain_complete") is None:
            message += M.t(lang, "changes.unverified")
        message += " " + M.t(lang, "changes.tail")
    if cities:
        message += " " + M.t(lang, "changes.class_tail")
    return contract.envelope(
        "compare_periods", ctx, status=r["status"], reason=r["reason"], message=message,
        data=data, provenance=r["provenance"], limits=limits, warnings=r["warnings"],
        recovery=rec)


def shrink(env: dict, lang: str = "ro") -> bool:
    """One budget step for the registry: halve every interval's exclusion sample
    (it is the optional part), then every interval's rows down to one. False when
    nothing is left to cut. Provenance, warnings and counts are never touched."""
    ivs = (env.get("data") or {}).get("intervals") or []
    if any(iv.get("excluded") for iv in ivs):
        for iv in ivs:
            ex = iv.get("excluded") or []
            if ex:
                iv["excluded"] = ex[:len(ex) // 2]
                iv["exclusions_truncated"] = True
    elif any(len(iv.get("rows") or []) > 1 for iv in ivs):
        for iv in ivs:
            rows = iv.get("rows") or []
            if len(rows) > 1:
                iv["rows"] = rows[:max(1, len(rows) // 2)]
    else:
        return False
    env["limits"]["returned_rows"] = sum(len(iv.get("rows") or []) for iv in ivs)
    env["limits"]["preview_truncated"] = True
    if not any(w.get("code") == "preview_shortened" for w in env["warnings"]):
        env["warnings"].append(contract.warning("preview_shortened", M.t(lang, "changes.preview_shortened")))
    if len(env["recovery"]) < contract.MAX_RECOVERY \
            and not any(x.get("tool") == "get_evidence_links" for x in env["recovery"]):
        prov = env.get("provenance") or {}
        e = _evidence_recovery(prov.get("selection"), (prov.get("generation") or {}).get("id"), lang)
        if e:
            env["recovery"].append(e)
    return True
