#!/bin/bash
set -e

echo "========================================="
echo " AutoHelp Bot — Startup"
echo "========================================="

echo "[1/4] Running preflight checks..."
python -m src.preflight || echo "[WARN] Preflight had warnings — see above"

echo "[2/4] Running database migrations..."
alembic upgrade head || { echo "ERROR: Database migrations failed!"; exit 1; }

echo "[3/4] Starting Telegram bot..."
# Run bot as the main foreground process so Railway tracks its health
python -m src.bot.main
