#!/bin/bash
set -e

echo "[POT] Starting PO Token provider server on port 4416..."
# Start the bgutil POT provider HTTP server in the background
# This generates Proof-of-Origin tokens that make YouTube treat our requests as legitimate
python -m bgutil_ytdlp_pot_provider serve --port 4416 &
POT_PID=$!

# Give the POT server a moment to start
sleep 2

if kill -0 $POT_PID 2>/dev/null; then
    echo "[POT] PO Token provider is running (PID: $POT_PID)"
else
    echo "[POT] WARNING: PO Token provider failed to start, continuing without it"
fi

echo "[BOT] Starting Telegram bot..."
exec python bot.py
