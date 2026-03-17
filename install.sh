#!/usr/bin/env bash
# install.sh — sets up myRSSfeed on Raspberry Pi / Debian
#
# What this does:
#   1. Ensures a Python venv exists and dependencies are installed
#   2. Ensures the app is registered as a systemd service (port 8080)
#   3. Ensures the Pi's mDNS hostname (avahi) is set — resolves as myrssfeed.local on some clients
#
# It is safe to re-run: each section first checks if things already look healthy
# and will skip work that does not need to be redone. If a check fails, it will
# try to fix that specific part and report clearly if it still cannot.

set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="myrssfeed"
PYTHON="$(which python3)"
VENV_DIR="$APP_DIR/.venv"
HOSTNAME_MDNS="myrssfeed"

log_step() { printf '\n==> %s\n' "$1"; }
log_ok()   { printf '    ✓ %s\n' "$1"; }
log_skip() { printf '    ↷ %s (already OK)\n' "$1"; }
log_fail() { printf '    ✗ %s\n' "$1"; }

# ── 1. Python venv ──────────────────────────────────────────────────────────
log_step "Checking Python virtual environment…"
if [[ -d "$VENV_DIR" && -x "$VENV_DIR/bin/python" ]]; then
    log_skip "Virtual environment at $VENV_DIR"
else
    log_step "Creating Python virtual environment…"
    rm -rf "$VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR"
fi

log_step "Ensuring Python dependencies are installed…"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q && \
    log_ok "Dependencies installed from requirements.txt"

# ── 2. systemd service ───────────────────────────────────────────────────────
log_step "Checking systemd service ${SERVICE_NAME}.service…"
SERVICE_ACTIVE=0
if systemctl is-active --quiet "${SERVICE_NAME}.service" 2>/dev/null && \
   systemctl is-enabled --quiet "${SERVICE_NAME}.service" 2>/dev/null; then
    SERVICE_ACTIVE=1
fi

if [[ "$SERVICE_ACTIVE" -eq 1 ]]; then
    log_skip "systemd unit is active and enabled"
else
    log_step "Writing systemd unit for myRSSfeed…"
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
fi

if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
    log_ok "myRSSfeed service is active on port 8080"
else
    log_fail "myRSSfeed service is not active after (re)install — check `systemctl status ${SERVICE_NAME}.service`"
fi

# ── 3. mDNS hostname ─────────────────────────────────────────────────────────
log_step "Checking mDNS hostname and avahi-daemon…"
CURRENT_HOSTNAME="$(hostnamectl --static)"
AVAHI_OK=0
if systemctl is-active --quiet avahi-daemon 2>/dev/null && \
   systemctl is-enabled --quiet avahi-daemon 2>/dev/null; then
    AVAHI_OK=1
fi

if [[ "$CURRENT_HOSTNAME" == "$HOSTNAME_MDNS" && "$AVAHI_OK" -eq 1 ]]; then
    log_skip "Hostname (${HOSTNAME_MDNS}) and avahi-daemon are already set up"
else
    log_step "Configuring mDNS hostname to ${HOSTNAME_MDNS}…"
    if [[ "$CURRENT_HOSTNAME" != "$HOSTNAME_MDNS" ]]; then
        sudo hostnamectl set-hostname "$HOSTNAME_MDNS"
    fi
    if ! command -v avahi-daemon &>/dev/null; then
        sudo apt-get install -y -q avahi-daemon
    fi
    sudo systemctl enable --now avahi-daemon
fi

if [[ "$(hostnamectl --static)" == "$HOSTNAME_MDNS" ]] && \
   systemctl is-active --quiet avahi-daemon 2>/dev/null; then
    log_ok "Hostname and mDNS are configured. Pi responds to ${HOSTNAME_MDNS}.local on the network."
else
    log_fail "mDNS configuration did not fully succeed — check `hostnamectl status` and `systemctl status avahi-daemon`."
fi

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
