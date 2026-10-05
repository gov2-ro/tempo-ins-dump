"""FIX-02 phase 2 browser check: a withheld total shows its reason and the
double-counted number appears nowhere in the DOM.

Needs a running app (default http://127.0.0.1:8099) and playwright (python).
Usage: python tests/browser/audit_aggregation.py [--base URL]

POP107A sums to 129,072,774 when every age grain and geographic level is added
together; v1, v2 and /insights used to headline it.
"""
import argparse
import re
import sys

from playwright.sync_api import sync_playwright

NAIVE = re.compile(r"129[.,\s ]?072[.,\s ]?774")
REASON = {"ro": "Total indisponibil", "en": "Total unavailable"}
OVERLAP = {"ro": "suprapuse", "en": "overlapping"}


def run(base):
    fails = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for page_name, path in (("v2", "/dataset-v2.html?code=POP107A"), ("v1", "/?code=POP107A")):
            for lang in ("ro", "en"):
                ctx = b.new_context(viewport={"width": 1280, "height": 900})
                ctx.add_init_script(f"localStorage.setItem('lens_lang','{lang}')")
                pg = ctx.new_page()
                errs = []
                pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(base + path, wait_until="networkidle")
                pg.wait_for_timeout(2500)
                html = pg.content()
                text = pg.inner_text("body")
                ok_naive = not NAIVE.search(html) and not NAIVE.search(text)
                ok_reason = REASON[lang] in text and OVERLAP[lang] in text
                bad_errs = [e for e in errs if "favicon" not in e and "view-profiles" not in e
                            and "Failed to load resource" not in e]
                status = "ok" if ok_naive and ok_reason and not bad_errs else "FAIL"
                if status != "ok":
                    fails += 1
                print(f"{status:4} {page_name}-{lang} naive-absent={ok_naive} reason-shown={ok_reason} errors={bad_errs[:3]}")
                ctx.close()
        b.close()
    return fails


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8099")
    a = ap.parse_args()
    sys.exit(1 if run(a.base) else 0)
