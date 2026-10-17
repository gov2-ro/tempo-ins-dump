"""The AQ-02 task file (data/eval/ask_tasks.json): loading, validation and the text/number
helpers its checks use. Shared by the task-file tests and scripts/eval-ask-tasks.py, so what a test
accepts as a valid task is exactly what the runner replays.

Nothing here touches the app or a corpus; the registry's tool names are read only when the
caller does not pass them.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_PATH = ROOT / "data" / "eval" / "ask_tasks.json"
TASKSET_SCHEMA = "ask-tasks/1"
LANGS = ("ro", "en")
SURFACES = ("direct", "mcp")
ID_RE = re.compile(r"^[TX]\d{2}[A-Z]?$")
FIXTURE_KINDS = ("synthetic", "copied")
EXPECT_KEYS = {"outcome", "reasons", "verification", "tools", "calls", "numbers", "evidence", "qualifications",
               "forbidden", "answer", "limits", "raises", "mcp", "context", "table"}
STEP_KEYS = {"tool", "arguments", "follow", "provider", "raise", "cancel", "hold", "usage"}
PROVIDER_STEPS = ("length_empty", "length_text", "empty", "incomplete", "content_filter")
RAISE_STEPS = ("RateLimitError", "APITimeoutError", "APIConnectionError", "key_echo")
BEFORE_ACTIONS = ("advance_generation",)
DETECTIONS = ("withheld", "flagged", "accepted")
HARD = ("numerical_deviation", "unsafe_claim_accepted", "secret_leak")   # never averaged, never skipped
MISSING = object()


# ------------------------------------------------------------------ small utilities

def safe_eval(expr: str) -> float:
    """+ - * / and parentheses over number literals only: the arithmetic written next to an
    expected value, evaluated without Python's eval."""
    ops = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return float(n.value)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -ev(n.operand) if isinstance(n.op, ast.USub) else ev(n.operand)
        if isinstance(n, ast.BinOp) and type(n.op) in ops:
            return ops[type(n.op)](ev(n.left), ev(n.right))
        raise ValueError(f"unsupported expression element {type(n).__name__}")
    return ev(ast.parse(expr.strip(), mode="eval"))


def pointer(obj, path: str):
    """RFC 6901 pointer into dicts and lists; MISSING when it does not resolve."""
    if path in ("", "/"):
        return obj
    node = obj
    for part in path.lstrip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        try:
            node = node[int(part)] if isinstance(node, list) else node[part]
        except (KeyError, IndexError, ValueError, TypeError):
            return MISSING
    return node


def sha(text: str | bytes, n: int = 16) -> str:
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode("utf-8")).hexdigest()[:n]


def clip(text, n: int = 80):
    t = " ".join(str(text if text is not None else "").split())
    return t if len(t) <= n else t[:n].rstrip() + "…"


