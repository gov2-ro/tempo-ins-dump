#!/usr/bin/env bash
# Stages deployment data into deploy-data/ and creates a tarball.
# Data is sourced from data/corpus/ (new unified data layout).
# Usage: bash scripts/prepare-deploy-data.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CORPUS_DIR="$PROJECT_ROOT/data/corpus"
DEPLOY_DIR="$PROJECT_ROOT/deploy-data"

echo "=== Preparing deployment data ==="
echo "Source: $CORPUS_DIR"

# Validate source
if [ ! -d "$CORPUS_DIR" ]; then
    echo "❌ corpus directory not found: $CORPUS_DIR"
    exit 1
fi
if [ ! -f "$CORPUS_DIR/metadata.duckdb" ]; then
    echo "❌ metadata.duckdb not found in $CORPUS_DIR"
    exit 1
fi

# Clean previous staging
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR/corpus/parquet"
mkdir -p "$DEPLOY_DIR/corpus/view-profiles"

# 1. Copy parquet files
echo "Copying parquet files..."
cp "$CORPUS_DIR/parquet/"*.parquet "$DEPLOY_DIR/corpus/parquet/"
PARQUET_COUNT=$(ls "$DEPLOY_DIR/corpus/parquet/" | wc -l | tr -d ' ')
echo "  $PARQUET_COUNT parquet files copied"

# 2. Copy DuckDB metadata
echo "Copying metadata database..."
cp "$CORPUS_DIR/metadata.duckdb" "$DEPLOY_DIR/corpus/"
DB_SIZE=$(du -h "$DEPLOY_DIR/corpus/metadata.duckdb" | cut -f1)
echo "  metadata.duckdb: $DB_SIZE"

# 3. Copy view profiles
echo "Copying view profiles..."
cp "$CORPUS_DIR/view-profiles/"*.json "$DEPLOY_DIR/corpus/view-profiles/"
VP_COUNT=$(ls "$DEPLOY_DIR/corpus/view-profiles/" | wc -l | tr -d ' ')
echo "  $VP_COUNT view profiles copied"

# 4. Create tarball (for HF Spaces / manual deploys)
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
echo "Parquet files: $PARQUET_COUNT | View profiles: $VP_COUNT"
