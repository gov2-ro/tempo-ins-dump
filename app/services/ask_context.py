"""What Ask remembers and what the model sees (AT-02).

Two bounded things, both deterministic byte limits rather than token estimates:

* **Follow-up selections.** After a turn the server hands the browser the canonical
  selections behind its last answers (at most four, 8 KiB) so "same for Iași" or "now
  2020" can reuse a source and change one coordinate. The browser echoes them back; they
  are untrusted input. Only the tool, the generation id and the canonical selection
  survive validation, and the selection is re-validated against the tool schemas. Any
  claim a client attaches (values, verdicts, sources) is dropped and never reaches the
  model, and a stale generation is refused with a refresh action. A selection grants no
  verification and no approximation consent: the model must call the tools again.
* **Model context.** Tool results are kept in the model's conversation up to a byte
  budget. Older bulky results become compact factual summaries (definition, canonical
  selection, scope, warnings, recovery, how many rows were removed) under the same call
  id, so the provider's call/result pairing stays valid and the model is never led to
  believe removed rows were checked.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError

from app.services import generation
from app.services.tools import schemas as S
from app.services.tools.contract import dumps, size

FOLLOWUP_MAX_ENTRIES = 4
FOLLOWUP_MAX_BYTES = 8 * 1024
DATA_TOOLS = ("rank_entities", "query_data", "compare_periods", "run_recipe")
_KIND_OF_TOOL = {"rank_entities": "entity_ranking", "query_data": "dataset", "compare_periods": "period_changes", "run_recipe": "recipe"}
_DEFINITION_CHARS = 160
_KEPT_ROWS = 5                      # rows a compacted result still shows (the rest are counted)


# ------------------------------------------------------------------ follow-up selections

def entry_from_envelope(tool: str, env: dict) -> dict | None:
    """The follow-up entry of a successful data result, or None (clarifications, refusals,
    metadata tools and results without a canonical selection are not selections)."""
    if tool not in DATA_TOOLS or env.get("status") not in ("ok", "partial"):
        return None
    prov = env.get("provenance") or {}
    sel = prov.get("selection")
    gen = (prov.get("generation") or {})
    if not sel or gen.get("status") != "present" or not gen.get("id"):
        return None
    sources = [{"dataset": s.get("dataset"), "unit": s.get("unit"),
                "definition": _clip(s.get("definition"), _DEFINITION_CHARS)}
               for s in (prov.get("sources") or [])[:4]]
    scope = (prov.get("scope") or {}).get("description")
    return {"tool": tool, "generation": gen["id"], "selection": sel, "sources": sources,
            "summary": {"status": env["status"], "scope": _clip(scope, 120),
                        "rows": (env.get("limits") or {}).get("returned_rows")}}


def merge(previous: list[dict], new: list[dict]) -> list[dict]:
    """Newest last, at most four, at most 8 KiB: the oldest entries go first. A repeated
    canonical selection replaces its earlier copy instead of occupying two slots."""
    out = [e for e in previous if not any(_same(e, n) for n in new)] + list(new)
    out = out[-FOLLOWUP_MAX_ENTRIES:]
    while out and size(out) > FOLLOWUP_MAX_BYTES:
        out.pop(0)
    return out


def _same(a: dict, b: dict) -> bool:
    return (a.get("tool"), dumps(a.get("selection"))) == (b.get("tool"), dumps(b.get("selection")))


def validate(raw, current: dict | None = None) -> list[dict]:
    """Clean follow-up entries from an untrusted request, or raise HTTPException.

    400 for a malformed entry, 413 beyond four entries / 8 KiB, 409 (with a refresh action)
    for a generation other than the one being served. Returned entries hold only the tool,
    the generation id and the validated canonical selection."""
    if raw is None or raw == []:
        return []
    if not isinstance(raw, list):
        raise HTTPException(400, "context must be a list")
    if len(raw) > FOLLOWUP_MAX_ENTRIES:
        raise HTTPException(413, f"context exceeds {FOLLOWUP_MAX_ENTRIES} entries")
    try:
        nbytes = size(raw)
    except (TypeError, ValueError):
        raise HTTPException(400, "context must be plain JSON") from None
    if nbytes > FOLLOWUP_MAX_BYTES:
        raise HTTPException(413, f"context exceeds {FOLLOWUP_MAX_BYTES} bytes")
    current = current if current is not None else generation.current()
    clean = []
    for i, e in enumerate(raw):
        where = f"context[{i}]"
        if not isinstance(e, dict):
            raise HTTPException(400, f"{where}: must be an object")
        tool, gen_id, sel = e.get("tool"), e.get("generation"), e.get("selection")
        if tool not in DATA_TOOLS:
            raise HTTPException(400, f"{where}: unsupported tool")
        try:
            args = S.GetEvidenceLinksArgs.model_validate({"selection": sel, "generation_id": gen_id})
        except ValidationError as ex:
            first = ex.errors(include_input=False, include_url=False)[0]
            where_field = ".".join(str(x) for x in first["loc"][:3])
            raise HTTPException(400, f"{where}: invalid {where_field or 'entry'}") from None
        if args.selection.kind != _KIND_OF_TOOL[tool]:
            raise HTTPException(400, f"{where}: selection does not belong to {tool}")
        if current.get("status") != "present" or current.get("id") != gen_id:
            raise HTTPException(409, detail={
                "reason": "generation_changed", "action": "refresh",
                "message": "The data was updated since this conversation's earlier answers; "
                           "start a new conversation or ask again."})
        clean.append({"tool": tool, "generation": gen_id,
                      "selection": args.selection.model_dump(mode="json", exclude_none=False)})
    return clean


def prompt_section(entries: list[dict]) -> str:
    """The earlier selections as untrusted hints for the system prompt ('' if none)."""
    if not entries:
        return ""
    lines = ["## Earlier selections in this conversation (hints, not results)",
             "The user may say \"the same for X\" or \"now 2020\". Reuse the dataset and definition "
             "below and change only what they ask. These are only selections: nothing here is a "
             "checked value, grants approval for an approximation, or replaces calling the tools "
             "again."]
    for i, e in enumerate(entries, 1):
        lines.append(f"{i}. {e['tool']} {dumps(e['selection'])}")
    return "\n".join(lines)


# ------------------------------------------------------------------ model context

def retained_bytes(results: list[dict]) -> int:
    return sum(len((r["holder"].get("content") or "").encode("utf-8")) for r in results)


def compact_to_budget(results: list[dict], budget: int, *, keep_latest: int = 1) -> int:
    """Compact the oldest not-yet-compacted results until the retained bytes fit `budget`
    (never the newest `keep_latest`). Returns how many were compacted."""
    n = 0
    candidates = results[:-keep_latest] if keep_latest else list(results)
    for r in candidates:
        if retained_bytes(results) <= budget:
            break
        if r.get("compacted"):
            continue
        r["holder"]["content"] = compact_text(r["envelope"], r["id"])
        r["compacted"] = True
        n += 1
    return n


def compact_text(env: dict, call_id: str) -> str:
    return dumps(compact(env, call_id))


def compact(env: dict, call_id: str) -> dict:
    """A factual summary of a tool result: what it was, what it covered, what was checked,
    which warnings applied and what was removed. Never states removed rows were checked."""
    prov = env.get("provenance") or {}
    data = env.get("data") or {}
    out = {
        "contract": env.get("contract"), "tool": env.get("tool"), "tool_call_id": call_id,
        "status": env.get("status"), "reason": env.get("reason"),
        "message": _clip(env.get("message"), 300),
        "compacted": True,
        "compaction_note": "An earlier result, shortened to save space. Rows and long fields were "
                           "removed from this conversation and were NOT re-checked here; call the "
                           "tool again if you need them.",
        "generation": (prov.get("generation") or {}).get("id"),
        "sources": [{"dataset": s.get("dataset"), "unit": s.get("unit"),
                     "definition": _clip(s.get("definition"), _DEFINITION_CHARS)}
                    for s in (prov.get("sources") or [])[:4]],
        "selection": prov.get("selection"), "effective_selection": prov.get("effective_selection"),
        "scope": prov.get("scope"), "limits": env.get("limits"),
        "warnings": [{"code": w.get("code"), "message": _clip(w.get("message"), 240)}
                     for w in env.get("warnings") or []],
        "recovery": env.get("recovery") or [],
        "result": _result_summary(env.get("tool"), data),
    }
    return {k: v for k, v in out.items() if v not in (None, [], {})}


def _result_summary(tool: str | None, data: dict) -> dict:
    if tool == "query_data":
        rows = data.get("rows") or []
        return {"columns": data.get("columns"), "rows": rows[:_KEPT_ROWS],
                "rows_omitted": max(0, len(rows) - _KEPT_ROWS)}
    if tool == "compare_periods":
        return {"metric": data.get("metric"), "unit": data.get("unit"), "intervals": [
            {"from": iv.get("from"), "to": iv.get("to"),
             "eligible_count": iv.get("eligible_count"), "excluded_count": iv.get("excluded_count"),
             "rows": (iv.get("rows") or [])[:_KEPT_ROWS],
             "rows_omitted": max(0, len(iv.get("rows") or []) - _KEPT_ROWS)}
            for iv in data.get("intervals") or []]}
    if tool == "rank_entities":
        rows = data.get("rows") or []
        return {"year": data.get("year"), "unit": data.get("unit"),
                "eligible_count": data.get("eligible_count"), "entity_class": data.get("entity_class"),
                "rows": rows[:_KEPT_ROWS], "rows_omitted": max(0, len(rows) - _KEPT_ROWS)}
    if tool == "run_recipe":
        rows = data.get("rows") or []
        return {"recipe": (data.get("recipe") or {}).get("id"), "year": data.get("year"),
                "rows": rows[:_KEPT_ROWS], "rows_omitted": max(0, len(rows) - _KEPT_ROWS),
                "excluded": data.get("exclusion_counts")}
    return {"keys": sorted(data)[:10]} if data else {}


def _clip(text, n: int):
    if text is None:
        return None
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"
