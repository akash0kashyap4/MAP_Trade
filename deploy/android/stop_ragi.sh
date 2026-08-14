#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# RAGI BOT — STOP (Android/Termux)
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RAGI_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$SCRIPT_DIR/pids/ragi.pid"
WATCHDOG_PID_FILE="$SCRIPT_DIR/pids/watchdog.pid"

# Stop watchdog first (prevents it from restarting the bot)
if [ -f "$WATCHDOG_PID_FILE" ]; then
    WD_PID=$(cat "$WATCHDOG_PID_FILE")
    if kill -0 "$WD_PID" 2>/dev/null; then
        echo "[ragi] Stopping watchdog (PID $WD_PID)..."
        kill "$WD_PID" 2>/dev/null
        sleep 1
    fi
    rm -f "$WATCHDOG_PID_FILE"
fi

# Stop bot
if [ -f "$PID_FILE" ]; then
    BOT_PID=$(cat "$PID_FILE")
    if kill -0 "$BOT_PID" 2>/dev/null; then
        echo "[ragi] Stopping bot (PID $BOT_PID)..."
        kill -TERM "$BOT_PID" 2>/dev/null
        # Wait up to 10 seconds for graceful shutdown
        for i in $(seq 1 10); do
            if ! kill -0 "$BOT_PID" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        # Force kill if still running
        if kill -0 "$BOT_PID" 2>/dev/null; then
            echo "[ragi] Force killing (PID $BOT_PID)..."
            kill -9 "$BOT_PID" 2>/dev/null
        fi
        echo "[ragi] Bot stopped."
    else
        echo "[ragi] Bot not running (PID $BOT_PID from file is stale)."
    fi
    rm -f "$PID_FILE"
else
    echo "[ragi] No PID file found — bot is not running."
fi

# Release wake lock
if command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock 2>/dev/null || true
fi
