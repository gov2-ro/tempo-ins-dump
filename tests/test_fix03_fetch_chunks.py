"""Stage 6: per-dimension chunking for INS's header-only answer to oversized dimensions.

EXP101F/EXP102F (1,261/1,274 options in one dimension) came back header-only and
were filed as "empty at source". Offline: a fake /pivot endpoint mimics INS.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
N_GROUPS = 650          # above both MAX_DIM_OPTIONS and what the fake INS accepts (500)
YEARS = [(1001, "Anul 2020"), (1002, "Anul 2021")]
HEADER = b"Grupe, Ani, Valoare\n"


def load():
    spec = importlib.util.spec_from_file_location("fetch_csv_chunks_t", ROOT / "6-fetch-csv.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def matrix_def(n_groups):
    return {
        "dimensionsMap": [
            {"label": "Grupe", "options": [{"label": "Total", "nomItemId": 0}] +
             [{"label": f"G{i}", "nomItemId": i} for i in range(1, n_groups + 1)]},
            {"label": "Ani", "options": [{"label": l, "nomItemId": i} for i, l in YEARS]},
        ],
        "details": {"matMaxDim": 2, "matUMSpec": 0},
    }


class FakeINS:
    """Header-only when a dimension carries more than `max_opts` ids, like INS."""

    def __init__(self, max_opts=500, fail_on=None, header_on=None):
        self.max_opts, self.fail_on, self.header_on = max_opts, fail_on, header_on
        self.calls = 0

    def __call__(self, url, json=None, **kw):
        self.calls += 1
        if self.fail_on == self.calls:
            raise ConnectionError("down")
        dims = [p.split(",") for p in json["encQuery"].split(":")]
        header = self.header_on.get(self.calls, HEADER) if self.header_on else HEADER
        if any(len(d) > self.max_opts for d in dims):
            body = HEADER
        else:
            body = header + b"".join(f"G{g}, {y}, {int(g) * 10 + int(y)}\n".encode()
                                     for g in dims[0] for y in dims[1])
        return type("R", (), {"content": body, "status_code": 200, "headers": {},
                              "raise_for_status": lambda self: None})()


@pytest.fixture
def stage6(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)            # stage 6 resolves data/ from cwd
    mod = load()
    monkeypatch.setattr(mod, "CHUNK_DELAY", 0)
    metas = tmp_path / "data" / "2-metas" / "ro"
    metas.mkdir(parents=True)
    return mod, metas


def write_meta(metas, code, n_groups):
    (metas / f"{code}.json").write_text(json.dumps(matrix_def(n_groups)))


def csv_rows(code):
    return Path(f"data/4-datasets/ro/{code}.csv").read_text().splitlines()


def test_generate_chunks_caps_each_dimension_and_covers_all_options(stage6):
    mod, _ = stage6
    opts = mod.query_dims_options(matrix_def(N_GROUPS))
    assert len(opts[0]) == N_GROUPS                  # exact "Total" dropped
    chunks = list(mod.generate_chunks(opts))
    assert all(len(c[0]) <= mod.DIM_CHUNK for c in chunks)
    seen = [o["nomItemId"] for c in chunks for o in c[0]]
    assert sorted(seen) == list(range(1, N_GROUPS + 1))   # each option exactly once
    assert all(len(c[1]) == 2 for c in chunks)


def test_header_only_big_dimension_is_refetched_in_chunks(stage6, monkeypatch):
    mod, metas = stage6
    write_meta(metas, "EXPBIG", N_GROUPS)
    ins = FakeINS()
    monkeypatch.setattr(mod.requests, "post", ins)
    assert mod.main(["--matrix", "EXPBIG", "--force"]) == 0
    rows = csv_rows("EXPBIG")
    assert rows[0] == HEADER.decode().strip()
    data = rows[1:]
    assert len(data) == N_GROUPS * 2 == len(set(data))     # complete, no duplicates
    assert "G137, 1002, 2372" in data                       # values pass through untouched
    assert not any(r.startswith("Total") for r in data)
    assert ins.calls == 1 + 7                               # one header-only answer, 7 chunks
    assert not list(Path("data/4-datasets/ro").glob("*.part"))


def test_failed_chunk_fails_the_matrix_and_leaves_no_file(stage6, monkeypatch):
    mod, metas = stage6
    write_meta(metas, "EXPBIG", N_GROUPS)
    monkeypatch.setattr(mod.requests, "post", FakeINS(fail_on=4))
    assert mod.main(["--matrix", "EXPBIG", "--force"]) == mod.EXIT_FETCH_FAILED == 1
    assert not Path("data/4-datasets/ro/EXPBIG.csv").exists()   # not "fetched" for the next run
    assert not list(Path("data/4-datasets/ro").glob("*.part"))


def test_chunk_with_different_header_fails(stage6, monkeypatch):
    mod, metas = stage6
    write_meta(metas, "EXPBIG", N_GROUPS)
    monkeypatch.setattr(mod.requests, "post", FakeINS(header_on={3: b"Other, Ani, Valoare\n"}))
    assert mod.main(["--matrix", "EXPBIG", "--force"]) == 1
    assert not Path("data/4-datasets/ro/EXPBIG.csv").exists()


def test_big_dimension_that_ins_accepts_stays_a_single_request(stage6, monkeypatch):
    mod, metas = stage6
    write_meta(metas, "INT400", 400)                 # >300 but accepted, like RSI101A (592)
    ins = FakeINS()
    monkeypatch.setattr(mod.requests, "post", ins)
    assert mod.main(["--matrix", "INT400", "--force"]) == 0
    assert ins.calls == 1
    assert len(csv_rows("INT400")) == 1 + 400 * 2


def test_small_dimensions_header_only_is_still_empty_dataset(stage6, monkeypatch):
    mod, metas = stage6
    write_meta(metas, "SMALL1", 20)
    monkeypatch.setattr(mod.requests, "post", FakeINS(max_opts=0))   # always header-only
    assert mod.main(["--matrix", "SMALL1", "--force"]) == mod.EXIT_EMPTY_DATASET
