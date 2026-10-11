"""PA-01c: a late response must not overwrite a newer selection (audit A05).

Moves a tile's year slider to Y1 then Y2 while the Y1 response is held back, then
checks that the tile shows Y2's values under the Y2 label. Needs a running app on
the real corpus (default http://127.0.0.1:8097) and python playwright.
Usage: python tests/browser/audit_pa01_races.py [--base URL] [--code FOM106F]
"""
import argparse
import json
import sys
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8097")
    ap.add_argument("--code", default="FOM106F")
    ap.add_argument("--delay", type=float, default=1.5)
    a = ap.parse_args()

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1400, "height": 1000})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        held = {"year": None}
        bodies = {}

        def record(resp):
            if f"/api/datasets/{a.code}/data?" not in resp.url:
                return
            q = parse_qs(urlparse(resp.url).query)
            years = json.loads(q.get("filters", ["{}"])[0]).get("TIME_PERIOD") or []
            if len(years) == 1:
                try:
                    bodies[years[0]] = resp.json()
                except Exception:
                    pass

        pg.on("response", record)
        # Hold back, in the page, the response for window.__hold (a network
        # delay that does not serialize the other requests).
        pg.add_init_script("""(() => { const f = window.fetch;
          window.fetch = async (...args) => { const r = await f(...args);
            const u = String(args[0]); const h = window.__hold;
            if (h && u.includes('/data?') && decodeURIComponent(u).includes('"' + h + '"'))
              await new Promise(res => setTimeout(res, %d));
            return r; }; })();""" % int(a.delay * 1000))
        pg.goto(f"{a.base}/dataset-v2.html?code={a.code}", wait_until="networkidle")
        slider = pg.locator(".dbv2-time-slider input[type=range]").first
        slider.wait_for(timeout=20000)
        tile = slider.locator("xpath=ancestor::*[contains(concat(' ', @class, ' '), ' dbv2-tile ')][1]")
        container_id = tile.locator("[id^='dbv2-chart-']").first.get_attribute("id")
        n = int(slider.get_attribute("max")) + 1
        if n < 3:
            print("FAIL slider has fewer than 3 periods"); return 1
        i1, i2 = n - 3, n - 2

        def set_index(i):
            slider.evaluate("(el, i) => { el.value = i; el.dispatchEvent(new Event('input')); "
                            "el.dispatchEvent(new Event('change')); }", i)
            return tile.locator(".dbv2-time-slider output").first.inner_text().strip()

        # Learn both periods' responses, then ask for Y1 (held back) and at once Y2.
        label2 = set_index(i2); pg.wait_for_timeout(1500)
        label1 = set_index(i1); pg.wait_for_timeout(1500)
        held["year"] = next((k for k in bodies if str(k).endswith(label1)), None)
        pg.evaluate("y => { window.__hold = y; }", held["year"])
        set_index(i1)
        label2 = set_index(i2)
        pg.wait_for_timeout(int(a.delay * 1000) + 2500)

        shown = pg.evaluate(
            """id => { const c = echarts.getInstanceByDom(document.getElementById(id));
                       const o = c.getOption();
                       return o.series.flatMap(s => (s.data || []).map(d =>
                           Array.isArray(d) ? d[d.length - 1] : (d && typeof d === 'object' ? d.value : d)))
                           .filter(v => typeof v === 'number').sort((x, y) => x - y); }""",
            container_id)
        y2key = next((k for k in bodies if str(k).endswith(label2)), None)
        y1key = held["year"]
        want = sorted(r[-1] for r in bodies.get(y2key, {}).get("rows", []) if r[-1] is not None)
        stale = sorted(r[-1] for r in bodies.get(y1key, {}).get("rows", []) if r[-1] is not None)
        # The chart may leave out total rows, so compare as subsets.
        in_want = bool(shown) and set(shown) <= set(want)
        in_stale = bool(shown) and set(shown) <= set(stale)
        ok = in_want and not in_stale
        print(f"{'OK  ' if ok else 'FAIL'} {a.code}: label={label2} (held {y1key}); "
              f"chart values from {label2}: {in_want}; from held year: {in_stale} "
              f"({len(shown)} shown, {len(want)}/{len(stale)} rows)")
        if errs:
            print("FAIL page errors:", errs[:3]); ok = False
        b.close()
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
