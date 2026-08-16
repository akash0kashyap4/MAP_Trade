#!/usr/bin/env bash
# ============================================
# RAGI BOT — DB BACKUP (Linux)
# ============================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RAGI_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DB_FILE="$RAGI_DIR/data_store/trading_bot.db"
BACKUP_DIR="$RAGI_DIR/data_store/backups"
KEEP=14

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_FILE" ]; then
    echo "[backup] No DB at $DB_FILE — nothing to do."
    exit 0
fi

TS=$(date '+%Y%m%d_%H%M%S')
OUT="$BACKUP_DIR/trading_bot_$TS.db"
# online-safe copy via sqlite3
if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_FILE" ".backup '$OUT'"
else
    cp "$DB_FILE" "$OUT"
fi
echo "[backup] Wrote $OUT ($(du -h "$OUT" | cut -f1))"

# prune old
ls -1t "$BACKUP_DIR"/trading_bot_*.db 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r F; do
    echo "[backup] Pruning $F"
    rm -f "$F"
done
