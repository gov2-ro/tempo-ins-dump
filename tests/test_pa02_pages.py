"""PA-02c: canonical dataset pages with meaningful initial HTML, sitemap, robots."""
import json
import re

import pytest

from fix02b_corpus import make_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    return make_client(tmp_path, monkeypatch)


def _robots(h):
    return re.search(r'<meta name="robots" content="([^"]+)">', h).group(1)


def test_canonical_page_has_content_without_javascript(client):
    r = client.get("/dataset/INCX")
    assert r.status_code == 200
    h = r.text
    assert _robots(h) == "index, follow"
    assert re.search(r'<link rel="canonical" href="http://testserver/dataset/INCX">', h)
    assert "<title>Venitul disponibil pe sexe (INCX) — INS+</title>" in h
    ssr = re.search(r'<section class="dbv2-ssr".*?</section>', h, re.S).group(0)
    assert "adulti-echivalent" in ssr and "Definiție" in ssr   # the definition
    assert "2023 – 2024" in ssr                              # actual periods
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', h, re.S).group(1))
    assert ld["@type"] == "Dataset" and ld["identifier"] == "INCX"
    assert ld["temporalCoverage"] == "2023/2024" and "license" not in ld
    assert h.count('name="robots"') == 1


@pytest.mark.parametrize("url", ["/dataset-v2.html?code=INCX", "/dataset/INCX?f=%7B%7D",
                                 "/dataset/INCX?place=county:cluj"])
def test_aliases_and_filtered_states_are_not_indexed(client, url):
    h = client.get(url).text
    assert _robots(h) == "noindex, follow"
    assert '<link rel="canonical" href="http://testserver/dataset/INCX">' in h


def test_unknown_dataset_is_404(client):
    assert client.get("/dataset/NOPE").status_code == 404
    assert client.get("/dataset/bad%20code").status_code == 404


def test_english_page(client):
    h = client.get("/dataset/INCX?lang=en").text
    assert '<html lang="en">' in h and "Periods with data" in h


def test_sitemap_lists_canonical_urls_only(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    locs = re.findall(r"<loc>([^<]+)</loc>", r.text)
    assert "http://testserver/dataset/INCX" in locs and "http://testserver/" in locs
    assert not any("?" in u for u in locs)


def test_robots_points_to_sitemap(client):
    t = client.get("/robots.txt").text
    assert "Sitemap: http://testserver/sitemap.xml" in t and "Disallow: /api/" in t
