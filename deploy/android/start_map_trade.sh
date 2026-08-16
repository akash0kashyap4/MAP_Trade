#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# MAP TRADE BOT — START (Android/Termux)
# ============================================
# Starts the trading bot with PID tracking and log redirection.
# Does NOT require root. Safe to run multiple times (prevents duplicates).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAP_TRADE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_DIR="$SCRIPT_DIR/pids"
PID_FILE="$PID_DIR/map_trade.pid"
LOG_DIR="${LOG_DIR:-$MAP_TRADE_DIR/logs}"
LOG_FILE="$LOG_DIR/map_trade.log"

mkdir -p "$PID_DIR" "$LOG_DIR"

# Prevent duplicate processes
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[map_trade] Bot is already running (PID $OLD_PID)."
        echo "       Use stop_map_trade.sh first, or restart_map_trade.sh"
        exit 1
    else
        echo "[map_trade] Stale PID file found (process $OLD_PID not running). Cleaning up."
        rm -f "$PID_FILE"
    fi
fi

cd "$MAP_TRADE_DIR"

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "[map_trade] ERROR: Virtual environment not found at $MAP_TRADE_DIR/venv"
    echo "       Run install_android.sh first."
    exit 1
fi

# Load environment
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
else
    echo "[map_trade] WARNING: .env file not found. Using defaults."
fi

# Ensure Android deployment target is set
export DEPLOYMENT_TARGET="${DEPLOYMENT_TARGET:-android}"
export TRADING_MODE="${TRADING_MODE:-paper}"

# Acquire Termux wake lock to prevent Android from killing the process
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock 2>/dev/null || true
fi

echo "=== MAP TRADE Bot Starting ==="
echo "  Directory:  $MAP_TRADE_DIR"
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
    echo "[map_trade] Bot started successfully (PID $BOT_PID)"
    echo "       Dashboard: http://localhost:${APP_PORT:-8000}"
    echo "       Logs: tail -f $LOG_FILE"
else
    echo "[map_trade] ERROR: Bot failed to start. Check logs:"
    echo "       tail -20 $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
