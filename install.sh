#!/usr/bin/env bash
# install.sh — sets up myRSSfeed on Raspberry Pi / Debian
#
# What this does:
#   1. Creates a Python venv and installs dependencies
#   2. Registers the app as a systemd service (port 8080, loopback only)
#   3. Installs nginx and mkcert
#   4. Generates a locally-trusted TLS certificate for myrssfeed.local
#   5. Drops the nginx site config in place and enables it
#   6. Sets the Pi's mDNS hostname so the site resolves as myrssfeed.local
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

# ── 2. systemd service (binds only to loopback) ─────────────────────────────
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

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ${SERVICE_NAME}.service
echo "    myRSSfeed service started on 127.0.0.1:8080"

# ── 3. Install nginx ─────────────────────────────────────────────────────────
echo "==> Installing nginx…"
sudo apt-get update -q
sudo apt-get install -y -q nginx

# ── 4. Install mkcert and generate a trusted local certificate ───────────────
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

# ── 5. nginx site config ─────────────────────────────────────────────────────
echo "==> Configuring nginx…"
sudo cp "$APP_DIR/nginx/myrssfeed.conf" /etc/nginx/sites-available/myrssfeed
sudo ln -sf /etc/nginx/sites-available/myrssfeed /etc/nginx/sites-enabled/myrssfeed
# Remove default site if it's still enabled
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
echo "    nginx configured and reloaded."

# ── 6. mDNS hostname ─────────────────────────────────────────────────────────
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
echo " To trust the certificate on each device, copy the mkcert CA from:"
echo "   \$(mkcert -CAROOT)/rootCA.pem"
echo " and install it as a trusted CA on each browser / OS."
echo "=========================================="
