"""County tile map and choropleth steps (app/static/js/county-tiles.js), run through Node."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

LOAD = ("const fs=require('fs'),vm=require('vm');"
        "vm.runInThisContext(fs.readFileSync('app/static/js/county-tiles.js','utf8'));")


def _run(script):
    r = subprocess.run([NODE, "-e", LOAD + script], cwd=ROOT, env=os.environ,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    return r.stdout


def _js(expr):
    return json.loads(_run(f"console.log(JSON.stringify({expr}))"))


def _tiles():
    return _js("CountyTiles.TILES")


def test_tiles_shape():
    t = _tiles()
    assert len(t) == 42
    slugs = [v[0] for v in t.values()]
    cells = [(v[1], v[2]) for v in t.values()]
    assert len(set(slugs)) == 42
    assert len(set(cells)) == 42
    assert all(1 <= c <= 9 and 1 <= r <= 7 for c, r in cells)


def test_steps_quartiles():
    r = _js("(()=>{const s=CountyTiles.steps([1,2,3,4,5,6,7,8]);"
            "return {b:s.breaks,min:s.min,max:s.max,st:[1,2,3,4,5,6,7,8].map(s.stepOf)}})()")
    # sorted idx floor(8k/4) = 2,4,6 -> 3,5,7
    assert r == {"b": [3, 5, 7], "min": 1, "max": 8, "st": [0, 0, 1, 1, 2, 2, 3, 3]}


def test_steps_rounds_two_sig_figs():
    r = _js("CountyTiles.steps([100000,200000,437123,500000,600000,1716000,1800000,2500000]).breaks")
    # idx 2,4,6 -> 437123, 600000, 1800000
    assert r == [440000, 600000, 1800000]
    r = _js("CountyTiles.steps([1,1716000,1716000,1716000]).breaks")
    assert r == [1700000]


def test_steps_degenerate_and_nonfinite():
    r = _js("(()=>{const e=CountyTiles.steps([]),q=CountyTiles.steps([5,5,5]);"
            "return {e:[e.breaks,e.stepOf(3),e.min,e.max],q:[q.breaks,q.stepOf(5)],"
            "n:CountyTiles.steps([NaN,Infinity,null,1,2,3,4]).breaks,"
            "nv:CountyTiles.steps([1,2,3,4]).stepOf(NaN)}})()")
    assert r["e"] == [[], 0, None, None]
    assert r["q"] == [[], 0]
    assert r["n"] == [2, 3, 4]  # only the finite 1..4 count: idx 1,2,3
    assert r["nv"] is None


@pytest.mark.parametrize("name,slug", [
    ("Municipiul Bucuresti", "municipiul-bucuresti"),
    ("Satu Mare", "satu-mare"),
    ("Bistrița-Năsăud", "bistrita-nasaud"),
    ("Regiunea Nord-Vest", "nord-vest"),
    ("Caraș-Severin", "caras-severin"),
])
def test_slugify(name, slug):
    assert _js(f"CountyTiles.slugify({json.dumps(name)})") == slug


@pytest.mark.corpus
def test_tiles_match_api():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.place_service import slugify

    client = TestClient(app)
    tile_slugs = {v[0] for v in _tiles().values()}
    places = client.get("/api/places").json()["places"]
    counties = {p["slug"] for p in places if p["type"] == "county"}
    assert tile_slugs == counties

    pop = client.get("/api/reference/population", params={"level": "county"}).json()["population"]
    assert {slugify(n) for n in pop} == tile_slugs
    # The page matches area names in the browser: the JS slugify must agree.
    assert set(_js(f"{json.dumps(sorted(pop))}.map(CountyTiles.slugify)")) == tile_slugs
    assert len(pop) == 42
