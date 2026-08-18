#!/data/data/com.termux/files/usr/bin/bash
# ============================================
# MAP TRADE — ANDROID/TERMUX INSTALLATION
# ============================================
# Run this once to set up the environment on a Moto G51 (or any Android + Termux).
# Does NOT require root.

set -e

echo "=== MAP Trade — Android/Termux Installer ==="
echo ""

# Resolve project directory dynamically
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MAP_TRADE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Project directory: $MAP_TRADE_DIR"

# Step 1: Update Termux packages
echo ""
echo "[1/7] Updating Termux packages..."
pkg update -y
pkg upgrade -y

# Step 2: Install system dependencies
echo ""
echo "[2/7] Installing system dependencies..."
pkg install -y python python-pip git libffi openssl rust binutils

# Step 3: Create virtual environment
echo ""
echo "[3/7] Creating Python virtual environment..."
cd "$MAP_TRADE_DIR"
if [ ! -d "venv" ]; then
    python -m venv venv
    echo "  Virtual environment created."
else
    echo "  Virtual environment already exists."
fi

# Step 4: Install Python dependencies
echo ""
echo "[4/7] Installing Python dependencies..."
source venv/bin/activate

# Install core dependencies (skip asyncpg on Android — we use SQLite)
pip install --upgrade pip setuptools wheel
pip install fastapi uvicorn anthropic apscheduler pandas pydantic \
    yfinance aiosqlite requests aiohttp numpy python-telegram-bot \
    websockets python-dotenv pytz pyotp openpyxl 2>&1 | tail -5

# curl_cffi may fail on some ARM builds; optional
pip install curl_cffi 2>/dev/null || echo "  WARN: curl_cffi not available — yfinance will work without it"

# colorama is optional
pip install colorama 2>/dev/null || true

# growwapi and smartapi-python
pip install growwapi smartapi-python 2>/dev/null || echo "  WARN: broker SDKs not fully available on ARM"

echo "  Dependencies installed."

# Step 5: Create directory structure
echo ""
echo "[5/7] Creating directories..."
mkdir -p "$MAP_TRADE_DIR/data_store"
mkdir -p "$MAP_TRADE_DIR/logs"
mkdir -p "$MAP_TRADE_DIR/deploy/android/pids"

# Step 6: Create .env from example if not present
echo ""
echo "[6/7] Checking .env configuration..."
if [ ! -f "$MAP_TRADE_DIR/.env" ]; then
    cp "$MAP_TRADE_DIR/.env.example" "$MAP_TRADE_DIR/.env"
    # Set Android-specific defaults
    sed -i 's/# DEPLOYMENT_TARGET=android/DEPLOYMENT_TARGET=android/' "$MAP_TRADE_DIR/.env"
    echo "  Created .env from .env.example"
    echo "  *** IMPORTANT: Edit .env with your credentials before starting ***"
    echo "      nano $MAP_TRADE_DIR/.env"
else
    echo "  .env already exists — not overwriting."
fi

# Step 7: Set up Termux:Boot (optional auto-start after phone reboot)
echo ""
echo "[7/7] Termux:Boot setup (optional)..."
BOOT_DIR="$HOME/.termux/boot"
if [ -d "$BOOT_DIR" ] || command -v termux-boot >/dev/null 2>&1; then
    mkdir -p "$BOOT_DIR"
    cat > "$BOOT_DIR/start_map_trade.sh" << BOOTEOF
#!/data/data/com.termux/files/usr/bin/bash
# Auto-start MAP Trade after phone reboot (requires Termux:Boot app)
sleep 15  # wait for network
termux-wake-lock
cd "$MAP_TRADE_DIR"
bash deploy/android/start_map_trade.sh
BOOTEOF
    chmod +x "$BOOT_DIR/start_map_trade.sh"
    echo "  Termux:Boot script installed at $BOOT_DIR/start_map_trade.sh"
    echo "  Install the Termux:Boot app from F-Droid for auto-start on reboot."
else
    echo "  Termux:Boot not detected. Install from F-Droid for auto-start on reboot."
    echo "  After installing, re-run this script to set up boot entry."
fi

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env with your credentials:"
echo "     nano $MAP_TRADE_DIR/.env"
echo ""
echo "  2. Start the bot:"
echo "     bash $MAP_TRADE_DIR/deploy/android/start_map_trade.sh"
echo ""
echo "  3. Check status:"
echo "     bash $MAP_TRADE_DIR/deploy/android/status_map_trade.sh"
echo ""
echo "  4. View logs:"
echo "     tail -f $MAP_TRADE_DIR/logs/map_trade.log"
echo ""
echo "  5. (Optional) Enable watchdog for auto-restart:"
echo "     bash $MAP_TRADE_DIR/deploy/android/watchdog.sh &"
echo ""
echo "  6. (Optional) Install Ollama for local AI:"
echo "     See deploy/android/README.md for instructions"
echo ""
