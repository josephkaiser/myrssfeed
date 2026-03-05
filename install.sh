#!/usr/bin/env bash
# install.sh — sets up myRSSfeed on Raspberry Pi / Debian
#
# What this does:
#   1. Creates a Python venv and installs dependencies
#   2. Installs ollama and pulls the default model (phi3:mini)
#   3. Registers the app as a systemd service (port 8080, loopback only)
#   4. Installs nginx and mkcert
#   5. Generates a locally-trusted TLS certificate for myrssfeed.local
#   6. Drops the nginx site config in place and enables it
#   7. Sets the Pi's mDNS hostname so the site resolves as myrssfeed.local
#
# After running:   https://myrssfeed.local  (from any device on the same network)
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="myrssfeed"
PYTHON="$(which python3)"
VENV_DIR="$APP_DIR/.venv"
CERT_DIR="/etc/ssl/myrssfeed"
HOSTNAME_MDNS="myrssfeed"

# ── 1. Python venv ──────────────────────────────────────────────────────────
echo "==> Creating Python virtual environment…"
rm -rf "$VENV_DIR"
$PYTHON -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# ── 2. ollama ────────────────────────────────────────────────────────────────
echo "==> Installing ollama…"
if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.ai/install.sh | sh
    echo "    ollama installed."
else
    echo "    ollama already installed — skipping."
fi

# Ensure the ollama systemd service is enabled and running
# (the official install script creates /etc/systemd/system/ollama.service)
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
echo "    ollama service enabled."

# Pull the default model if not already available
DEFAULT_MODEL="phi3:mini"
echo "==> Pulling default model '$DEFAULT_MODEL' (may take a few minutes)…"
ollama pull "$DEFAULT_MODEL"
echo "    Model '$DEFAULT_MODEL' ready."

# ── 3. systemd service (binds only to loopback) ─────────────────────────────
echo "==> Writing systemd unit for myRSSfeed…"
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=myRSSfeed — personal RSS aggregator
After=network.target ollama.service
Wants=ollama.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/python main.py
Restart=on-failure
RestartSec=10
# Memory throttling: the kernel reclaims pages and slows the process once it
# crosses MemoryHigh, then hard-kills it only if it reaches MemoryMax.
# This keeps the Pi responsive under load instead of triggering a system OOM.
# Adjust to fit your Pi's available RAM (Pi 5 8 GB → adjust as needed)
MemoryHigh=700M
MemoryMax=900M
MemorySwapMax=0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ${SERVICE_NAME}.service
echo "    myRSSfeed service started on 127.0.0.1:8080"

# ── 4. Install nginx ─────────────────────────────────────────────────────────
echo "==> Installing nginx…"
sudo apt-get update -q
sudo apt-get install -y -q nginx

# ── 5. Install mkcert and generate a trusted local certificate ───────────────
echo "==> Installing mkcert…"
if ! command -v mkcert &>/dev/null; then
    # Prefer the distro package; fall back to the upstream binary
    if apt-cache show mkcert &>/dev/null 2>&1; then
        sudo apt-get install -y -q mkcert
    else
        ARCH="$(dpkg --print-architecture)"
        MKCERT_VERSION="v1.4.4"
        case "$ARCH" in
            arm64)  BIN="mkcert-${MKCERT_VERSION}-linux-arm64" ;;
            armhf)  BIN="mkcert-${MKCERT_VERSION}-linux-arm" ;;
            amd64)  BIN="mkcert-${MKCERT_VERSION}-linux-amd64" ;;
            *)      echo "Unknown arch $ARCH — install mkcert manually."; exit 1 ;;
        esac
        sudo curl -fsSL "https://github.com/FiloSottile/mkcert/releases/download/${MKCERT_VERSION}/${BIN}" \
            -o /usr/local/bin/mkcert
        sudo chmod +x /usr/local/bin/mkcert
    fi
fi

echo "==> Installing mkcert CA into system trust store…"
# Must run as the current user so the CA lands in the right place
mkcert -install

echo "==> Generating TLS certificate for myrssfeed.local…"
sudo mkdir -p "$CERT_DIR"
# Generate into a temp dir then move, so nginx can read the key
TMPDIR="$(mktemp -d)"
pushd "$TMPDIR" > /dev/null
mkcert myrssfeed.local
sudo mv myrssfeed.local.pem     "$CERT_DIR/myrssfeed.local.pem"
sudo mv myrssfeed.local-key.pem "$CERT_DIR/myrssfeed.local-key.pem"
popd > /dev/null
sudo chmod 640 "$CERT_DIR/myrssfeed.local-key.pem"
sudo chown root:www-data "$CERT_DIR/myrssfeed.local-key.pem"

# ── 6. nginx site config ─────────────────────────────────────────────────────
echo "==> Configuring nginx…"
sudo cp "$APP_DIR/nginx/myrssfeed.conf" /etc/nginx/sites-available/myrssfeed
sudo ln -sf /etc/nginx/sites-available/myrssfeed /etc/nginx/sites-enabled/myrssfeed
# Remove default site if it's still enabled
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
echo "    nginx configured and reloaded."

# ── 7. mDNS hostname ─────────────────────────────────────────────────────────
echo "==> Setting mDNS hostname to ${HOSTNAME_MDNS}…"
sudo hostnamectl set-hostname "$HOSTNAME_MDNS"
# avahi-daemon provides .local mDNS resolution on the LAN
if ! command -v avahi-daemon &>/dev/null; then
    sudo apt-get install -y -q avahi-daemon
fi
sudo systemctl enable --now avahi-daemon
echo "    Hostname set. The Pi will respond to ${HOSTNAME_MDNS}.local on the network."

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo " myRSSfeed is ready!"
echo " Open on any device on this network:"
echo "   https://myrssfeed.local"
echo ""
echo " AI Digest is powered by ollama (model: phi3:mini)."
echo " To use a smarter model, go to Settings → AI Digest"
echo " and set the model to llama3.1:8b, then run:"
echo "   ollama pull llama3.1:8b"
echo ""
echo " To trust the certificate on each device, copy the mkcert CA from:"
echo "   \$(mkcert -CAROOT)/rootCA.pem"
echo " and install it as a trusted CA on each browser / OS."
echo ""
echo " View live logs from any browser on the LAN:"
echo "   https://myrssfeed.local/api/logs"
echo "=========================================="