def norm(text) -> str:
    """Casefolded, accent-free, dash-normalised, single-spaced: how phrases and patterns match."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    t = t.replace("–", "-").replace("—", "-").replace("−", "-")
    return " ".join(t.split())


_NUM_RE = re.compile(r"(?<![\w.,/-])[-−]?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?(?!\w)|(?<![\w.,/-])[-−]?\d+(?:[.,]\d+)*(?!\w)")


def number_candidates(token: str) -> list[float]:
    """The values a numeral can mean: RO writes 1.010 / 4,91, EN writes 1,010 / 4.91; a lone
    separator before exactly three digits is ambiguous and yields both readings."""
    t = token.replace("−", "-").replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    neg = t.startswith("-")
    t = t.lstrip("-")
    out = []
    if "." in t and "," in t:
        dec = "." if t.rfind(".") > t.rfind(",") else ","
        out.append(t.replace("," if dec == "." else ".", "").replace(dec, "."))
    else:
        sep = "." if "." in t else "," if "," in t else None
        if sep is None:
            out.append(t)
        elif t.count(sep) > 1:
            out.append(t.replace(sep, ""))
        else:
            head, tail = t.split(sep)
            out.append(f"{head}.{tail}")
            if len(tail) == 3 and 1 <= len(head) <= 3:
                out.append(head + tail)
    vals = []
    for s in out:
        try:
            vals.append(-float(s) if neg else float(s))
        except ValueError:
            pass
    return vals


def numbers_in(text: str) -> list[tuple[str, list[float]]]:
    return [(m.group(0), number_candidates(m.group(0))) for m in _NUM_RE.finditer(text or "")]


def _decimals(token: str) -> int:
    m = re.search(r"[.,](\d+)$", token)
    return len(m.group(1)) if m and not (len(m.group(1)) == 3 and re.search(r"\d[.,]\d{3}$", token)) else 0


def matches_value(token: str, cands: list[float], value: float) -> bool:
    """The numeral states `value`: exactly for an integer, to the stated decimals otherwise."""
    for c in cands:
        if float(value).is_integer():
            if c == value:
                return True
        else:
            d = max(1, _decimals(token))
            if abs(c - value) <= 0.5 * 10 ** -d + 1e-12:
                return True
    return False


def states_number(text: str, value: float) -> bool:
    return any(matches_value(t, c, value) for t, c in numbers_in(text))


def stray_numbers(text: str, values: list[float], allowed: list[float]) -> list[str]:
    """Numerals of `text` that state none of the expected values and are not on the allowed list."""
    out = []
    for token, cands in numbers_in(text):
        if any(matches_value(token, cands, v) for v in values) or any(c == a for c in cands for a in allowed):
            continue
        out.append(token)
    return out


def phrase_in(text: str, phrases) -> str | None:
    t = norm(text)
    return next((p for p in phrases if norm(p) in t), None)


def pattern_in(text: str, patterns) -> str | None:
    t = norm(text)
    return next((p for p in patterns if re.search(p, t)), None)


# ------------------------------------------------------------------ task file

def load_taskset(path: Path = TASKS_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def turns_of(task: dict) -> list[dict]:
    """A task is one turn written inline or a list of turns; both read the same."""
    if "turns" in task:
        return task["turns"]
    return [{k: task[k] for k in ("prompt", "steps", "answer", "expect", "before", "usage", "shown") if k in task}]


def _check_steps(where, steps, tools, errs, *, allow_faults=True):
    if not isinstance(steps, list):
        errs.append(f"{where}: steps must be a list")
        return
    for i, s in enumerate(steps):
        w = f"{where}.steps[{i}]"
        if not isinstance(s, dict) or not (set(s) & {"tool", "follow", "provider", "raise", "cancel"}):
            errs.append(f"{w}: needs one of tool/follow/provider/raise/cancel")
            continue
        if set(s) - STEP_KEYS:
            errs.append(f"{w}: unknown keys {sorted(set(s) - STEP_KEYS)}")
        if "tool" in s and s["tool"] not in tools:
            errs.append(f"{w}: unknown tool {s['tool']!r}")
        if "tool" in s and not isinstance(s.get("arguments", {}), dict):
            errs.append(f"{w}: arguments must be an object")
        if "follow" in s:
            f = s["follow"]
            if not (isinstance(f, dict) and isinstance(f.get("call"), int) and str(f.get("path", "")).startswith("/")):
                errs.append(f"{w}: follow needs an integer call and a pointer path")
        if "provider" in s and s["provider"] not in PROVIDER_STEPS:
            errs.append(f"{w}: provider step must be one of {PROVIDER_STEPS}")
        if "raise" in s and s["raise"] not in RAISE_STEPS:
            errs.append(f"{w}: raise must be one of {RAISE_STEPS}")


def _check_expect(where, e, errs):
    if not isinstance(e, dict):
        errs.append(f"{where}: expect must be an object")
        return
    if set(e) - EXPECT_KEYS:
        errs.append(f"{where}: unknown expect keys {sorted(set(e) - EXPECT_KEYS)}")
    ids = set()
    for i, n in enumerate(e.get("numbers", [])):
        w = f"{where}.numbers[{i}]"
        for k in ("id", "call", "path", "value", "derivation"):
            if k not in n:
                errs.append(f"{w}: missing {k}")
        if n.get("id") in ids:
            errs.append(f"{w}: duplicate number id {n.get('id')!r}")
        ids.add(n.get("id"))
        if not str(n.get("path", "")).startswith("/"):
            errs.append(f"{w}: path must be a JSON pointer")
        try:
            got = safe_eval(str(n.get("derivation", "")))
            if not math.isclose(got, float(n["value"]), rel_tol=1e-9, abs_tol=float(n.get("tol", 0)) + 1e-9):
                errs.append(f"{w}: derivation {n['derivation']!r} = {got}, not {n['value']}")
        except (ValueError, SyntaxError, ZeroDivisionError, KeyError, TypeError) as ex:
            errs.append(f"{w}: derivation not evaluable ({ex})")
    for kind in ("qualifications", "forbidden"):
        for i, q in enumerate(e.get(kind, [])):
            w = f"{where}.{kind}[{i}]"
            if not q.get("id"):
                errs.append(f"{w}: missing id")
            for k in ("answer_any", "answer_pattern"):
                if k in q and not all(isinstance(q[k].get(lg), list) and q[k][lg] for lg in LANGS):
                    errs.append(f"{w}.{k}: needs a non-empty list for both ro and en")
            if kind == "forbidden" and not (q.get("answer_pattern") or q.get("numbers")):
                errs.append(f"{w}: needs answer_pattern or numbers")
            if kind == "forbidden" and q.get("on", "model") not in ("model", "visible"):
                errs.append(f"{w}: on must be model or visible")
            if kind == "forbidden":
                for rx in sum((q.get("answer_pattern") or {}).values(), []):
                    try:
                        re.compile(rx)
                    except re.error as ex:
                        errs.append(f"{w}: bad pattern {rx!r} ({ex})")
            if kind == "qualifications" and not (q.get("answer_any") or q.get("tool")):
                errs.append(f"{w}: needs answer_any or tool")


def validate_taskset(doc: dict, tool_names=None) -> list[str]:
    """Every problem in the task file (empty = valid): structure, stable IDs, RO/EN pairs,
    fixture and dataset references, scripted steps, and each expected number's derivation."""
    if tool_names is None:
        from app.services.tools import registry
        tool_names = registry.tool_names()
    errs: list[str] = []
    if doc.get("schema") != TASKSET_SCHEMA:
        errs.append(f"schema must be {TASKSET_SCHEMA!r}")
    if not isinstance(doc.get("version"), str) or not doc.get("version"):
        errs.append("version must be a non-empty string")
    fixtures = doc.get("fixtures") or {}
    for fid, f in fixtures.items():
        if f.get("kind") not in FIXTURE_KINDS:
            errs.append(f"fixtures.{fid}: kind must be one of {FIXTURE_KINDS}")
        if f["kind"] == "synthetic" and not f.get("datasets"):
            errs.append(f"fixtures.{fid}: synthetic fixtures list their datasets")
        if f["kind"] == "copied" and not f.get("generation_prefix"):
            errs.append(f"fixtures.{fid}: copied fixtures name the generation_prefix they were hand-checked on")
    seen = set()
    tasks = doc.get("tasks") or []
    if not tasks:
        errs.append("no tasks")
    for t in tasks:
        tid = t.get("id", "?")
        w = f"task {tid}"
        if not ID_RE.match(str(tid)):
            errs.append(f"{w}: id must match {ID_RE.pattern}")
        if tid in seen:
            errs.append(f"{w}: duplicate id")
        seen.add(tid)
        for k in ("title", "category", "fixture", "surfaces"):
            if not t.get(k):
                errs.append(f"{w}: missing {k}")
        if t.get("fixture") not in fixtures:
            errs.append(f"{w}: unknown fixture {t.get('fixture')!r}")
        if not set(t.get("surfaces", [])) <= set(SURFACES) or not t.get("surfaces"):
            errs.append(f"{w}: surfaces must be a non-empty subset of {SURFACES}")
        if fixtures.get(t.get("fixture"), {}).get("kind") == "copied" and t.get("surfaces") != ["direct"]:
            errs.append(f"{w}: tasks on a copied generation run on the direct surface only")
        if ("turns" in t) == ("prompt" in t):
            errs.append(f"{w}: give either turns or an inline prompt/steps/answer/expect")
        turns = turns_of(t)
        fix = fixtures.get(t.get("fixture")) or {}
        for i, turn in enumerate(turns):
            tw = f"{w}.turn{i}"
            p = turn.get("prompt") or {}
            if not all(isinstance(p.get(lg), str) and p[lg].strip() for lg in LANGS):
                errs.append(f"{tw}: prompt needs ro and en text")
            if "direct" in t.get("surfaces", []) and not all(
                    isinstance((turn.get("answer") or {}).get(lg), str) for lg in LANGS):
                errs.append(f"{tw}: answer needs ro and en text")
            _check_steps(tw, turn.get("steps", []), tool_names, errs)
            _check_expect(f"{tw}.expect", turn.get("expect", {}), errs)
            for ds in (a for s in turn.get("steps", []) for a in [s.get("arguments", {}).get("dataset")] if a):
                if fix.get("kind") == "synthetic" and ds not in fix.get("datasets", []):
                    errs.append(f"{tw}: dataset {ds!r} is not in fixture {t.get('fixture')!r}")
            for b in turn.get("before", []):
                if b.get("action") not in BEFORE_ACTIONS:
                    errs.append(f"{tw}: before action must be one of {BEFORE_ACTIONS}")
        nids = set()
        for n in t.get("negatives", []):
            nw = f"{w}.negative {n.get('id')}"
            if not n.get("id") or n["id"] in nids:
                errs.append(f"{nw}: missing or duplicate id")
            nids.add(n.get("id"))
            if not all(isinstance((n.get("answer") or {}).get(lg), str) for lg in LANGS):
                errs.append(f"{nw}: answer needs ro and en text")
            d = n.get("detect") or {}
            if d.get("app") not in DETECTIONS or not d.get("fails"):
                errs.append(f"{nw}: detect needs app in {DETECTIONS} and the check ids that must fail")
            if d.get("app") == "accepted" and not (n.get("known_limitation") and d.get("hard")):
                errs.append(f"{nw}: an accepted wrong answer needs a known_limitation note and the hard categories it triggers")
        kf = t.get("known_failure")
        if kf and not (kf.get("package") and kf.get("categories") and kf.get("note")):
            errs.append(f"{w}: known_failure needs package, categories and note")
        pin = t.get("pinned")
        if pin:
            if fixtures.get(pin.get("fixture"), {}).get("kind") != "copied":
                errs.append(f"{w}: pinned.fixture must name a copied fixture")
            if set(pin.get("surfaces", ["direct"])) != {"direct"}:
                errs.append(f"{w}: pinned cases run on the direct surface only")
            pt = {**t, **{k: v for k, v in pin.items() if k != "fixture"}}
            pt.pop("pinned", None)
            for i, turn in enumerate(turns_of(pt)):
                _check_steps(f"{w}.pinned.turn{i}", turn.get("steps", []), tool_names, errs)
                _check_expect(f"{w}.pinned.turn{i}.expect", turn.get("expect", {}), errs)
    return errs
