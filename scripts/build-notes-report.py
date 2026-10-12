#!/usr/bin/env python3
"""Render app/data/dataset_notes.json as the decision log docs/reports/ins-notes.md.

  python scripts/build-notes-report.py [--out docs/reports/ins-notes.md]

Sections: points to take up with INS (`ins.raise`), source issues, decisions,
then every note by dataset. Read-only except for --out; needs no corpus.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.services.dataset_notes import KINDS, NOTES_PATH, load  # noqa: E402


def _codes(n, limit=8):
    c = n["codes"]
    s = ", ".join(f"`{x}`" for x in c[:limit])
    return s + (f" and {len(c) - limit} more" if len(c) > limit else "")


def _who(n):
    d = n.get("decided") or {}
    return f" Decided by {d['by']}, {d['date']}" + (f" ({d['context']})" if d.get("context") else "") + "." \
        if d.get("by") else ""


def render(notes: list[dict]) -> str:
    L = ["# Dataset notes and decisions",
         "",
         "Generated from `app/data/dataset_notes.json` by `scripts/build-notes-report.py`;",
         "edit the JSON, not this file. Public notes are shown on the dataset pages.",
         "How totals, averages and rates are computed: [METHODOLOGY](../METHODOLOGY.md).",
         ""]
    raise_ = [n for n in notes if (n.get("ins") or {}).get("raise")]
    L += ["## To take up with INS", ""]
    for n in raise_:
        L.append(f"- **{n['id']}** ({_codes(n)}): {n['ins']['question']}  ")
        L.append(f"  Context: {n['text']['en']}")
    L += ["", "## Source issues (ours or INS's)", ""]
    for n in notes:
        if n["kind"] == "source_issue":
            L.append(f"- **{n['id']}** ({_codes(n)}): {n['text']['en']}"
                     + (f" Evidence: {n['evidence']}" if n.get("evidence") else ""))
    L += ["", "## Decisions", ""]
    for n in notes:
        if n.get("decided"):
            L.append(f"- **{n['id']}** [{n['kind']}] ({_codes(n)}): {n['text']['en']}{_who(n)}")
    L += ["", "## All notes by kind", ""]
    for kind in KINDS:
        rows = [n for n in notes if n["kind"] == kind]
        if not rows:
            continue
        L += [f"### {kind}", "", "| Note | Datasets | Public | Text (en) |", "|---|---|---|---|"]
        for n in rows:
            text = n["text"]["en"].replace("|", "\\|")
            L.append(f"| {n['id']} | {_codes(n, 4)} | {'yes' if n.get('public') else 'no'} | {text} |")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--notes", default=str(NOTES_PATH))
    ap.add_argument("--out", default=str(REPO / "docs" / "reports" / "ins-notes.md"))
    a = ap.parse_args(argv)
    Path(a.out).write_text(render(load(Path(a.notes))), encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
