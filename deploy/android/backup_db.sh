#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# RAGI BOT — DATABASE BACKUP (Android/Termux)
# ============================================
# Creates a timestamped backup of the SQLite database.
# Safe to run while the bot is running (uses SQLite .backup command).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RAGI_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-$RAGI_DIR/data_store}"
DB_FILE="${DB_PATH:-$DATA_DIR/trading_bot.db}"
BACKUP_DIR="$DATA_DIR/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/trading_bot_${TIMESTAMP}.db"

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_FILE" ]; then
    echo "[backup] Database file not found: $DB_FILE"
    exit 1
fi

echo "[backup] Backing up $DB_FILE..."

# Use SQLite's .backup for a safe online backup
sqlite3 "$DB_FILE" ".backup '$BACKUP_FILE'" 2>/dev/null
if [ $? -eq 0 ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[backup] Backup created: $BACKUP_FILE ($BACKUP_SIZE)"
else
    # Fallback: simple copy (safe with WAL mode)
    cp "$DB_FILE" "$BACKUP_FILE"
    echo "[backup] Backup created (copy): $BACKUP_FILE"
fi

# Clean old backups — keep last 7
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/trading_bot_*.db 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt 7 ]; then
    ls -1t "$BACKUP_DIR"/trading_bot_*.db | tail -n +8 | xargs rm -f
    echo "[backup] Cleaned old backups. Keeping last 7."
fi

echo "[backup] Done."
echo ""
echo "To restore: cp $BACKUP_FILE $DB_FILE"
