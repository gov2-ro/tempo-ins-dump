"""AQ-06B: release-check's candidate smoke without Docker, and its guards.

The checks themselves run against a staged generation (`release-check.py --local`; see
docs/plans/ask-and-public-mcp/remaining/aq-06b-record.md). Here: the local server runs like the
image with no inherited switches or provider keys, the MCP run has the separate-origin shape, and
--docker refuses a stage the image would not contain.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def rc():
    spec = importlib.util.spec_from_file_location("release_check_06b", ROOT / "scripts" / "release-check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_local_candidate_runs_like_the_image_without_inherited_switches_or_keys(rc, tmp_path, monkeypatch):
    seen = {}

    class FakePopen:
        def __init__(self, cmd, cwd, env, stdout, stderr):
            seen.update(cmd=cmd, cwd=cwd, env=env)

    monkeypatch.setattr(rc.subprocess, "Popen", FakePopen)
    for k, v in {"TEMPO_ASK_ENABLED": "1", "TEMPO_ASK_BYOK_ENABLED": "1", "TEMPO_MCP_ENABLED": "true",
                 "ANTHROPIC_API_KEY": "sk-ant-x", "OPENROUTER_API_KEY": "sk-or-x", "PATH_HINT": "kept"}.items():
        monkeypatch.setenv(k, v)
    rc._local_server(tmp_path / "stage", 8301, {"TEMPO_MCP_ENABLED": "true"}, tmp_path / "log")
    env = seen["env"]
    assert not [k for k in env if k.endswith("_API_KEY")]                    # no model provider reachable
    assert "TEMPO_ASK_ENABLED" not in env and "TEMPO_ASK_BYOK_ENABLED" not in env
    assert env["TEMPO_MCP_ENABLED"] == "true" and env["PATH_HINT"] == "kept"
    assert env["TEMPO_DATA_DIR"] == str((tmp_path / "stage").resolve())     # not fly.toml's /app/data
    for k, v in rc.fly_env().items():
        if k != "TEMPO_DATA_DIR":
            assert env[k] == v
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert '"--workers", "1"' in dockerfile and seen["cmd"][seen["cmd"].index("--workers") + 1] == "1"
    assert seen["cmd"][1:4] == ["-m", "uvicorn", "app.main:app"] and seen["cwd"] == rc.ROOT


def test_the_mcp_run_has_the_separate_origin_shape(rc):
    env = rc.mcp_run_env(8302)
    assert env["TEMPO_MCP_ENABLED"] == "true" and env["TEMPO_PUBLIC_BASE_URL"] == "http://127.0.0.1:8302"
    assert env["TEMPO_CORS_ORIGINS"] == env["TEMPO_PUBLIC_SITE_URL"] == rc.SITE_ORIGIN
    assert rc.FOREIGN_ORIGIN != rc.SITE_ORIGIN
    assert not [k for k in env if k.startswith("TEMPO_ASK")]                  # Ask stays off in the MCP run


def test_docker_refuses_a_stage_the_image_would_not_contain(rc, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(rc.subprocess, "run", lambda *a, **k: calls.append(a) or None)
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"generation": {"id": "g"}}))
    rep = rc.Report()
    assert rc.docker_smoke(rep, tmp_path, 8303) is None
    assert rep.failures and "Dockerfile COPY" in rep.failures[0] and calls == []   # nothing built or run


def test_the_image_copies_every_root_level_module_the_app_imports():
    """`--local` runs from the checkout, where every root module imports; the image has only what the
    Dockerfile copies. A missing one (sdmx_labels, 2026-10-27) only showed when the image would not start."""
    import ast
    local = {p.stem for p in ROOT.glob("*.py")}
    needed = set()
    for f in (ROOT / "app").rglob("*.py"):
        if "_obsolete" in f.parts:
            continue
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                needed |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                needed.add(n.module.split(".")[0])
    copied = {line.split()[1] for line in (ROOT / "Dockerfile").read_text().splitlines()
              if line.startswith("COPY ") and line.split()[1].endswith(".py")}
    ignored = (ROOT / ".dockerignore").read_text().split()
    missing = sorted(m for m in needed & local if f"{m}.py" not in copied or f"{m}.py" in ignored)
    assert missing == [], f"the image would fail to import: {missing}"
    assert "sdmx_labels" in needed                                       # the guard sees real imports
