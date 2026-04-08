#!/usr/bin/env python
"""Generate `data/eval/chart_selector_baseline.json`.

Snapshots the current chart_selector output for every dataset in `matrices`.
The MCP tool `tempo_eval_chart_selector` diffs subsequent runs against this
file to detect regressions when chart_selector logic changes.

Run after intentional changes to chart_selector that you want to bake in:

    python scripts/build_chart_selector_baseline.py

The output is deterministic (no timestamps inside the file) so re-running on
unchanged code produces a no-op git diff.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.db import get_conn  # noqa: E402
from app.services.chart_selector_eval import evaluate_all  # noqa: E402


BASELINE_PATH = REPO_ROOT / "data" / "eval" / "chart_selector_baseline.json"
BASELINE_VERSION = 1


def main() -> int:
    print(f"Loading metadata + scoring all datasets…")
    conn = get_conn()
    datasets = evaluate_all(conn)
    print(f"  Scored {len(datasets)} datasets")

    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Custom format: pretty header, one dataset per line. Stable, compact,
    # and git-diff-friendly when single rows shift.
    sorted_keys = sorted(datasets.keys())
    lines = [
        "{",
        f'  "version": {BASELINE_VERSION},',
        f'  "total_datasets": {len(datasets)},',
        '  "datasets": {',
    ]
    for i, mc in enumerate(sorted_keys):
        entry = json.dumps(datasets[mc], ensure_ascii=False, separators=(",", ":"))
        sep = "," if i < len(sorted_keys) - 1 else ""
        lines.append(f'    {json.dumps(mc)}: {entry}{sep}')
    lines.append("  }")
    lines.append("}")
    BASELINE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"  Wrote {BASELINE_PATH.relative_to(REPO_ROOT)} ({BASELINE_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
