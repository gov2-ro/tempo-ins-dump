# Context
User asked whether `/ui/` and `/static-site/` folders are still in active use, likely considering cleanup/archival.

## Findings

### `/ui/` — LEGACY (dev-time only, not deployed)
- Standalone HTML pages (`dataset-navigator.html`, `dataset-profile.html`, `category-browser.html`, `tree-browser.html`, `index.html`) run via `python -m http.server 8000`
- Load data from local JSON/CSV files — **no dependency on FastAPI app**
- `build-dataset-metadata.py` generates `ui/data/dataset-metadata.json` for these pages
- Oracle deploy script **explicitly excludes** `ui/` via rsync `--exclude='ui/'`
- `.dockerignore` also excludes `ui/`
- No commits in the last ~40 commits; last activity ~1 year ago
- README still documents these as a dev option

### `/static-site/` — EXPERIMENTAL (not deployed)
- Vue 3 + DuckDB-WASM frontend — serverless, no backend needed
- `build-static-site.py` exports metadata/parquet → `_site/` deployment artifact
- **Not mounted by `app/main.py`**, no deployment config (fly.toml, Dockerfile, Oracle)
- Scaffolded as alternative serverless architecture; never deployed

### Active frontend: `/app/static/`
- Mounted by `app/main.py` at `/`; served in production on Fly.io and Oracle
- All active development is here

## Conclusion
Neither folder is part of the production stack. Options:
1. **Archive `/ui/`** — move to `docs/archived/ui/` or tag + delete; update README
2. **Delete `/static-site/`** — experimental scaffold, not pursued; or keep if serverless path is still considered
3. **Do nothing** — low harm, they're excluded from deploys already
