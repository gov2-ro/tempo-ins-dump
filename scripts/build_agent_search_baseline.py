#!/usr/bin/env python
"""Generate `data/eval/agent_search_baseline.json`.

Captures the current top-K dataset hits for every question in
`data/eval/agent_questions.yaml`. The MCP tool `tempo_eval_agent` diffs
subsequent runs against this file to detect retrieval regressions when
the FTS index, search ranking, or dataset corpus changes.

Run after intentional changes to the search layer that you want to bake in:

    python scripts/build_agent_search_baseline.py

The output is deterministic (sorted keys, no timestamps inside the file)
so re-running on unchanged code produces a no-op git diff.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.services.agent_eval import load_questions, run_search_eval  # noqa: E402


QUESTIONS_PATH = REPO_ROOT / "data" / "eval" / "agent_questions.yaml"
BASELINE_PATH = REPO_ROOT / "data" / "eval" / "agent_search_baseline.json"
BASELINE_VERSION = 1


def main() -> int:
    print(f"Loading questions from {QUESTIONS_PATH.relative_to(REPO_ROOT)}…")
    questions = load_questions(QUESTIONS_PATH)
    print(f"  Loaded {len(questions)} questions")

    print("Running search eval…")
    current = run_search_eval(questions)
    print(f"  Captured top-{current['top_k']} for {len(current['questions'])} questions")

    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Stable layout: pretty header, one question per line, sorted.
    sorted_qs = sorted(current["questions"].keys())
    lines = [
        "{",
        f'  "version": {BASELINE_VERSION},',
        f'  "top_k": {current["top_k"]},',
        f'  "total_questions": {len(sorted_qs)},',
        '  "questions": {',
    ]
    for i, q in enumerate(sorted_qs):
        entry = json.dumps(current["questions"][q], ensure_ascii=False, separators=(",", ":"))
        sep = "," if i < len(sorted_qs) - 1 else ""
        lines.append(f'    {json.dumps(q, ensure_ascii=False)}: {entry}{sep}')
    lines.append("  }")
    lines.append("}")
    BASELINE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"  Wrote {BASELINE_PATH.relative_to(REPO_ROOT)} ({BASELINE_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
