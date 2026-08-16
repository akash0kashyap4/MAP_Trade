#!/usr/bin/env bash
# ============================================
# RAGI BOT — STOP (Linux)
# ============================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/pids/ragi.pid"
WATCHDOG_PID_FILE="$SCRIPT_DIR/pids/watchdog.pid"

if [ -f "$WATCHDOG_PID_FILE" ]; then
    WD_PID=$(cat "$WATCHDOG_PID_FILE")
    if kill -0 "$WD_PID" 2>/dev/null; then
        echo "[ragi] Stopping watchdog (PID $WD_PID)..."
        kill "$WD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$WATCHDOG_PID_FILE"
fi

if [ -f "$PID_FILE" ]; then
    BOT_PID=$(cat "$PID_FILE")
    if kill -0 "$BOT_PID" 2>/dev/null; then
        echo "[ragi] Stopping bot (PID $BOT_PID)..."
        kill -TERM "$BOT_PID" 2>/dev/null || true
        for _ in $(seq 1 10); do
            kill -0 "$BOT_PID" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$BOT_PID" 2>/dev/null; then
            echo "[ragi] Force killing (PID $BOT_PID)..."
            kill -9 "$BOT_PID" 2>/dev/null || true
        fi
        echo "[ragi] Bot stopped."
    else
        echo "[ragi] Bot not running (stale PID $BOT_PID)."
    fi
    rm -f "$PID_FILE"
else
    echo "[ragi] No PID file — bot is not running."
fi
