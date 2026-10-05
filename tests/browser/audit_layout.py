"""FIX-07 browser audit: document overflow, control reachability, console errors.

Needs a running app (default http://127.0.0.1:8097) and playwright (python).
Usage: python tests/browser/audit_layout.py [--base URL] [--shots DIR] [--quick]
Assertions are about scrollWidth <= innerWidth and controls being inside the
viewport or inside a scrollable bounded container -- never overflow:hidden.
"""
import argparse, os, sys
from playwright.sync_api import sync_playwright

PAGES = {
    "home": "/",
    "v1-POP107A": "/?code=POP107A",
    "v1-long": "/?code=TUR104B",
    "v2-POP107A": "/dataset-v2.html?code=POP107A",
    "v2-long": "/dataset-v2.html?code=TUR104B",
    "places": "/places",
    "place-bihor": "/place/county/bihor",
}
VIEWPORTS = [320, 390, 768, 1440]
# favicon: fixed separately; view-profiles/<code>.json: optional probe, 404 = "no profile" (api.js getViewProfile)
IGNORE = ("favicon", "view-profiles", "Failed to load resource")

# Interactive elements whose right edge is past the viewport and which are not
# inside a bounded scroll container (overflow-x auto/scroll that really scrolls).
JS_OVERFLOW = """() => {
  const W = innerWidth, bad = [];
  const inScroller = el => { for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if ((o === 'auto' || o === 'scroll') && p.scrollWidth > p.clientWidth) return true; }
      return false; };
  document.querySelectorAll('body *').forEach(el => {
    if (!['BUTTON','A','INPUT','SELECT'].includes(el.tagName)) return;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.position === 'fixed') return;
    if ((r.right > W + 1 || r.left < -1) && !inScroller(el))
      bad.push(el.tagName + '#' + el.id + '.' + String(el.className).slice(0, 40) + ' right=' + Math.round(r.right));
  });
  return {sw: document.documentElement.scrollWidth, W, unreachable: bad.slice(0, 8)};
}"""


def run(base, shots, quick):
    fails = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, path in PAGES.items():
            for w in VIEWPORTS:
                combos = [("ro", "light")] if quick else [("ro", "light"), ("en", "dark")]
                for lang, theme in combos:
                    ctx = b.new_context(viewport={"width": w, "height": 900})
                    ctx.add_init_script(
                        f"localStorage.setItem('lens_lang','{lang}');localStorage.setItem('lens_theme','{theme}')")
                    pg = ctx.new_page()
                    errs = []
                    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
                    pg.on("pageerror", lambda e: errs.append(str(e)))
                    pg.on("requestfailed", lambda r: errs.append("REQFAIL " + r.url))
                    pg.on("response", lambda r: errs.append(f"{r.status} {r.url}") if r.status >= 400 else None)
                    pg.goto(base + path, wait_until="networkidle")
                    pg.wait_for_timeout(1200)
                    o = pg.evaluate(JS_OVERFLOW)
                    errs = [e for e in errs if not any(i in e for i in IGNORE)]
                    ok = o["sw"] <= o["W"] and not o["unreachable"] and not errs
                    fails += (not ok)
                    print(f"{'OK  ' if ok else 'FAIL'} {name:12} {w:5} {lang} {theme:5} scrollWidth={o['sw']}"
                          + (f" unreachable={o['unreachable']}" if o["unreachable"] else "")
                          + (f" errors={errs[:3]}" if errs else ""))
                    if shots:
                        pg.screenshot(path=f"{shots}/{name}-{w}-{lang}-{theme}.png", full_page=False)
                    ctx.close()
        b.close()
    return fails


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8097")
    ap.add_argument("--shots")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    if a.shots:
        os.makedirs(a.shots, exist_ok=True)
    sys.exit(1 if run(a.base, a.shots, a.quick) else 0)
