#!/usr/bin/env bash
# Deploy the API and public MCP to the Hetzner VPS (HZ-1). Dry run by default.
#
# Usage: bash scripts/deploy/hetzner/deploy.sh [--apply] [--stage DIR] <ssh-host>
# Run it from the repository checkout, after `bash scripts/prepare-deploy-data.sh`.
#
# Steps (with --apply; without it the script prints them and runs only read-only checks):
#   1. Check the local stage (deploy-data/MANIFEST.json) and the remote disk (the filesystem of /opt/tempo needs 5 GB free).
#   2. rsync code, then the staged data, to /opt/tempo/releases/<id>.
#      Both use --link-dest against the previous release: unchanged files are hard links.
#   3. Create a venv in the release, install requirements.txt, install the DuckDB fts extension.
#      Refuse the release if pandas, numpy or pyarrow are in the venv.
#   4. Smoke the new release on port 8095/8096 with release-check.py --local. Stop on failure.
#   5. Swap /opt/tempo/current, restart tempo-api, check /api/health. Swap back on failure.
#   6. Keep two releases (the new one and the previous one). Delete the others.
# Needs: ssh access, passwordless sudo for `systemctl restart tempo-api`, python3.12, rsync, curl.
set -euo pipefail

APPLY=0
STAGE=""
HOST=""
while [ $# -gt 0 ]; do
    case "$1" in
        --apply) APPLY=1 ;;
        --stage) STAGE="${2:?--stage needs a directory}"; shift ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) HOST="$1" ;;
    esac
    shift
done
[ -n "$HOST" ] || { echo "Usage: deploy.sh [--apply] [--stage DIR] <ssh-host>" >&2; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
STAGE="${STAGE:-$ROOT/deploy-data}"
BASE=/opt/tempo
MIN_FREE_GB=5
PORT=8095
# Strict gate from AGENTS.md. Override with SMOKE_ARGS="..." only with the owner's approval.
SMOKE_ARGS="${SMOKE_ARGS:---require-clean-audit --accept-restriction conflicting_grain}"
SSH=(ssh -o BatchMode=yes "$HOST")

# Code the app needs at run time: what the Dockerfile copies (app/, sdmx_labels.py, llms.txt,
# requirements.txt), plus the files the smoke needs: fly.toml (safe default env) and the two scripts.
CODE_FILES=(requirements.txt llms.txt sdmx_labels.py fly.toml scripts/release-check.py scripts/mcp_probe.py)
CODE_DIRS=(app)

say() { printf '%s\n' "$*"; }
run() { if [ "$APPLY" = 1 ]; then "$@"; else say "[dry-run] $*"; fi; }

# --- 1. Local checks
[ -f "$STAGE/MANIFEST.json" ] && [ -f "$STAGE/corpus/search.duckdb" ] && [ -f "$STAGE/corpus/metadata.duckdb" ] \
    || { echo "ERROR: $STAGE is not a staged release (run scripts/prepare-deploy-data.sh)" >&2; exit 1; }
for f in "${CODE_FILES[@]}"; do [ -f "$ROOT/$f" ] || { echo "ERROR: missing $ROOT/$f" >&2; exit 1; }; done
GEN="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['generation']['id'][:8])" "$STAGE/MANIFEST.json" 2>/dev/null || echo nogen)"
REL_ID="$(date +%Y%m%d-%H%M%S)-$GEN"
REL="$BASE/releases/$REL_ID"
say "=== Deploy $REL_ID to $HOST ($([ "$APPLY" = 1 ] && echo APPLY || echo dry run)) ==="
say "Stage: $STAGE"

# --- 2. Remote disk and state (read-only)
# Releases live on the filesystem of $BASE (on gov2-1: the volume, bind-mounted at /opt/tempo).
FREE_GB="$("${SSH[@]}" "df -BG --output=avail $BASE | tail -1 | tr -dc 0-9")"
say "Free on $BASE: ${FREE_GB:-?} GB (need $MIN_FREE_GB)"
[ "${FREE_GB:-0}" -ge "$MIN_FREE_GB" ] || { echo "ERROR: less than $MIN_FREE_GB GB free on $BASE" >&2; exit 1; }
# readlink -e (not -f): print nothing unless the whole path exists. -f prints /opt/tempo/current on a first deploy.
PREV="$("${SSH[@]}" "readlink -e $BASE/current 2>/dev/null || true")"
say "Current release: ${PREV:-none}"

