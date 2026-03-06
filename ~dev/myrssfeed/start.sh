#!/usr/bin/env bash
# start.sh — one-command dev startup for myRSSfeed
#
# What this does (each step is idempotent and safe to re-run):
#   1. Creates a Python venv if one doesn't exist
#   2. Installs / syncs dependencies from requirements.txt
#   3. Starts ollama if it isn't already running
#   4. Pulls the default model (phi3:mini) if not already available
#   5. Starts the myRSSfeed app (foreground — Ctrl+C to stop)
#
# Usage:
#   bash start.sh
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
DEFAULT_MODEL="phi3:mini"
OLLAMA_URL="http://localhost:11434"

# ── Colours ──────────────────────────────────────────────────────────────────
_green()  { printf '\033[32m%s\033[0m\n' "$*"; }
_yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
_red()    { printf '\033[31m%s\033[0m\n' "$*"; }

# ── 1. Python venv ────────────────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "==> Creating Python virtual environment…"
    python3 -m venv "$VENV_DIR"
fi

# ── 2. Dependencies ───────────────────────────────────────────────────────────
echo "==> Syncing Python dependencies…"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
_green "    Dependencies up to date."

# ── 3. ollama ─────────────────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    _yellow "    ollama not found — digest feature will be unavailable."
    _yellow "    Install from https://ollama.ai and re-run to enable it."
else
    if curl -sf "$OLLAMA_URL" > /dev/null 2>&1; then
        _green "==> ollama already running."
    else
        echo "==> Starting ollama…"
        ollama serve >> "$APP_DIR/logs/ollama.log" 2>&1 &
        OLLAMA_PID=$!
        echo "    PID $OLLAMA_PID — logs at logs/ollama.log"

        # Wait up to 15 s for ollama to become ready
        for i in $(seq 1 15); do
            if curl -sf "$OLLAMA_URL" > /dev/null 2>&1; then
                _green "    ollama ready."
                break
            fi
            if [ "$i" -eq 15 ]; then
                _red "    ollama did not start within 15 s — digest will be unavailable."
            fi
            sleep 1
        done
    fi

    # ── 4. Pull default model if missing ─────────────────────────────────────
    if curl -sf "$OLLAMA_URL" > /dev/null 2>&1; then
        if ollama list 2>/dev/null | grep -q "^${DEFAULT_MODEL}"; then
            _green "==> Model '$DEFAULT_MODEL' already available."
        else
            echo "==> Pulling model '$DEFAULT_MODEL' (first-time download, may take a few minutes)…"
            ollama pull "$DEFAULT_MODEL"
            _green "    Model ready."
        fi
    fi
fi

# ── 5. Create logs dir (main.py also does this, but be explicit) ──────────────
mkdir -p "$APP_DIR/logs"

# ── 6. Start the app ──────────────────────────────────────────────────────────
echo ""
_green "==> Starting myRSSfeed at http://localhost:8080"
echo "    Press Ctrl+C to stop."
echo ""
exec "$VENV_DIR/bin/python" "$APP_DIR/main.py"
