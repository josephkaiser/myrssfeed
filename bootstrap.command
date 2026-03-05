#!/usr/bin/env bash
# myRSSfeed — first-time setup for macOS
#
# What this does:
#   1. Downloads the CA certificate from your myRSSfeed server (over HTTP)
#   2. Installs it into the macOS System Keychain so all browsers trust it
#   3. Opens https://myrssfeed.local in your browser
#
# How to use:
#   Double-click this file in Finder.  macOS will ask if you're sure — click Open.
#   You may be prompted for your Mac password to modify the System Keychain.
#
# The server address can be overridden:
#   ./bootstrap.command http://192.168.1.42
# ---------------------------------------------------------------------------
set -euo pipefail

SERVER="${1:-http://myrssfeed.local}"
CERT_TMP="$(mktemp /tmp/myrssfeed-ca.XXXXXX.crt)"

echo ""
echo "=========================================="
echo "  myRSSfeed — first-time device setup"
echo "=========================================="
echo ""
echo "Server: $SERVER"
echo ""

# ── 1. Fetch the CA certificate ──────────────────────────────────────────────
echo "Downloading CA certificate..."
if ! curl -fsSL --max-time 10 "$SERVER/ca.crt" -o "$CERT_TMP"; then
    echo ""
    echo "ERROR: Could not reach $SERVER"
    echo ""
    echo "Make sure:"
    echo "  • Your Mac is on the same Wi-Fi as the myRSSfeed server"
    echo "  • The server is running  (ping myrssfeed.local)"
    echo ""
    rm -f "$CERT_TMP"
    read -rp "Press Enter to close..."
    exit 1
fi
echo "  Certificate downloaded."

# ── 2. Install into System Keychain ──────────────────────────────────────────
echo ""
echo "Installing into System Keychain..."
echo "(You may be prompted for your Mac password)"
echo ""
if ! sudo security add-trusted-cert -d -r trustRoot \
       -k /Library/Keychains/System.keychain "$CERT_TMP"; then
    echo ""
    echo "ERROR: Could not install the certificate."
    echo "Try running this script again."
    rm -f "$CERT_TMP"
    read -rp "Press Enter to close..."
    exit 1
fi
rm -f "$CERT_TMP"
echo "  Certificate installed."

# ── 3. Open the site ─────────────────────────────────────────────────────────
HTTPS_URL="${SERVER/http:\/\//https://}"
HTTPS_URL="${HTTPS_URL/http:/https:}"   # fallback if already https
echo ""
echo "=========================================="
echo "  Done!  Opening $HTTPS_URL"
echo "=========================================="
echo ""
open "$HTTPS_URL" 2>/dev/null || true
