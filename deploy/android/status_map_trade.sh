#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# MAP TRADE BOT — STATUS CHECK (Android/Termux)
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAP_TRADE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$SCRIPT_DIR/pids/map_trade.pid"
WATCHDOG_PID_FILE="$SCRIPT_DIR/pids/watchdog.pid"
APP_PORT="${APP_PORT:-8000}"

echo "=== MAP TRADE Bot Status ==="
echo ""

# Bot process
if [ -f "$PID_FILE" ]; then
    BOT_PID=$(cat "$PID_FILE")
    if kill -0 "$BOT_PID" 2>/dev/null; then
        echo "  Bot:       RUNNING (PID $BOT_PID)"
        # Show memory usage
        if [ -f "/proc/$BOT_PID/status" ]; then
            RSS=$(grep VmRSS /proc/$BOT_PID/status 2>/dev/null | awk '{print $2, $3}')
            echo "  Memory:    $RSS"
        fi
    else
        echo "  Bot:       STOPPED (stale PID $BOT_PID)"
    fi
else
    echo "  Bot:       STOPPED (no PID file)"
fi

# Watchdog
if [ -f "$WATCHDOG_PID_FILE" ]; then
    WD_PID=$(cat "$WATCHDOG_PID_FILE")
    if kill -0 "$WD_PID" 2>/dev/null; then
        echo "  Watchdog:  ACTIVE (PID $WD_PID)"
    else
        echo "  Watchdog:  STOPPED (stale PID)"
    fi
else
    echo "  Watchdog:  NOT RUNNING"
fi

# HTTP health check
echo ""
echo "--- Health Check ---"
HEALTH=$(curl -s --connect-timeout 3 "http://localhost:$APP_PORT/health" 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$HEALTH" ]; then
    echo "  HTTP:      OK ($HEALTH)"
else
    echo "  HTTP:      UNREACHABLE (port $APP_PORT)"
fi

# Detailed health
DETAILED=$(curl -s --connect-timeout 3 "http://localhost:$APP_PORT/health/detailed" 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$DETAILED" ]; then
    echo ""
    echo "--- Detailed Health ---"
    echo "$DETAILED" | python -m json.tool 2>/dev/null || echo "$DETAILED"
fi

# Database
echo ""
echo "--- Database ---"
DB_FILE="$MAP_TRADE_DIR/data_store/trading_bot.db"
if [ -f "$DB_FILE" ]; then
    DB_SIZE=$(du -h "$DB_FILE" | cut -f1)
    echo "  SQLite:    $DB_FILE ($DB_SIZE)"
else
    echo "  SQLite:    not yet created"
fi

# Logs
echo ""
echo "--- Recent Log ---"
LOG_FILE="$MAP_TRADE_DIR/logs/map_trade.log"
if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(du -h "$LOG_FILE" | cut -f1)
    echo "  Log file:  $LOG_FILE ($LOG_SIZE)"
    echo "  Last 3 lines:"
    tail -3 "$LOG_FILE" 2>/dev/null | sed 's/^/    /'
else
    echo "  No log file yet."
fi

# Disk space
echo ""
echo "--- Disk ---"
df -h "$MAP_TRADE_DIR" 2>/dev/null | tail -1 | awk '{print "  Available: " $4 " of " $2}'

echo ""
echo "========================"
