#!/bin/bash
# Local MCP test server with the 512 MiB budgets and the operator profile (scan cap 5M), on port 8090.
# usage: scripts/serve-mcp-test.sh [PUBLIC_BASE_URL]   (default http://127.0.0.1:8090; pass the tunnel URL when tunnelling)
# env:   TEMPO_TEST_DATA (default <repo>/data), TEMPO_ASK_LOG_DIR (default <repo>/data/logs/mcp-test)
BASE=${1:-http://127.0.0.1:8090}
REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO" || exit 1
source ~/devbox/envs/240826/bin/activate
export TEMPO_DATA_DIR=${TEMPO_TEST_DATA:-$REPO/data}
export TEMPO_DB_THREADS=1
export TEMPO_ASK_BYOK_ENABLED=true   # Ask with your own key (local only)
export TEMPO_ASK_LOG_CHATS=true TEMPO_MCP_LOG_CALLS=true   # content logs (disclosed): ask-chats.jsonl, mcp-calls.jsonl
export TEMPO_ASK_LOG_DIR=${TEMPO_ASK_LOG_DIR:-$REPO/data/logs/mcp-test}
mkdir -p "$TEMPO_ASK_LOG_DIR"
export TEMPO_MCP_ENABLED=true TEMPO_MCP_MAX_SCAN_ROWS=5000000
export TEMPO_PUBLIC_BASE_URL=$BASE
case $BASE in http://127.0.0.1*|http://localhost*) export TEMPO_MCP_LOCAL_TEST=true;; esac
# app loggers (MCP_METRICS: tool, status, reason, duration per call) at INFO, with timestamps
exec python -c "
import logging, uvicorn
logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logging.getLogger('app').setLevel(logging.INFO)
uvicorn.run('app.main:app', host='127.0.0.1', port=8090, log_level='warning')"
