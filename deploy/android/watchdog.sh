#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# RAGI BOT — WATCHDOG (Android/Termux)
# ============================================
# Monitors the bot process and restarts it if it crashes.
# Run in background: bash watchdog.sh &
# Does NOT spawn uncontrolled processes — max 5 restarts in 30 minutes,
# then stops and waits for manual intervention.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/pids/ragi.pid"
WATCHDOG_PID_FILE="$SCRIPT_DIR/pids/watchdog.pid"
LOG_DIR="${LOG_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)/logs}"
LOG_FILE="$LOG_DIR/watchdog.log"

CHECK_INTERVAL=60       # seconds between checks
MAX_RESTARTS=5          # max restarts within the window
RESTART_WINDOW=1800     # 30 minutes in seconds
RESTART_COOLDOWN=300    # 5 min cooldown between restarts

mkdir -p "$SCRIPT_DIR/pids" "$LOG_DIR"

# Prevent duplicate watchdogs
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

log "Watchdog started (PID $$, checking every ${CHECK_INTERVAL}s)"

RESTART_TIMES=()

cleanup() {
    log "Watchdog stopping (signal received)"
    rm -f "$WATCHDOG_PID_FILE"
    exit 0
}
trap cleanup SIGTERM SIGINT

while true; do
    sleep "$CHECK_INTERVAL"

    # Check if bot is running
    if [ -f "$PID_FILE" ]; then
        BOT_PID=$(cat "$PID_FILE")
        if kill -0 "$BOT_PID" 2>/dev/null; then
            continue  # bot is healthy
        fi
    fi

    # Bot is not running — attempt restart
    log "Bot not running — attempting restart..."

    # Rate limit: count recent restarts
    NOW=$(date +%s)
    RECENT=()
    for T in "${RESTART_TIMES[@]}"; do
        if [ $((NOW - T)) -lt $RESTART_WINDOW ]; then
            RECENT+=("$T")
        fi
    done
    RESTART_TIMES=("${RECENT[@]}")

    if [ ${#RESTART_TIMES[@]} -ge $MAX_RESTARTS ]; then
        log "ERROR: $MAX_RESTARTS restarts in ${RESTART_WINDOW}s — entering safe mode."
        log "       Manual restart required: bash $SCRIPT_DIR/start_ragi.sh"
        # Wait a long time before trying again
        sleep 3600
        RESTART_TIMES=()
        continue
    fi

    # Cooldown between restarts
    if [ ${#RESTART_TIMES[@]} -gt 0 ]; then
        LAST_RESTART=${RESTART_TIMES[-1]}
        ELAPSED=$((NOW - LAST_RESTART))
        if [ $ELAPSED -lt $RESTART_COOLDOWN ]; then
            WAIT=$((RESTART_COOLDOWN - ELAPSED))
            log "Cooldown: waiting ${WAIT}s before restart..."
            sleep "$WAIT"
        fi
    fi

    # Restart
    RESTART_TIMES+=("$(date +%s)")
    bash "$SCRIPT_DIR/start_ragi.sh"

    if [ $? -eq 0 ]; then
        log "Bot restarted successfully."
    else
        log "WARNING: Restart script exited with error."
    fi
done
