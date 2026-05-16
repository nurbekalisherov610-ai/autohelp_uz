#!/bin/bash
set -e

echo "Running preflight checks..."
python -m src.preflight || echo "[WARN] Preflight check had failures - review logs above"

echo "Running database migrations..."
# If migrations fail, we MUST exit 1 so Railway knows the deploy failed.
alembic upgrade head || { echo "❌ ERROR: Database migrations failed!"; exit 1; }

echo "Starting scheduler in background..."
python -m src.tasks.scheduler &

echo "Starting Telegram bot in background..."
python -m src.bot.main &

echo "Starting API server..."
exec python -m src.api.app
