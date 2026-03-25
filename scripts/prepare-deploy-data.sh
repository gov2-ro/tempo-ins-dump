#!/usr/bin/env bash
# Stages deployment data into deploy-data/ and creates a tarball.
# Usage: bash scripts/prepare-deploy-data.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEPLOY_DIR="$PROJECT_ROOT/deploy-data"

echo "=== Preparing deployment data ==="

# Clean previous staging
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR/parquet-v3/ro"
mkdir -p "$DEPLOY_DIR/view-profiles"

# 1. Copy parquet-v3 (primary)
echo "Copying parquet-v3..."
cp "$PROJECT_ROOT/data/parquet-v3/ro/"*.parquet "$DEPLOY_DIR/parquet-v3/ro/"
V3_COUNT=$(ls "$DEPLOY_DIR/parquet-v3/ro/" | wc -l | tr -d ' ')
echo "  $V3_COUNT v3 files copied"

# 2. Merge v2-only parquet files (those not in v3)
echo "Merging v2-only parquet files..."
V2_ADDED=0
if [ -d "$PROJECT_ROOT/data/parquet-v2/ro" ]; then
    for f in "$PROJECT_ROOT/data/parquet-v2/ro/"*.parquet; do
        basename=$(basename "$f")
        if [ ! -f "$DEPLOY_DIR/parquet-v3/ro/$basename" ]; then
            cp "$f" "$DEPLOY_DIR/parquet-v3/ro/"
            V2_ADDED=$((V2_ADDED + 1))
        fi
    done
fi
echo "  $V2_ADDED v2-only files merged"

# 3. Copy DuckDB metadata
echo "Copying metadata database..."
cp "$PROJECT_ROOT/data/tempo_metadata.duckdb" "$DEPLOY_DIR/"

# 4. Copy view profiles
echo "Copying view profiles..."
cp "$PROJECT_ROOT/data/view-profiles/"*.json "$DEPLOY_DIR/view-profiles/"
VP_COUNT=$(ls "$DEPLOY_DIR/view-profiles/" | wc -l | tr -d ' ')
echo "  $VP_COUNT view profiles copied"

# 5. Create tarball
echo "Creating tarball..."
cd "$PROJECT_ROOT"
tar czf deploy-data.tar.gz -C deploy-data .
TARBALL_SIZE=$(du -h deploy-data.tar.gz | cut -f1)
echo "  deploy-data.tar.gz: $TARBALL_SIZE"

TOTAL_SIZE=$(du -sh "$DEPLOY_DIR" | cut -f1)
echo ""
echo "=== Done ==="
echo "Staged: $DEPLOY_DIR ($TOTAL_SIZE)"
echo "Tarball: $PROJECT_ROOT/deploy-data.tar.gz ($TARBALL_SIZE)"
echo "Total parquet: $((V3_COUNT + V2_ADDED)) files"
