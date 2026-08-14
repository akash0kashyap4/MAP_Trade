#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# RAGI BOT — RESTART (Android/Termux)
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[ragi] Restarting bot..."
bash "$SCRIPT_DIR/stop_ragi.sh"
sleep 2
bash "$SCRIPT_DIR/start_ragi.sh"
