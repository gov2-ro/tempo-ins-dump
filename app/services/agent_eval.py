"""Search-quality eval for the NL→Data agent.

Exercises the catalog search used by the agent's `search_datasets` tool
and diffs the current top-K hits against a committed baseline. This is
regression detection, not a golden-answer test — the baseline records
whatever the search returns TODAY, and a human judges improvements vs.
regressions when reviewing the diff.

Why search-only and not full LLM runs?
    Full agent runs need an API key, cost money, and are non-deterministic
    (temperature > 0 and tool-call ordering). Search is the biggest lever
    on agent correctness — if the right dataset can't be found, no amount
    of LLM reasoning recovers it. So this harness pins the retrieval layer,
    which is deterministic and cheap.

Two consumers:
    - `scripts/build_agent_search_baseline.py` — writes the committed baseline
    - `tools/tempo-dev-mcp` `tempo_eval_agent` — diffs current run vs baseline
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services.dataset_search import search_datasets


DEFAULT_TOP_K = 10


def load_questions(path: Path) -> list[dict]:
    """Load the seed question set.

    Prefers PyYAML if installed; otherwise falls back to a tiny line-based
    parser that handles the restricted YAML shape used in this repo
    (top-level list of mappings with simple `key: value` entries).
    """
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or []
    except ImportError:
        pass
    return _parse_simple_yaml(text)


def _parse_simple_yaml(text: str) -> list[dict]:
    """Minimal YAML parser for our seed file format.

    Supports:
      - top-level list items starting with `- key: value`
      - subsequent key/value pairs on the same item
      - `#` comments and blank lines
      - scalar values are strings (stripped of surrounding quotes) or ints
    Does NOT support nested mappings, multi-line scalars, or flow style.
    """
    items: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip()
        if stripped.startswith("- "):
            if current is not None:
                items.append(current)
            current = {}
            stripped = stripped[2:]
        if current is None:
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        if value.isdigit():
            value = int(value)  # type: ignore[assignment]
        current[key] = value
    if current is not None:
        items.append(current)
    return items


def run_search_eval(questions: list[dict], *, top_k: int = DEFAULT_TOP_K) -> dict:
    """Run `search_datasets` for every question and capture top-K hits.

    Returns: {
        "top_k": int,
        "questions": {
            "<question>": {
                "top": ["matrix_code", …],   # length up to top_k
                "total_hits": int,            # raw search total
            },
            …
        }
    }
    """
    out: dict[str, dict] = {}
    for entry in questions:
        q = entry.get("question") if isinstance(entry, dict) else None
        if not q:
            continue
        k = int(entry.get("top_k") or top_k)
        try:
            result = search_datasets(q, limit=k)
        except Exception as e:
            out[q] = {"error": str(e), "top": [], "total_hits": 0}
            continue
        datasets = result.get("datasets") or []
        out[q] = {
            "top": [d["matrix_code"] for d in datasets[:k]],
            "total_hits": int(result.get("total") or len(datasets)),
        }
    return {"top_k": top_k, "questions": out}


def diff_against_baseline(baseline: dict, current: dict) -> dict:
    """Compare current search eval to a baseline and return a drift report.

    Drift categories:
      - top_set_changes: top-K *set* of codes differs (order-insensitive)
      - order_changes:   same set but ordering changed
      - total_hit_drifts: `total_hits` differs by > 20% (signals FTS scope change)
      - missing:         question in baseline but not in current
      - added:           question in current but not in baseline
    """
    b_qs = (baseline or {}).get("questions") or {}
    c_qs = (current or {}).get("questions") or {}

    top_set_changes: list[dict] = []
    order_changes: list[dict] = []
    total_hit_drifts: list[dict] = []
    missing: list[str] = []
    added: list[str] = []
    ok = 0

    for q, b in b_qs.items():
        c = c_qs.get(q)
        if not c:
            missing.append(q)
            continue

        b_top = list(b.get("top") or [])
        c_top = list(c.get("top") or [])
        b_set = set(b_top)
        c_set = set(c_top)

        if b_set != c_set:
            top_set_changes.append({
                "question": q,
                "baseline": b_top,
                "current": c_top,
                "added": sorted(c_set - b_set),
                "removed": sorted(b_set - c_set),
            })
            continue

        if b_top != c_top:
            order_changes.append({
                "question": q,
                "baseline": b_top,
                "current": c_top,
            })
            continue

        b_hits = int(b.get("total_hits") or 0)
        c_hits = int(c.get("total_hits") or 0)
        # Drift threshold: 20% relative change OR absolute delta > 20 when baseline is small
        if b_hits > 0:
            rel = abs(c_hits - b_hits) / b_hits
            if rel > 0.20 and abs(c_hits - b_hits) > 5:
                total_hit_drifts.append({
                    "question": q,
                    "baseline_hits": b_hits,
                    "current_hits": c_hits,
                    "delta_pct": round(rel * 100, 1),
                })
                continue

        ok += 1

    for q in c_qs:
        if q not in b_qs:
            added.append(q)

    return {
        "summary": {
            "total_baseline": len(b_qs),
            "total_current": len(c_qs),
            "ok": ok,
            "top_set_changed": len(top_set_changes),
            "order_changed": len(order_changes),
            "total_hit_drifts": len(total_hit_drifts),
            "missing": len(missing),
            "added": len(added),
        },
        "top_set_changes": top_set_changes,          # full — most important signal
        "order_changes": order_changes[:30],
        "total_hit_drifts": total_hit_drifts[:20],
        "missing": missing[:20],
        "added": added[:20],
    }
