#!/usr/bin/env bash
# install.sh — sets up myRSSfeed on Raspberry Pi / Debian
#
# What this does:
#   1. Creates a Python venv and installs dependencies
#   2. Registers the app as a systemd service (port 8080)
#   3. Sets the Pi's mDNS hostname (avahi) — resolves as myrssfeed.local on some clients
#
# After running:   http://<server-ip>:8080  (from any device on the same network)
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="myrssfeed"
PYTHON="$(which python3)"
VENV_DIR="$APP_DIR/.venv"
HOSTNAME_MDNS="myrssfeed"

# ── 1. Python venv ──────────────────────────────────────────────────────────
echo "==> Creating Python virtual environment…"
rm -rf "$VENV_DIR"
$PYTHON -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# ── 2. systemd service ───────────────────────────────────────────────────────
echo "==> Writing systemd unit for myRSSfeed…"
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=myRSSfeed — personal RSS aggregator
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/python main.py
Restart=on-failure
RestartSec=10
MemoryHigh=400M
MemoryMax=600M
MemorySwapMax=0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ${SERVICE_NAME}.service
echo "    myRSSfeed service started on port 8080"

# ── 3. mDNS hostname ─────────────────────────────────────────────────────────
echo "==> Setting mDNS hostname to ${HOSTNAME_MDNS}…"
sudo hostnamectl set-hostname "$HOSTNAME_MDNS"
if ! command -v avahi-daemon &>/dev/null; then
    sudo apt-get install -y -q avahi-daemon
fi
sudo systemctl enable --now avahi-daemon
echo "    Hostname set. The Pi will respond to ${HOSTNAME_MDNS}.local on the network."

# ── Done ─────────────────────────────────────────────────────────────────────
SERVER_IP="$(hostname -I | awk '{print $1}')"
echo ""
echo "=========================================="
echo " myRSSfeed is ready!"
echo ""
echo " Open on any device on this network:"
echo "   http://${SERVER_IP}:8080"
echo ""
echo " View live logs:"
echo "   http://${SERVER_IP}:8080/api/logs"
echo "=========================================="
