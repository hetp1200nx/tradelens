#!/usr/bin/env bash
# Pull the latest code from GitHub and restart TradeLens. Your .env and data are kept.
set -euo pipefail
APP_DIR=/opt/tradelens
sudo -u tradelens git -C "$APP_DIR" pull --ff-only
sudo -u tradelens "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
sudo systemctl restart tradelens
sleep 3
sudo systemctl --no-pager --lines=5 status tradelens
echo "Updated. Website keeps the same address."