# --- 3. Upload
run "${SSH[@]}" "mkdir -p $REL"
RSYNC=(rsync -rlpt --delete -e "ssh -o BatchMode=yes")
[ "$APPLY" = 1 ] || RSYNC+=(--dry-run)
CODE_LINK=(); DATA_LINK=()
if [ -n "$PREV" ]; then CODE_LINK=(--link-dest="$PREV/"); DATA_LINK=(--link-dest="$PREV/data/"); fi
say "Uploading code..."
( cd "$ROOT" && "${RSYNC[@]}" ${CODE_LINK[@]+"${CODE_LINK[@]}"} --relative --exclude='__pycache__/' --exclude='*.pyc' \
    "${CODE_DIRS[@]}" "${CODE_FILES[@]}" "$HOST:$REL/" ) \
    || [ "$APPLY" = 0 ] || exit 1
say "Uploading data (hard links against the previous release)..."
"${RSYNC[@]}" ${DATA_LINK[@]+"${DATA_LINK[@]}"} "$STAGE/" "$HOST:$REL/data/" || [ "$APPLY" = 0 ] || exit 1

# --- 4. Venv, dependencies, fts extension
say "Building the venv in $REL ..."
run "${SSH[@]}" "set -e; cd $REL && python3 -m venv venv && venv/bin/python -m pip install --no-cache-dir -q -r requirements.txt \
 && mkdir -p home \
 && HOME=$REL/home venv/bin/python -c \"import duckdb; c = duckdb.connect(); c.execute('INSTALL fts'); c.execute('LOAD fts'); print('fts', duckdb.__version__)\" \
 && if venv/bin/python -m pip list --format=freeze | grep -iE '^(pandas|numpy|pyarrow)=='; then echo 'ERROR: pandas, numpy or pyarrow in the venv' >&2; exit 1; fi \
 && chmod -R a+rX $REL"

# --- 5. Smoke the new release on another port
say "Smoke on port $PORT (release-check.py --local) ..."
SMOKE="cd $REL && HOME=$REL/home venv/bin/python scripts/release-check.py --local --stage $REL/data --skip-tests --port $PORT $SMOKE_ARGS"
if [ "$APPLY" = 1 ]; then
    "${SSH[@]}" "$SMOKE" || { echo "ERROR: smoke failed. 'current' is unchanged. The new release stays at $REL." >&2; exit 1; }
else
    say "[dry-run] ssh $HOST '$SMOKE'"
fi

# --- 6. Swap, restart, health check; swap back on failure
health() { "${SSH[@]}" 'for i in $(seq 1 40); do curl -fsS http://127.0.0.1:8080/api/health >/dev/null && exit 0; sleep 1; done; exit 1'; }
swap() { "${SSH[@]}" "ln -sfn $1 $BASE/current.new && mv -Tf $BASE/current.new $BASE/current && sudo systemctl restart tempo-api"; }
if [ "$APPLY" = 1 ]; then
    swap "$REL"
    if ! health; then
        echo "ERROR: health check failed after the swap." >&2
        if [ -n "$PREV" ]; then
            say "Swapping back to $PREV ..."
            swap "$PREV"
            health && say "Rolled back to $PREV." || echo "ERROR: the previous release is not healthy either." >&2
        fi
        exit 1
    fi
    say "New release healthy: $REL"
else
    say "[dry-run] ln -sfn $REL $BASE/current; systemctl restart tempo-api; health check; swap back on failure"
fi

# --- 7. Keep two releases: the new one and the previous one. Delete the others.
if [ "$APPLY" = 1 ]; then
    "${SSH[@]}" "cd $BASE/releases && for d in *; do [ \"$BASE/releases/\$d\" = \"$REL\" ] || [ \"$BASE/releases/\$d\" = \"$PREV\" ] || rm -rf \"\$d\"; done; ls -1 $BASE/releases"
else
    say "[dry-run] delete every release in $BASE/releases except $REL_ID and the previous one"
fi
say "=== Done ==="
