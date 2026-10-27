"""AQ-01C: place profiles are built one at a time and kept per generation.

A first profile build held ~270 MB at 512 MiB, and five at once filled the machine (PA-04 workload).
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers import places


@pytest.fixture
def built(monkeypatch):
    calls = []

    def build(place_type, slug):
        calls.append((place_type, slug))
        time.sleep(0.05)
        return {"place": {"type": place_type, "slug": slug}, "n": len(calls)}

    monkeypatch.setattr(places, "_build_place_profile", build)
    monkeypatch.setattr(places, "_profiles", places.OrderedDict())
    monkeypatch.setattr(places, "_build_slots", threading.BoundedSemaphore(1))
    gen = {"id": "gen-a"}
    monkeypatch.setattr(places.generation, "current", lambda: dict(gen))
    return calls, gen


def test_a_profile_is_built_once_per_generation(built):
    calls, gen = built
    a = places.get_place_profile("county", "cluj")
    assert places.get_place_profile("county", "cluj") is a and len(calls) == 1
    places.get_place_profile("county", "iasi")
    assert len(calls) == 2
    gen["id"] = "gen-b"                                   # a new generation never serves the old profile
    b = places.get_place_profile("county", "cluj")
    assert b is not a and b["n"] == 3 and len(calls) == 3


def test_concurrent_requests_for_one_place_build_it_once(built):
    calls, _ = built
    out = []
    ts = [threading.Thread(target=lambda: out.append(places.get_place_profile("county", "bihor"))) for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(calls) == 1 and len(out) == 5 and all(o is out[0] for o in out)


def test_builds_never_overlap(built, monkeypatch):
    calls, _ = built
    active, peak, lock = [0], [0], threading.Lock()

    def build(place_type, slug):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.03)
        with lock:
            active[0] -= 1
        return {"slug": slug}

    monkeypatch.setattr(places, "_build_place_profile", build)
    ts = [threading.Thread(target=places.get_place_profile, args=("county", f"c{i}")) for i in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert peak[0] == 1


def test_no_free_slot_in_time_is_a_503_with_retry_after(built, monkeypatch):
    monkeypatch.setattr(places.config, "PLACE_WAIT_SECONDS", 0.05)
    assert places._build_slots.acquire(timeout=1)
    try:
        with pytest.raises(HTTPException) as e:
            places.get_place_profile("county", "arad")
    finally:
        places._build_slots.release()
    assert e.value.status_code == 503 and e.value.headers == {"Retry-After": "10"}
    assert places.get_place_profile("county", "arad")["place"]["slug"] == "arad"   # the slot is usable again


def test_an_unknown_place_is_not_cached_and_frees_the_slot(built, monkeypatch):
    def build(place_type, slug):
        raise HTTPException(404, "Place not found")

    monkeypatch.setattr(places, "_build_place_profile", build)
    for _ in range(2):
        with pytest.raises(HTTPException) as e:
            places.get_place_profile("county", "nowhere")
        assert e.value.status_code == 404
    assert len(places._profiles) == 0 and places._build_slots.acquire(timeout=0.1)
    places._build_slots.release()


def test_the_cache_is_bounded(built, monkeypatch):
    calls, _ = built
    monkeypatch.setattr(places.config, "PLACE_CACHE_ENTRIES", 2)
    for s in ("a", "b", "c"):
        places.get_place_profile("county", s)
    assert len(places._profiles) == 2
    places.get_place_profile("county", "a")                  # evicted first, so built again
    assert len(calls) == 4


def test_the_main_duckdb_budget_defaults_to_160mb():
    env = {k: v for k, v in os.environ.items() if k != "TEMPO_DB_MEMORY"}
    out = subprocess.run([sys.executable, "-c", "import app.db as d; print(d.DB_MEMORY)"], env=env,
                         capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent))
    assert out.stdout.strip() == "160MB", out.stderr


def test_the_public_mcp_operator_profile_is_valid_and_only_raises_the_scan_cap():
    from app.services.public_mcp import McpSettings
    root = Path(__file__).resolve().parent.parent
    env = dict(line.split("=", 1) for line in (root / "scripts/deploy/fly/mcp-public.env").read_text().splitlines()
               if line.strip() and not line.startswith("#"))
    s = McpSettings.from_env(env, base_url=env["TEMPO_PUBLIC_BASE_URL"])
    d = McpSettings.from_env({"TEMPO_MCP_ENABLED": "true"}, base_url=env["TEMPO_PUBLIC_BASE_URL"])
    assert s.enabled and s.max_scan_rows == 5_000_000 and not s.local_test
    assert s.allowed_hosts == ("api-ins.gov2.ro",) and s.allowed_origins == ("https://api-ins.gov2.ro",)
    changed = {k for k in vars(s) if getattr(s, k) != getattr(d, k)}
    assert changed == {"max_scan_rows"}                   # every other limit stays at its measured default
    assert 3_898_870 <= s.max_scan_rows < 8_662_140       # admits *_grupe_localitate, not *_varste_judet


def test_the_place_recipe_cache_keeps_only_what_kpis_read_and_one_generation(monkeypatch):
    from app.services import place_service as P
    full = {"recipe": {"id": "r", "kind": "weighted_mean", "value_source": None, "definition": "x" * 100},
            "years_available": ["2023", "2024"], "year": "2024",
            "rows": [{"geo_id": "CJ", "value": 1.5, "weight_total": 10, "label": "Cluj", "inputs": [1, 2]}],
            "excluded": [{"geo_id": "B", "reason": "missing_input", "bounds": [1, 2]}],
            "aggregates": [{"geo_id": "total", "value": 2.0, "inputs": [3]}],
            "inputs": [[1] * 1000], "sources": [{"table": [[0] * 1000]}], "value_source": None}
    slim = P._recipe_slim(full)
    assert set(slim) == {"recipe", "years_available", "rows", "excluded", "aggregates", "value_source"}
    assert slim["recipe"] == {"id": "r", "kind": "weighted_mean", "value_source": None}
    assert slim["rows"] == [{"geo_id": "CJ", "value": 1.5, "weight_total": 10}]
    assert slim["aggregates"] == [{"geo_id": "total", "value": 2.0}] and slim["excluded"] == full["excluded"]
    assert P._recipe_slim({"error": {"reason": "x"}}) == {"error": {"reason": "x"}}

    gen = {"id": "g1"}
    monkeypatch.setattr(P, "_recipe_cache", {})
    import app.services.generation as G
    import app.services.recipes as R
    monkeypatch.setattr(G, "current", lambda: dict(gen))
    monkeypatch.setattr(R, "run", lambda con, rid, year=None: full)
    monkeypatch.setattr(P, "get_conn", lambda: type("C", (), {"close": lambda self: None})())
    P._recipe_run("r", "2024")
    gen["id"] = "g2"
    P._recipe_run("r", "2024")
    assert list(P._recipe_cache) == [("g2", "r", "2024")]
