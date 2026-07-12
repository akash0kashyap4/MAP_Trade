#!/bin/bash
# ============================================
# RAGI BOT DEPLOYMENT STARTUP SCRIPT
# ============================================

cd /home/user/Ragi_bot

echo "🚀 Starting Ragi Bot deployment..."

# Step 1: Activate virtual environment
echo "✓ Activating virtual environment..."
source venv/bin/activate

# Step 2: Load environment variables
if [ -f .env ]; then
    echo "✓ Loading environment from .env"
    export $(cat .env | xargs)
else
    echo "⚠️  WARNING: .env file not found!"
    echo "   Copy .env.deploy to .env and set your credentials:"
    echo "   cp .env.deploy .env"
    echo "   nano .env"
    exit 1
fi

# Step 3: Clean old database (if this is first deployment)
if [ -f "trading_bot.db" ] && [ ! -f "trading_bot.db.backup" ]; then
    echo "⚠️  Backing up old database (from before F-1 fix)..."
    mv trading_bot.db trading_bot.db.backup
fi

# Step 4: Verify environment variables
echo "✓ Verifying required environment variables..."
for var in BOT_USERNAME BOT_PASSWORD SESSION_SECRET ANTHROPIC_API_KEY GROWW_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
    if [ -z "${!var}" ]; then
        echo "❌ Missing: $var"
        exit 1
    fi
done
echo "✓ All required variables set"

# Step 5: Start the application
echo ""
echo "═══════════════════════════════════════════════════════"
echo "🎯 RAGI BOT IS STARTING"
echo "═══════════════════════════════════════════════════════"
echo "Port: ${BOT_PORT:-8999}"
echo "Database: ${DATABASE_URL:-sqlite:///trading_bot.db}"
echo "Mode: PAPER (switch to LIVE via Settings)"
echo ""
echo "Login at: http://localhost:${BOT_PORT:-8999}"
echo "Username: ${BOT_USERNAME}"
echo ""
echo "Watch for log: [DB] Initialized SQLite DB"
echo "═══════════════════════════════════════════════════════"
echo ""

python main.py
