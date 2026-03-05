#!/usr/bin/env bash
# configure-resilience.sh — idempotent script to apply reboot-on-failure
# settings to the myrssfeed systemd unit.
#
# Safe to run multiple times. Writes the same result on every run.
# See docs/system-resilience.md for a full explanation of what this does
# and why it deviates from default OS behaviour.
set -euo pipefail

SERVICE_FILE="/etc/systemd/system/myrssfeed.service"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$APP_DIR/.venv"

# ── Guard: must be run as a user who can sudo ────────────────────────────────
if ! sudo -n true 2>/dev/null && ! sudo -v 2>/dev/null; then
    echo "ERROR: this script requires sudo privileges." >&2
    exit 1
fi

# ── Check if already applied ─────────────────────────────────────────────────
already_applied() {
    grep -q "FailureAction=reboot" "$SERVICE_FILE" 2>/dev/null
}

if already_applied; then
    echo "Resilience settings are already applied to $SERVICE_FILE."
    echo "No changes made."
    exit 0
fi

# ── Explain what we are about to do ─────────────────────────────────────────
cat <<'INFO'

  ┌─────────────────────────────────────────────────────────────────────┐
  │  myRSSfeed — reboot-on-failure configuration                        │
  │                                                                     │
  │  This will modify the systemd service unit to:                      │
  │                                                                     │
  │    • Kill the process if it hangs for more than 5 minutes           │
  │      (TimeoutSec=300)                                               │
  │                                                                     │
  │    • Allow up to 3 automatic restarts within a 5-minute window      │
  │      (StartLimitBurst=3 / StartLimitIntervalSec=300)                │
  │                                                                     │
  │    • Reboot the device if the service keeps failing after           │
  │      those retries (FailureAction=reboot)                           │
  │                                                                     │
  │  This is NOT default OS behaviour. The device will reboot           │
  │  automatically when myRSSfeed cannot recover on its own.            │
  │  See docs/system-resilience.md for full details and trade-offs.     │
  └─────────────────────────────────────────────────────────────────────┘

INFO

read -rp "Apply these settings? [y/N] " REPLY
echo

if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
    echo "Skipped. The service will run without reboot-on-failure protection."
    exit 0
fi

# ── Write the updated unit file ──────────────────────────────────────────────
echo "==> Writing updated systemd unit…"
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=myRSSfeed — personal RSS aggregator
After=network.target ollama.service
Wants=ollama.service
StartLimitBurst=3
StartLimitIntervalSec=300

[Service]
Type=simple
User=${SUDO_USER:-$USER}
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/python main.py
Restart=on-failure
RestartSec=10
# Kill hung process after 5 minutes (handles ollama/model hangs)
TimeoutSec=300
# Reboot the device when restart limit is exhausted instead of staying dead
FailureAction=reboot
# Memory throttling: the kernel reclaims pages and slows the process once it
# crosses MemoryHigh, then hard-kills it only if it reaches MemoryMax.
# Adjust to fit your Pi's available RAM (Pi 5 8 GB → adjust as needed)
MemoryHigh=700M
MemoryMax=900M
MemorySwapMax=0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl reset-failed myrssfeed.service 2>/dev/null || true

echo ""
echo "Done. Resilience settings applied."
echo "The service will now reboot the device if myRSSfeed fails repeatedly."
echo ""
echo "To verify:  systemctl cat myrssfeed.service"
echo "To revert:  see docs/system-resilience.md"
