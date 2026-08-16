#!/usr/bin/env bash
# ============================================
# RAGI BOT — INSTALLER (Linux Mint / Ubuntu / Debian)
# ============================================
# One-shot installer for a laptop/desktop that will host the bot 24/7.
# Safe to re-run: it will only install what is missing.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RAGI_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Ragi Bot Installer (Linux Mint) ==="
echo "  Repo: $RAGI_DIR"
echo

# --- System packages ----------------------------------------------------------
if command -v apt-get >/dev/null 2>&1; then
    echo "[install] Installing system packages (sudo required)..."
    sudo apt-get update
    sudo apt-get install -y \
        python3 python3-venv python3-pip python3-dev \
        build-essential libssl-dev libffi-dev \
        curl git sqlite3 tzdata
else
    echo "[install] apt-get not found — install python3, venv, build tools manually."
fi

cd "$RAGI_DIR"

# --- Virtual env --------------------------------------------------------------
if [ ! -d "venv" ]; then
    echo "[install] Creating virtual environment at $RAGI_DIR/venv"
    python3 -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate

echo "[install] Upgrading pip / wheel / setuptools"
pip install --upgrade pip wheel setuptools

echo "[install] Installing Python dependencies (requirements.txt)"
pip install -r requirements.txt

# --- .env skeleton ------------------------------------------------------------
if [ ! -f ".env" ]; then
    cat > .env <<'EOF'
# ============================================
# Ragi Bot — environment (Linux host, 24/7)
# ============================================
DEPLOYMENT_TARGET=linux
TRADING_MODE=paper           # paper | live  (start with paper!)
APP_PORT=8000

# --- Dashboard auth --------------------------
BOT_USERNAME=admin
BOT_PASSWORD=change-me
SESSION_SECRET=change-me-to-a-long-random-string

# --- AI provider (pick one) ------------------
AI_PROVIDER=anthropic_api
ANTHROPIC_API_KEY=

# --- Broker / data ---------------------------
GROWW_API_KEY=
GROWW_API_SECRET=

# --- Live trading (optional, only if TRADING_MODE=live) ---
ANGELONE_API_KEY=
ANGELONE_CLIENT_CODE=
ANGELONE_PIN=
ANGELONE_TOTP_SECRET=

# --- Telegram alerts -------------------------
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOF
    echo "[install] Wrote skeleton .env — edit it before starting the bot:"
    echo "          nano $RAGI_DIR/.env"
fi

# --- Directories --------------------------------------------------------------
mkdir -p "$RAGI_DIR/logs" "$RAGI_DIR/data_store/backups" "$SCRIPT_DIR/pids"

# --- Battery / sleep hint -----------------------------------------------------
cat <<EOM

=== Installation complete ===

Next steps:

  1. Edit credentials:
       nano $RAGI_DIR/.env

  2. (Recommended) Stop the laptop from sleeping when the lid is closed:
       sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
     (undo later with: sudo systemctl unmask ...)

  3. Start the bot manually to sanity-check:
       bash $SCRIPT_DIR/start_ragi.sh
       tail -f $RAGI_DIR/logs/ragi.log

  4. Install the systemd user service (survives reboots, auto-restarts):
       bash $SCRIPT_DIR/install_systemd_user.sh

  5. Dashboard: http://localhost:\${APP_PORT:-8000}

EOM
