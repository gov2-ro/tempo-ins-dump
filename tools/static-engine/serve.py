#!/usr/bin/env python3
"""Serve a static build locally with the same rewrites the Apache .htaccess
makes (dev and tests only; no Python app, no /api).

  python tools/static-engine/serve.py _static [--port 8090]

  /dataset/{code}        -> dataset/{code}/index.html when pre-rendered, else dataset-v2.html
  /place/{type}/{slug}   -> place.html          /places -> places.html
  /dataset.html?…        -> 301 /dataset-v2.html?…
  /api/…, /sdmx/…        -> 404 (and logged: a static page must never ask)
"""
import argparse
import http.server
import re
import sys
from functools import partial
from pathlib import Path


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json",
                      ".gz": "application/octet-stream", ".geojson": "application/json"}
    api_hits: list = []

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path.startswith(("/api/", "/sdmx/")):
            Handler.api_hits.append(self.path)
            sys.stderr.write(f"STATIC SITE ASKED THE SERVER: {self.path}\n")
            self.send_error(404)
            return
        if path == "/dataset.html":
            self.send_response(301)
            self.send_header("Location", "/dataset-v2.html" + (f"?{query}" if query else ""))
            self.end_headers()
            return
        m = re.fullmatch(r"/dataset/([A-Za-z0-9_]+)/?", path)
        if m:
            pre = Path(self.directory) / "dataset" / m.group(1) / "index.html"
            self.path = (f"/dataset/{m.group(1)}/index.html" if pre.exists() else "/dataset-v2.html") \
                + (f"?{query}" if query else "")
        elif re.fullmatch(r"/place/[a-z]+/[a-z0-9-]+/?", path):
            self.path = "/place.html" + (f"?{query}" if query else "")
        elif path in ("/places", "/places/"):
            self.path = "/places.html"
        return super().do_GET()

    def log_message(self, fmt, *args):
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root")
    ap.add_argument("--port", type=int, default=8090)
    a = ap.parse_args(argv)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), partial(Handler, directory=a.root))
    print(f"serving {a.root} on http://127.0.0.1:{a.port}", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
