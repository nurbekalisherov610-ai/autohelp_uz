#!/bin/bash
set -e

echo "========================================="
echo " AutoHelp Bot — Startup"
echo "========================================="

echo "[1/4] Running preflight checks..."
python -m src.preflight || echo "[WARN] Preflight had warnings — see above"

echo "[2/4] Running database migrations..."
alembic upgrade head || { echo "ERROR: Database migrations failed!"; exit 1; }

echo "[3/4] Starting scheduler in background..."
python -m src.tasks.scheduler &
SCHEDULER_PID=$!
echo "Scheduler PID: $SCHEDULER_PID"

echo "[4/4] Starting Telegram bot (foreground)..."
# Bot is the main process — Railway tracks this for health/restart.
# If the bot exits, Railway will restart the whole container (including scheduler).
exec python -m src.bot.main
