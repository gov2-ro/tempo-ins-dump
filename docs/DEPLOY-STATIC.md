# Static site: build, gate, host

The whole site can run as static files on shared hosting (Apache), with no
Python process:
- the pages compute in the browser;
- the aggregation rules are a JavaScript port of the server's, proven equal to
  it on every served dataset;
- everything else is either recorded once from the real app or computed from
  exported inputs, and proven equal too.

The FastAPI app stays the specification, the build tool and the development
server. The design and the parity results are in
[plans/public-alpha/static/](plans/public-alpha/static/): `plan.md`, `s1-spike.md`,
`s2-corpus.md` and `s3-wiring.md`.

## Build

```bash
source ~/devbox/envs/240826/bin/activate
TEMPO_DATA_DIR=<generation>/data python scripts/build-static.py --out _static --base-url https://ins.gov2.ro
```

The build is read-only on the generation. `--codes A,B` builds a subset for
development. `--no-record` writes only data and policies, which is what the
parity tests use. `_static/` is gitignored.

| Path | What |
|---|---|
| `data/`, `policy/` | observations (TCOL1 binary, gzipped; partitioned above 200k rows) and the aggregation context per dataset |
| `rec/` | bounded API answers recorded from the real app (ro/en): metadata, insights, related, categories, places + KPI baselines, recipes per year and their evidence ZIPs, the catalog |
| `search/` | concepts, card facts and the FTS sidecar's BM25 index (exact, sharded) |
| `dataset/{code}/index.html`, `en.html` | pre-rendered canonical pages (facts in the HTML, no server links) |
| site files | `app/static`, view profiles, `js/config.js` set to static mode, `.htaccess`, `robots.txt`, `sitemap.xml`, `llms.txt` |
| `build.json`, `static-manifest.json` | generation, commit, limits; sha256 and size of every file |

A full build of the 2026-10-05 copy takes about 30 minutes; see the activity
log for its size and file count.

## Gate

```bash
python scripts/gen-api-cases.py --out api.jsonl --n 300            # server answers to compare
python scripts/release-check.py --static _static --source <generation>/data/corpus \
    --api-cases api.jsonl [--skip-tests]
```

The gate checks:
- every file's hash against the manifest, with nothing outside it and no file
  over 15 MB;
- the generation equals the corpus;
- `config.js` is in static mode;
- every dataset has data, policy, metadata (ro/en), insights and both pages;
- the site files are present and the full-text index was exported;
- every recipe was recorded without error;
- the API parity cases pass.

Test locally with Apache's rewrites and no Python app:

```bash
python tools/static-engine/serve.py _static --port 8090      # logs any /api request as an error
```

## Host

`deploy/static/.htaccess` is copied into the build. It needs Apache 2.4 with
mod_rewrite and mod_headers. It:
- answers `/api/*` and `/sdmx/*` with 404;
- redirects `/dataset.html` to `/dataset-v2.html`;
- maps `/dataset/{code}` to the pre-rendered page (`en.html` when `lang=en`);
- maps `/place/{type}/{slug}` and `/places` to their pages;
- serves `.gz` files as opaque bytes (the page gunzips them itself, so any
  server setting works);
- sends `Cache-Control: no-cache` on everything, so a page never mixes two
  releases.

Upload is a separate, explicit step:

```bash
scripts/deploy-static.sh _static user@host /home/user/ins-static          # dry run: prints the steps
scripts/deploy-static.sh _static user@host /home/user/ins-static --go     # only with the owner's authorization
```

Each release goes to `releases/<gen12>-<commit12>/`. `current` is then
switched atomically. Point the document root (or the subdomain) at
`<root>/current`. To roll back, re-point `current` at the previous release.

## What the static site does not have

- **No REST/SDMX query API.** Machines read the data files listed in
  `/llms.txt`.
- **No Ask.** Its links are hidden.
- **No server logs or rate limits.**
- **A browser byte budget.** A query whose files exceed 12 MB is refused with
  reason `browser_budget` (`build.json` `max_query_bytes`), never cut. This
  only happens for whole-country reads of the largest families. The same
  applies to CSV/XLSX downloads and evidence ZIPs: filter by county or period.
- **Recipe evidence ZIPs cover the whole year.** An area subset is not applied
  to the recorded bundle.
- **XLSX files come from SheetJS** (loaded from cdnjs on demand), not the
  server's writer.
