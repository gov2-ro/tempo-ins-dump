"""mcp-connect.html: the pre-rendered cards match js/mcp-connect.js and data/mcp-clients.csv."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "app" / "static" / "mcp-connect.html"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_prerendered_page_is_in_sync():
    r = subprocess.run([NODE, "scripts/build-mcp-connect.mjs", "--check"], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_page_has_content_without_javascript():
    html = PAGE.read_text(encoding="utf-8")
    cards = re.search(r"<!-- mcp:cards -->(.*?)<!-- /mcp:cards -->", html, re.S).group(1)
    assert cards.count('class="cc"') >= 30
    assert "claude mcp add --transport http --scope user ins-tempo https://api-ins.gov2.ro/mcp" in cards
    # Asset paths stay relative, so the page also works opened from disk.
    assert 'src="/js/' not in html and 'href="/css/' not in html
