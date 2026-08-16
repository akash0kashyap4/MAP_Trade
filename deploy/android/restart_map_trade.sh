#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# MAP TRADE BOT — RESTART (Android/Termux)
# ============================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[map_trade] Restarting bot..."
bash "$SCRIPT_DIR/stop_map_trade.sh"
sleep 2
bash "$SCRIPT_DIR/start_map_trade.sh"
