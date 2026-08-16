#!/usr/bin/env bash
# ============================================
# RAGI BOT — START (Linux)
# ============================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RAGI_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_DIR="$SCRIPT_DIR/pids"
PID_FILE="$PID_DIR/ragi.pid"
LOG_DIR="${LOG_DIR:-$RAGI_DIR/logs}"
LOG_FILE="$LOG_DIR/ragi.log"

mkdir -p "$PID_DIR" "$LOG_DIR"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[ragi] Bot already running (PID $OLD_PID). Use stop_ragi.sh / restart_ragi.sh."
        exit 1
    else
        echo "[ragi] Stale PID file — cleaning up."
        rm -f "$PID_FILE"
    fi
fi

cd "$RAGI_DIR"

if [ ! -f "venv/bin/activate" ]; then
    echo "[ragi] ERROR: venv not found. Run install_linux.sh first."
    exit 1
fi
# shellcheck disable=SC1091
source venv/bin/activate

if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
else
    echo "[ragi] WARNING: .env not found — using defaults."
fi

export DEPLOYMENT_TARGET="${DEPLOYMENT_TARGET:-linux}"
export TRADING_MODE="${TRADING_MODE:-paper}"

echo "=== Ragi Bot Starting ==="
echo "  Directory:  $RAGI_DIR"
echo "  Target:     $DEPLOYMENT_TARGET"
echo "  Mode:       $TRADING_MODE"
echo "  Port:       ${APP_PORT:-8000}"
echo "  Log:        $LOG_FILE"
echo "=========================="

nohup python main.py >> "$LOG_FILE" 2>&1 &
BOT_PID=$!
echo "$BOT_PID" > "$PID_FILE"

sleep 3
if kill -0 "$BOT_PID" 2>/dev/null; then
    echo "[ragi] Bot started (PID $BOT_PID). Dashboard: http://localhost:${APP_PORT:-8000}"
    echo "       tail -f $LOG_FILE"
else
    echo "[ragi] ERROR: Bot failed to start. Last 20 log lines:"
    tail -20 "$LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
