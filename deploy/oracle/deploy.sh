#!/usr/bin/env bash
# Deploy INS TEMPO Explorer to Oracle Cloud VM.
# Usage: bash deploy/oracle/deploy.sh <ssh-host>
# Example: bash deploy/oracle/deploy.sh ubuntu@129.xx.xx.xx
set -euo pipefail

HOST="${1:?Usage: deploy.sh <ssh-host>}"
REMOTE_DIR="/opt/tempo"

echo "=== Deploying to $HOST ==="

# 1. Upload app code
echo "Uploading app code..."
rsync -avz --delete \
    --exclude='data/' --exclude='deploy-data/' --exclude='__pycache__/' \
    --exclude='.git/' --exclude='docs/' --exclude='ui/' --exclude='profiling/' \
    ./ "$HOST:$REMOTE_DIR/"

# 2. Upload data tarball (if it exists and remote data dir is empty)
if [ -f deploy-data.tar.gz ]; then
    echo "Uploading data tarball..."
    scp deploy-data.tar.gz "$HOST:/tmp/"
    ssh "$HOST" "mkdir -p $REMOTE_DIR/data && tar xzf /tmp/deploy-data.tar.gz -C $REMOTE_DIR/data/ && rm /tmp/deploy-data.tar.gz"
fi

# 3. Setup venv and install deps
echo "Setting up Python environment..."
ssh "$HOST" "cd $REMOTE_DIR && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"

# 4. Install and start service
echo "Installing systemd service..."
ssh "$HOST" "sudo cp $REMOTE_DIR/deploy/oracle/tempo-explorer.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable tempo-explorer && sudo systemctl restart tempo-explorer"

echo ""
echo "=== Done ==="
echo "Check status: ssh $HOST 'sudo systemctl status tempo-explorer'"
