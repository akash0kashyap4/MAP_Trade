#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# RAGI BOT — START (Android/Termux)
# ============================================
# Starts the trading bot with PID tracking and log redirection.
# Does NOT require root. Safe to run multiple times (prevents duplicates).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RAGI_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_DIR="$SCRIPT_DIR/pids"
PID_FILE="$PID_DIR/ragi.pid"
LOG_DIR="${LOG_DIR:-$RAGI_DIR/logs}"
LOG_FILE="$LOG_DIR/ragi.log"

mkdir -p "$PID_DIR" "$LOG_DIR"

# Prevent duplicate processes
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[ragi] Bot is already running (PID $OLD_PID)."
        echo "       Use stop_ragi.sh first, or restart_ragi.sh"
        exit 1
    else
        echo "[ragi] Stale PID file found (process $OLD_PID not running). Cleaning up."
        rm -f "$PID_FILE"
    fi
fi

cd "$RAGI_DIR"

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "[ragi] ERROR: Virtual environment not found at $RAGI_DIR/venv"
    echo "       Run install_android.sh first."
    exit 1
fi

# Load environment
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
else
    echo "[ragi] WARNING: .env file not found. Using defaults."
fi

# Ensure Android deployment target is set
export DEPLOYMENT_TARGET="${DEPLOYMENT_TARGET:-android}"
export TRADING_MODE="${TRADING_MODE:-paper}"

# Acquire Termux wake lock to prevent Android from killing the process
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock 2>/dev/null || true
fi

echo "=== Ragi Bot Starting ==="
echo "  Directory:  $RAGI_DIR"
echo "  Target:     $DEPLOYMENT_TARGET"
echo "  Mode:       $TRADING_MODE"
echo "  Port:       ${APP_PORT:-8000}"
echo "  Log:        $LOG_FILE"
echo "  PID file:   $PID_FILE"
echo "=========================="

# Start the bot in the background
nohup python main.py >> "$LOG_FILE" 2>&1 &
BOT_PID=$!
echo "$BOT_PID" > "$PID_FILE"

# Wait a moment and verify it started
sleep 3
if kill -0 "$BOT_PID" 2>/dev/null; then
    echo "[ragi] Bot started successfully (PID $BOT_PID)"
    echo "       Dashboard: http://localhost:${APP_PORT:-8000}"
    echo "       Logs: tail -f $LOG_FILE"
else
    echo "[ragi] ERROR: Bot failed to start. Check logs:"
    echo "       tail -20 $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
