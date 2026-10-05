"""FIX-07 interaction audit: keyboard flow, focus visibility, chart switching,
URL-state round trip, resize after layout/theme change, no console errors.

Needs a running app (default http://127.0.0.1:8097) and python playwright.
Usage: python tests/browser/audit_interactions.py [--base URL] [--shots DIR]
"""
import argparse, os, sys
from playwright.sync_api import sync_playwright

IGNORE = ("favicon", "view-profiles", "Failed to load resource")
fails = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def new_page(b, w, lang="ro", theme="light", dsf=1, h=900):
    ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=dsf)
    ctx.add_init_script(f"localStorage.setItem('lens_lang','{lang}');localStorage.setItem('lens_theme','{theme}')")
    pg = ctx.new_page()
    pg.errs = []
    pg.on("console", lambda m: pg.errs.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: pg.errs.append(str(e)))
    pg.on("requestfailed", lambda r: pg.errs.append("REQFAIL " + r.url))
    pg.on("response", lambda r: pg.errs.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    return pg


def errs(pg):
    return [e for e in pg.errs if not any(i in e for i in IGNORE)]


def sw(pg):
    return pg.evaluate("[document.documentElement.scrollWidth, innerWidth]")


FOCUS_JS = """() => { const e = document.activeElement; if (!e || e === document.body) return null;
  const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
  return {tag: e.tagName, id: e.id, cls: String(e.className).slice(0, 40), left: r.left, right: r.right,
          outline: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 }; }"""


def tab_flow(pg, steps=90):
    seen = []
    pg.mouse.click(2, 2)  # park focus at document start
    for _ in range(steps):
        pg.keyboard.press("Tab")
        pg.wait_for_timeout(220)  # buttons use transition:all, which animates outline-width from 0
        f = pg.evaluate(FOCUS_JS)
        if f:
            seen.append(f)
    return seen


def run_v1(b, w, shots):
    tag = f"v1@{w}"
    pg = new_page(b, w)
    pg.goto(f"{BASE}/?code=POP107A", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    seen = tab_flow(pg)
    check(any("ct-btn" in f["cls"] for f in seen), f"{tag} tab reaches chart pills")
    check(any("period-btn" in f["cls"] for f in seen), f"{tag} tab reaches period navigation")
    check(any("dim-picker-select" in f["cls"] for f in seen), f"{tag} tab reaches dimension selectors")
    check(all(f["outline"] for f in seen if f["tag"] in ("BUTTON", "A", "SELECT")),
          f"{tag} every focused control shows a focus outline")
    check(all(f["left"] >= -1 and f["right"] <= w + 1 for f in seen), f"{tag} focused controls inside viewport")
    # keyboard-operate the chart pills: focus 2nd snapshot pill, press Enter
    pills = pg.locator("#snapshot-pills .ct-btn")
    n = pills.count()
    if n > 1:
        pills.nth(1).focus()
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(600)
        check(pills.nth(1).get_attribute("aria-pressed") == "true", f"{tag} Enter on chart pill selects it (aria-pressed)")
        check(pills.nth(0).get_attribute("aria-pressed") == "false", f"{tag} previous pill deselected")
        url = pg.url
        pg.goto(url, wait_until="networkidle")
        pg.wait_for_timeout(1200)
        again = pg.locator("#snapshot-pills .ct-btn").nth(1).get_attribute("aria-pressed")
        check(again == "true", f"{tag} URL round trip restores chart pill ({url.split('?')[-1][:60]})")
    # period nav via keyboard
    nxt = pg.locator(".period-btn").first
    if nxt.count():
        before = pg.locator(".period-label").inner_text()
        pg.locator(".period-btn").nth(1).focus()
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(500)
        prev = pg.locator(".period-btn").first
        check(prev.get_attribute("aria-label") is not None, f"{tag} period buttons have accessible names")
    # theme switch + sidebar toggle -> chart canvas matches container
    pg.click("#theme-toggle")
    pg.wait_for_timeout(500)
    pg.click("#sidebar-toggle")
    pg.wait_for_timeout(600)
    ok = pg.evaluate("""() => [...document.querySelectorAll('.chart-container')].filter(c => c.offsetWidth)
        .every(c => { const cv = c.querySelector('canvas,svg'); return !cv || Math.abs(cv.getBoundingClientRect().width - c.clientWidth) < 4; })""")
    check(ok, f"{tag} chart canvas tracks container after theme+sidebar change")
    check(sw(pg)[0] <= sw(pg)[1], f"{tag} no horizontal overflow after theme+sidebar change {sw(pg)}")
    pg.click("#lang-toggle")
    pg.wait_for_timeout(800)
    check(not errs(pg), f"{tag} no console/request errors ({errs(pg)[:2]})")
    if shots:
        pg.screenshot(path=f"{shots}/inter-v1-{w}.png")
    pg.context.close()


def run_v2(b, w, shots):
    tag = f"v2@{w}"
    pg = new_page(b, w)
    pg.goto(f"{BASE}/dataset-v2.html?code=POP107A", wait_until="networkidle")
    pg.wait_for_timeout(2000)
    seen = tab_flow(pg, 110)
    check(any("dbv2-pill" in f["cls"] or f["tag"] == "SELECT" for f in seen), f"{tag} tab reaches filter controls")
    check(any("dbv2-expand" in f["cls"] for f in seen), f"{tag} tab reaches tile expand buttons")
    check(all(f["outline"] for f in seen if f["tag"] in ("BUTTON", "A", "SELECT")),
          f"{tag} every focused control shows a focus outline")
    check(all(f["left"] >= -1 and f["right"] <= w + 1 for f in seen), f"{tag} focused controls inside viewport")
    types = pg.locator(".dbv2-tile-type").all_inner_texts()
    check(types and not any("_" in t for t in types), f"{tag} chart type names are user-facing: {types}")
    pill = pg.locator(".dbv2-filter-row .dbv2-pill").first
    if pill.count():
        pill.focus()
        key = pill.get_attribute("data-fk")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(1200)
        focused = pg.evaluate("document.activeElement && document.activeElement.dataset.fk")
        check(focused is not None, f"{tag} focus kept inside filter row after keyboard activation ({key} -> {focused})")
    exp = pg.locator(".dbv2-expand").first
    exp.focus()
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(600)
    check(exp.get_attribute("aria-expanded") == "true", f"{tag} expand button exposes aria-expanded")
    pg.keyboard.press("Enter")
    pg.click("#theme-toggle")
    pg.wait_for_timeout(1200)
    check(sw(pg)[0] <= sw(pg)[1], f"{tag} no horizontal overflow after theme switch {sw(pg)}")
    check(not errs(pg), f"{tag} no console/request errors ({errs(pg)[:2]})")
    if shots:
        pg.screenshot(path=f"{shots}/inter-v2-{w}.png")
    pg.context.close()


def run_zoom(b, shots):
    # 200% browser zoom on a 1280px window == 640 CSS px; 320 CSS px == 400% / small phone
    for w in (640, 320):
        for path in ("/?code=POP107A", "/dataset-v2.html?code=POP107A"):
            pg = new_page(b, w, dsf=2)
            pg.goto(BASE + path, wait_until="networkidle")
            pg.wait_for_timeout(1500)
            s = sw(pg)
            check(s[0] <= s[1], f"zoom {w}css/2x {path.split('?')[0]} scrollWidth {s}")
            check(not errs(pg), f"zoom {w} {path} no errors")
            pg.context.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8097")
    ap.add_argument("--shots")
    a = ap.parse_args()
    BASE = a.base
    if a.shots:
        os.makedirs(a.shots, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w in (320, 390, 1440):
            run_v1(b, w, a.shots)
            run_v2(b, w, a.shots)
        run_zoom(b, a.shots)
        b.close()
    print(f"\n{len(fails)} failure(s)")
    sys.exit(1 if fails else 0)
