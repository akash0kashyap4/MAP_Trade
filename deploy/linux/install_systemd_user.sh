#!/usr/bin/env bash
# ============================================
# RAGI BOT — INSTALL SYSTEMD USER SERVICE
# ============================================
# Runs the bot as YOUR user (no root, no sudo), auto-starts on login,
# and — with `loginctl enable-linger` — also on boot before you log in.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RAGI_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
UNIT_SRC="$SCRIPT_DIR/ragi.service"

if [ "$RAGI_DIR" != "$HOME/Ragi_bot" ]; then
    echo "[systemd] NOTE: repo is at $RAGI_DIR but the unit file assumes \$HOME/Ragi_bot."
    echo "          Either symlink it:  ln -s '$RAGI_DIR' \"\$HOME/Ragi_bot\""
    echo "          or edit paths in $UNIT_SRC before continuing."
    read -r -p "Continue anyway? [y/N] " ans
    [ "$ans" = "y" ] || [ "$ans" = "Y" ] || exit 1
fi

DEST_DIR="$HOME/.config/systemd/user"
mkdir -p "$DEST_DIR"
cp "$UNIT_SRC" "$DEST_DIR/ragi.service"
echo "[systemd] Installed $DEST_DIR/ragi.service"

systemctl --user daemon-reload
systemctl --user enable ragi.service
systemctl --user restart ragi.service

echo
echo "[systemd] Enabling linger so the service runs on boot without login:"
if command -v loginctl >/dev/null 2>&1; then
    sudo loginctl enable-linger "$USER" || echo "  (skipped — enable manually with: sudo loginctl enable-linger $USER)"
fi

echo
echo "=== Done ==="
echo "  Status:   systemctl --user status ragi.service"
echo "  Logs:     journalctl --user -u ragi.service -f"
echo "            tail -f $RAGI_DIR/logs/ragi.log"
echo "  Stop:     systemctl --user stop ragi.service"
echo "  Disable:  systemctl --user disable --now ragi.service"
