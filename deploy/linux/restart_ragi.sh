#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
bash "$SCRIPT_DIR/stop_ragi.sh" || true
sleep 2
bash "$SCRIPT_DIR/start_ragi.sh"
