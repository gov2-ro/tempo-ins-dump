"""Canonical public pages, sitemap and robots (PA-02c, audit A12).

`/dataset/{code}` is the canonical URL of a dataset. It serves the v2 dashboard
with the dataset's title, definition, unit, coverage and source in the initial
HTML (readable without JavaScript), canonical/language links and schema.org
Dataset data. `/dataset-v2.html?code=` stays as an alias: same page, canonical
pointing at `/dataset/{code}`, not indexed. Filtered states (`f`, `g`, `t`)
are never indexed. No licence is asserted and INS is credited as the creator
of the data, not as endorsing this site.
"""
from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from app.config import PARQUET_DIR
from app.db import get_conn

router = APIRouter()

_STATIC = Path(__file__).parent.parent / "static"
_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_STATE_PARAMS = ("f", "g", "t", "place")
INS_URL = "http://statistici.insse.ro:8077/tempo-online/"


@lru_cache(maxsize=1)
def _template(mtime: float) -> str:
    return (_STATIC / "dataset-v2.html").read_text(encoding="utf-8")


def _page_template() -> str:
    p = _STATIC / "dataset-v2.html"
    return _template(p.stat().st_mtime)


def _facts(code: str, lang: str) -> dict | None:
    from app.services.concept_search import dataset_facts
    conn = get_conn()
    try:
        f = dataset_facts(conn, code, lang)
        if f:
            return f
        row = conn.execute(
            "SELECT matrix_name, matrix_name_en, definitie, ultima_actualizare "
            "FROM matrices WHERE matrix_code = ?", [code]).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    title = (row[1] if lang == "en" and row[1] else row[0]) or code
    return {"code": code, "title": title, "definition": row[2], "unit": None,
            "coverage": None, "source_updated": str(row[3]) if row[3] else None}


def _head(base: str, code: str, facts: dict, lang: str, indexable: bool, static: bool = False) -> str:
    canonical = f"{base}/dataset/{quote(code)}"
    e = html.escape
    desc = (facts.get("definition") or facts["title"]).strip()
    desc = re.sub(r"\s+", " ", desc)
    short = desc[:300] + ("…" if len(desc) > 300 else "")
    cov = facts.get("coverage") or {}
    ld = {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": f"{facts['title']} ({code})",
        "description": desc if len(desc) >= 50 else f"{facts['title']}. INS TEMPO dataset {code}.",
        "identifier": code, "url": canonical, "inLanguage": lang,
        "isAccessibleForFree": True,
        "creator": {"@type": "Organization", "name": "Institutul Național de Statistică (INS)",
                    "url": "https://insse.ro"},
        "spatialCoverage": {"@type": "Place", "name": "Romania"},
    }
    if not static:      # the static site writes CSV in the browser: no download URL
        ld["distribution"] = [
            {"@type": "DataDownload", "encodingFormat": "text/csv",
             "contentUrl": f"{base}/api/datasets/{quote(code)}/download?format=csv"},
            {"@type": "DataDownload", "encodingFormat": "application/vnd.sdmx.genericdata+xml;version=2.1",
             "contentUrl": f"{base}/sdmx/2.1/data/INS,{quote(code)}/"},
        ]
    if cov.get("first") and cov.get("last"):
        ld["temporalCoverage"] = f"{cov['first']}/{cov['last']}"
    if facts.get("source_updated"):
        ld["dateModified"] = facts["source_updated"]
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    title = f"{facts['title']} ({code}) — INS+"
    return "\n".join([
        f"<title>{e(title)}</title>",
        f'<meta name="robots" content="{"index, follow" if indexable else "noindex, follow"}">',
        f'<meta name="description" content="{e(short)}">',
        f'<link rel="canonical" href="{e(canonical)}">',
        f'<link rel="alternate" hreflang="ro" href="{e(canonical)}">',
        f'<link rel="alternate" hreflang="en" href="{e(canonical)}?lang=en">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(short)}">',
        f'<meta property="og:url" content="{e(canonical)}">',
        '<meta property="og:type" content="website">',
        f'<script type="application/ld+json">{ld_json}</script>',
    ])


def _summary(code: str, facts: dict, lang: str, static: bool = False) -> str:
    """Server-rendered dataset facts, readable without JavaScript."""
    e = html.escape
    en = lang == "en"
    cov = facts.get("coverage") or {}
    rows = [(("Cod" if not en else "Code"), code)]
    if facts.get("unit"):
        rows.append(("Unitate de măsură" if not en else "Unit", facts["unit"]))
    if cov.get("first"):
        freq = {"annual": "anual", "monthly": "lunar", "quarterly": "trimestrial"}.get(cov.get("frequency"), cov.get("frequency")) \
            if not en else cov.get("frequency")
        rows.append(("Perioade cu date" if not en else "Periods with data",
                     f"{cov['first']} – {cov['last']} ({freq}, {cov.get('periods')})"))
    if facts.get("source_updated"):
        rows.append(("Actualizat la sursă" if not en else "Source updated", facts["source_updated"]))
    rows.append(("Sursa" if not en else "Source", "INS — TEMPO Online"))
    dl = "".join(f"<dt>{e(k)}</dt><dd>{e(str(v))}</dd>" for k, v in rows)
    definition = facts.get("definition")
    return (f'<section class="dbv2-ssr" id="dbv2-ssr" aria-label="{"Despre set" if not en else "About this dataset"}">'
            f'<h1 class="dbv2-ssr-title">{e(facts["title"])}</h1>'
            + (_definition_html(definition, en) if definition else "")
            + _notes_html(code, en)
            + f'<dl class="dbv2-ssr-facts">{dl}</dl>'
            + ('<p class="dbv2-ssr-links">'
               + ("" if static else f'<a href="/api/datasets/{quote(code)}/download?format=csv">CSV</a> · '
                                    f'<a href="/sdmx/2.1/data/INS,{quote(code)}/">SDMX</a> · ')
               + f'<a href="{INS_URL}" rel="noopener">TEMPO Online</a></p>')
            + "</section>")


