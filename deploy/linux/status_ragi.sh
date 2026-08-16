#!/usr/bin/env bash
# ============================================
# RAGI BOT — STATUS (Linux)
# ============================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RAGI_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="$SCRIPT_DIR/pids/ragi.pid"
WATCHDOG_PID_FILE="$SCRIPT_DIR/pids/watchdog.pid"
APP_PORT="${APP_PORT:-8000}"

echo "=== Ragi Bot Status ==="

if [ -f "$PID_FILE" ]; then
    BOT_PID=$(cat "$PID_FILE")
    if kill -0 "$BOT_PID" 2>/dev/null; then
        echo "  Bot:       RUNNING (PID $BOT_PID)"
        RSS=$(grep VmRSS "/proc/$BOT_PID/status" 2>/dev/null | awk '{print $2, $3}')
        [ -n "$RSS" ] && echo "  Memory:    $RSS"
        UPTIME=$(ps -o etime= -p "$BOT_PID" 2>/dev/null | tr -d ' ')
        [ -n "$UPTIME" ] && echo "  Uptime:    $UPTIME"
    else
        echo "  Bot:       STOPPED (stale PID $BOT_PID)"
    fi
else
    echo "  Bot:       STOPPED (no PID file)"
fi

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

echo
echo "--- systemd (user) ---"
if systemctl --user list-unit-files 2>/dev/null | grep -q '^ragi\.service'; then
    systemctl --user status ragi.service --no-pager -n 3 2>/dev/null | sed 's/^/  /'
else
    echo "  ragi.service not installed (see install_systemd_user.sh)"
fi

echo
echo "--- Health Check ---"
HEALTH=$(curl -s --connect-timeout 3 "http://localhost:$APP_PORT/health" 2>/dev/null || true)
if [ -n "$HEALTH" ]; then
    echo "  HTTP:      OK ($HEALTH)"
else
    echo "  HTTP:      UNREACHABLE (port $APP_PORT)"
fi

echo
DB_FILE="$RAGI_DIR/data_store/trading_bot.db"
if [ -f "$DB_FILE" ]; then
    echo "  SQLite:    $DB_FILE ($(du -h "$DB_FILE" | cut -f1))"
else
    echo "  SQLite:    not yet created"
fi

LOG_FILE="$RAGI_DIR/logs/ragi.log"
if [ -f "$LOG_FILE" ]; then
    echo "  Log:       $LOG_FILE ($(du -h "$LOG_FILE" | cut -f1))"
    echo "  Last 3 lines:"
    tail -3 "$LOG_FILE" 2>/dev/null | sed 's/^/    /'
fi

echo
df -h "$RAGI_DIR" 2>/dev/null | tail -1 | awk '{print "  Disk free: " $4 " of " $2}'
echo "========================"
