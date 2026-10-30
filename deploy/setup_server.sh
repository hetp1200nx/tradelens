#!/usr/bin/env bash
# TradeLens one-time server setup for Ubuntu 22.04 / 24.04 (Oracle Cloud, any VPS).
# Usage:  bash setup_server.sh <your-domain-or-ip.sslip.io> [github-repo-url]
# Example: bash setup_server.sh trade.het-patel.work.gd https://github.com/hetp1200nx/tradelens.git
set -euo pipefail

DOMAIN="${1:-}"
REPO="${2:-https://github.com/hetp1200nx/tradelens.git}"
APP_DIR=/opt/tradelens
APP_USER=tradelens

if [ -z "$DOMAIN" ]; then
  IP=$(curl -s -4 https://ifconfig.me || true)
  echo "Usage: bash setup_server.sh <domain>   e.g. bash setup_server.sh ${IP//./-}.sslip.io"
  exit 1
fi

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git curl debian-keyring debian-archive-keyring apt-transport-https iptables-persistent

echo "==> Installing Caddy (automatic HTTPS)"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y caddy
fi

echo "==> Getting the code"
id -u "$APP_USER" >/dev/null 2>&1 || sudo useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
if [ -d "$APP_DIR/.git" ]; then
  sudo -u "$APP_USER" git -C "$APP_DIR" pull --ff-only
else
  sudo mkdir -p "$APP_DIR" && sudo chown "$APP_USER":"$APP_USER" "$APP_DIR"
  sudo -u "$APP_USER" git clone "$REPO" "$APP_DIR"
fi

echo "==> Python environment"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  sudo -u "$APP_USER" cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  sudo chmod 600 "$APP_DIR/.env"
  NEW_ENV=1
fi

echo "==> Auto-start service"
sudo tee /etc/systemd/system/tradelens.service >/dev/null <<EOF
[Unit]
Description=TradeLens
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PORT=8000
ExecStart=$APP_DIR/.venv/bin/python run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "==> HTTPS website at https://$DOMAIN"
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$DOMAIN {
    encode gzip
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
EOF

echo "==> Opening web ports 80 and 443 (Oracle Ubuntu images block them by default)"
for p in 80 443; do
  sudo iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 5 -p tcp -m state --state NEW --dport $p -j ACCEPT
done
sudo netfilter-persistent save >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now tradelens
sudo systemctl restart tradelens
sudo systemctl enable caddy
sudo systemctl restart caddy

echo
echo "================================================================"
if [ "${NEW_ENV:-}" = "1" ]; then
  echo " NEXT: fill in your settings, then restart:"
  echo "   sudo nano $APP_DIR/.env"
  echo "   sudo systemctl restart tradelens"
fi
echo " Website:  https://$DOMAIN   (HTTPS certificate appears within ~1 minute)"
echo " Logs:     sudo journalctl -u tradelens -f"
echo " Update:   bash $APP_DIR/deploy/update.sh"
echo "================================================================"