def _notes_html(code: str, en: bool) -> str:
    """Curated notes (series breaks, coverage, caveats) under the definition."""
    from app.services.dataset_notes import for_code
    notes = for_code(code, "en" if en else "ro")
    if not notes:
        return ""
    items = "".join(f'<li data-kind="{html.escape(n["kind"])}">{html.escape(n["text"])}</li>' for n in notes)
    return (f'<div class="dbv2-ssr-notes"><strong>{"Note" if not en else "Notes"}:</strong>'
            f'<ul>{items}</ul></div>')


def _definition_html(definition: str, en: bool) -> str:
    """First sentence visible, full official text one click away (long INS
    definitions would otherwise push the chart off a phone screen)."""
    e = html.escape
    text = re.sub(r"\s+", " ", definition).strip()
    first = re.split(r"(?<=[.;])\s", text, maxsplit=1)[0]
    if len(first) > 220:
        first = first[:220].rsplit(" ", 1)[0] + "…"
    label = "Definiție" if not en else "Definition"
    if first == text:
        return f'<p class="dbv2-ssr-def"><strong>{label}:</strong> {e(text)}</p>'
    return (f'<details class="dbv2-ssr-def"><summary><strong>{label}:</strong> {e(first)} '
            f'<span class="dbv2-ssr-more">{"(mai mult)" if not en else "(more)"}</span></summary>'
            f'<p>{e(text)}</p></details>')


def dataset_page_html(code: str, lang: str, base: str, indexable: bool,
                      static: bool = False) -> str | None:
    """The dataset page with its facts in the HTML, or None for an unknown code.
    `static` drops the server-only links (CSV/SDMX endpoints) for the static site."""
    page = _page_template()
    facts = _facts(code, lang) if _CODE_RE.match(code or "") else None
    if not facts:
        return None
    page = re.sub(r"<title>.*?</title>\s*<meta name=\"robots\" content=\"noindex\">",
                  lambda _m: _head(base, code, facts, lang, indexable, static), page, count=1, flags=re.S)
    page = page.replace('<html lang="ro">', f'<html lang="{lang}">', 1)
    page = page.replace('<header class="dash-header" id="dbv2-header"></header>',
                        '<header class="dash-header" id="dbv2-header"></header>\n        '
                        + _summary(code, facts, lang, static), 1)
    return page


def render_dataset_page(request: Request, code: str, *, canonical_route: bool) -> Response:
    lang = "en" if request.query_params.get("lang") == "en" else "ro"
    indexable = canonical_route and not any(p in request.query_params for p in _STATE_PARAMS)
    page = dataset_page_html(code, lang, str(request.base_url).rstrip("/"), indexable)
    if page is None:
        return HTMLResponse(_page_template(), status_code=404)
    return HTMLResponse(page)


@router.get("/dataset/{code}", include_in_schema=False)
def dataset_page(request: Request, code: str):
    return render_dataset_page(request, code, canonical_route=True)


@router.get("/dataset-v2.html", include_in_schema=False)
def dataset_page_alias(request: Request):
    code = request.query_params.get("code") or ""
    if not code:
        return HTMLResponse(_page_template())     # the page shows "missing ?code="
    return render_dataset_page(request, code, canonical_route=False)


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request):
    """Home, places and one canonical URL per served dataset. No filtered or
    comparison states: those are not separate documents."""
    from app.services.place_service import slugify
    base = str(request.base_url).rstrip("/")
    conn = get_conn()
    try:
        has_canon = conn.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'matrices' AND column_name = 'is_canonical'").fetchone()[0]
        codes = conn.execute(
            "SELECT matrix_code, ultima_actualizare FROM matrices "
            + ("WHERE is_canonical " if has_canon else "") + "ORDER BY matrix_code").fetchall()
        places = conn.execute("""
            SELECT DISTINCT geo_level, geo_name_clean FROM dimension_options_parsed
            WHERE dim_type = 'geo' AND geo_level IN ('county', 'region', 'macroregion')
              AND geo_name_clean IS NOT NULL""").fetchall()
    finally:
        conn.close()

    def lastmod(v):
        m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", str(v or ""))
        return f"<lastmod>{m.group(3)}-{m.group(2)}-{m.group(1)}</lastmod>" if m else ""

    urls = [f"<url><loc>{html.escape(base)}/</loc></url>",
            f"<url><loc>{html.escape(base)}/places</loc></url>"]
    for level, name in sorted({(l, slugify(n)) for l, n in places}):
        urls.append(f"<url><loc>{html.escape(base)}/place/{level}/{html.escape(name)}</loc></url>")
    for code, upd in codes:
        if (PARQUET_DIR / f"{code}.parquet").exists():
            urls.append(f"<url><loc>{html.escape(base)}/dataset/{quote(code)}</loc>{lastmod(upd)}</url>")
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(urls) + "\n</urlset>\n")
    return Response(body, media_type="application/xml")


@router.get("/robots.txt", include_in_schema=False)
def robots(request: Request):
    base = str(request.base_url).rstrip("/")
    return PlainTextResponse(
        "User-agent: *\nDisallow: /api/\nDisallow: /sdmx/\nAllow: /\n"
        f"Sitemap: {base}/sitemap.xml\n")
