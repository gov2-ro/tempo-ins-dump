"""Shared pytest config. Tests marked `corpus` need the real corpus and are
skipped (not passed) on a clean checkout; synthetic tests always run."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_DATA = Path(os.environ.get("TEMPO_DATA_DIR", ROOT / "data"))
HAVE_CORPUS = (_DATA / "corpus" / "metadata.duckdb").exists()


def pytest_collection_modifyitems(config, items):
    if HAVE_CORPUS:
        return
    skip = pytest.mark.skip(reason="real corpus not present (data/corpus/metadata.duckdb)")
    for item in items:
        if "corpus" in item.keywords:
            item.add_marker(skip)
