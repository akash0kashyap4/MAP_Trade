#!/usr/bin/env bash
# ============================================
# RAGI BOT — WATCHDOG (Linux)
# ============================================
# Restarts the bot if it crashes. Run with: nohup bash watchdog.sh &
# Prefer the systemd user service (install_systemd_user.sh) for real 24/7 hosts.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/pids/ragi.pid"
WATCHDOG_PID_FILE="$SCRIPT_DIR/pids/watchdog.pid"
LOG_DIR="${LOG_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)/logs}"
LOG_FILE="$LOG_DIR/watchdog.log"

CHECK_INTERVAL=60
MAX_RESTARTS=5
RESTART_WINDOW=1800
RESTART_COOLDOWN=300

mkdir -p "$SCRIPT_DIR/pids" "$LOG_DIR"

if [ -f "$WATCHDOG_PID_FILE" ]; then
    OLD_PID=$(cat "$WATCHDOG_PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[watchdog] Already running (PID $OLD_PID). Exiting."
        exit 0
    fi
fi
echo "$$" > "$WATCHDOG_PID_FILE"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [watchdog] $1" >> "$LOG_FILE"
    echo "[watchdog] $1"
}
cleanup() { log "Watchdog stopping"; rm -f "$WATCHDOG_PID_FILE"; exit 0; }
trap cleanup SIGTERM SIGINT

log "Started (PID $$, interval ${CHECK_INTERVAL}s)"
RESTART_TIMES=()

while true; do
    sleep "$CHECK_INTERVAL"

    if [ -f "$PID_FILE" ]; then
        BOT_PID=$(cat "$PID_FILE")
        kill -0 "$BOT_PID" 2>/dev/null && continue
    fi

    log "Bot not running — attempting restart..."
    NOW=$(date +%s)
    RECENT=()
    for T in "${RESTART_TIMES[@]}"; do
        [ $((NOW - T)) -lt $RESTART_WINDOW ] && RECENT+=("$T")
    done
    RESTART_TIMES=("${RECENT[@]}")

    if [ ${#RESTART_TIMES[@]} -ge $MAX_RESTARTS ]; then
        log "ERROR: $MAX_RESTARTS restarts in ${RESTART_WINDOW}s — safe mode 1h."
        sleep 3600
        RESTART_TIMES=()
        continue
    fi

    if [ ${#RESTART_TIMES[@]} -gt 0 ]; then
        LAST=${RESTART_TIMES[-1]}
        ELAPSED=$((NOW - LAST))
        if [ $ELAPSED -lt $RESTART_COOLDOWN ]; then
            WAIT=$((RESTART_COOLDOWN - ELAPSED))
            log "Cooldown ${WAIT}s..."
            sleep "$WAIT"
        fi
    fi

    RESTART_TIMES+=("$(date +%s)")
    bash "$SCRIPT_DIR/start_ragi.sh" && log "Restart OK" || log "Restart FAILED"
done
