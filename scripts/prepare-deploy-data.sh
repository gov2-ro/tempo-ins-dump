#!/usr/bin/env bash
# Stages deployment data (metadata, search index, parquets, view profiles) into
# deploy-data/ together with a MANIFEST.json, then (optionally) a tarball.
#
# Safety properties (FIX-05):
#   * staging is built in a temp dir next to the target and swapped in atomically
#     only after validation succeeds; a failed run leaves the previous staging intact
#   * the previous staging is kept as <out>.prev for rollback
#     (python scripts/release-check.py --rollback)
#   * the source is snapshotted (size+mtime, sha256 for DBs) before and after the
#     copy; any change mid-copy aborts
#
# Usage: bash scripts/prepare-deploy-data.sh [--no-tarball]
# Env:   TEMPO_CORPUS_SRC  source corpus dir   (default: <repo>/data/corpus)
#        TEMPO_DEPLOY_OUT  staging output dir  (default: <repo>/deploy-data)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CORPUS_DIR="${TEMPO_CORPUS_SRC:-$PROJECT_ROOT/data/corpus}"
DEPLOY_DIR="${TEMPO_DEPLOY_OUT:-$PROJECT_ROOT/deploy-data}"
PY="${PYTHON:-python}"
TARBALL=1
[ "${1:-}" = "--no-tarball" ] && TARBALL=0

RC="$PY $SCRIPT_DIR/release-check.py"
TMP_DIR="$DEPLOY_DIR.tmp.$$"
PREV_DIR="$DEPLOY_DIR.prev"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "=== Preparing deployment data ==="
echo "Source: $CORPUS_DIR"
echo "Output: $DEPLOY_DIR"

# Validate source presence
[ -d "$CORPUS_DIR" ] || { echo "ERROR: corpus directory not found: $CORPUS_DIR"; exit 1; }
for f in metadata.duckdb search.duckdb; do
    [ -f "$CORPUS_DIR/$f" ] || { echo "ERROR: $f not found in $CORPUS_DIR" \
        "(search.duckdb: run scripts/build-search-index.py)"; exit 1; }
done
[ -d "$CORPUS_DIR/parquet" ] && [ -d "$CORPUS_DIR/view-profiles" ] \
    || { echo "ERROR: parquet/ or view-profiles/ missing in $CORPUS_DIR"; exit 1; }

# Snapshot the quiescent source before copying
SNAP_BEFORE="$($RC snapshot "$CORPUS_DIR")"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR/corpus/parquet" "$TMP_DIR/corpus/view-profiles"

echo "Copying parquet files..."
cp "$CORPUS_DIR/parquet/"*.parquet "$TMP_DIR/corpus/parquet/"
echo "Copying metadata.duckdb + search.duckdb..."
cp "$CORPUS_DIR/metadata.duckdb" "$CORPUS_DIR/search.duckdb" "$TMP_DIR/corpus/"
echo "Copying view profiles..."
cp "$CORPUS_DIR/view-profiles/"*.json "$TMP_DIR/corpus/view-profiles/"

# Reject mid-copy source changes
SNAP_AFTER="$($RC snapshot "$CORPUS_DIR")"
if [ "$SNAP_BEFORE" != "$SNAP_AFTER" ]; then
    echo "ERROR: source changed while copying; staging rejected (previous staging untouched)"
    exit 1
fi

# Manifest (placeholder for FIX-03 generation manifest) + validate the temp stage
$RC manifest "$TMP_DIR" "$CORPUS_DIR"
# release-check validates a dir containing corpus/..., so point it at the temp dir;
# tests are the release gate's job, not the staging step's.
$PY "$SCRIPT_DIR/release-check.py" --stage "$TMP_DIR" --skip-tests --source "$CORPUS_DIR" \
    || { echo "ERROR: staged data failed validation; previous staging untouched"; exit 1; }

# Atomic swap, keeping the previous staging for rollback
if [ -d "$DEPLOY_DIR" ]; then
    rm -rf "$PREV_DIR"
    mv "$DEPLOY_DIR" "$PREV_DIR"
fi
if ! mv "$TMP_DIR" "$DEPLOY_DIR"; then
    [ -d "$PREV_DIR" ] && mv "$PREV_DIR" "$DEPLOY_DIR"
    echo "ERROR: swap failed; previous staging restored"
    exit 1
fi
trap - EXIT

if [ "$TARBALL" = 1 ]; then
    echo "Creating tarball (for HF Spaces / manual deploys)..."
    tar czf "$DEPLOY_DIR.tar.gz.tmp" -C "$DEPLOY_DIR" . && mv "$DEPLOY_DIR.tar.gz.tmp" "$DEPLOY_DIR.tar.gz"
fi

echo ""
echo "=== Done ==="
echo "Staged: $DEPLOY_DIR ($(du -sh "$DEPLOY_DIR" | cut -f1)); previous kept at $PREV_DIR (if any)"
echo "Next: python scripts/release-check.py [--docker]"
