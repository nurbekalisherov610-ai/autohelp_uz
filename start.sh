#!/bin/bash

echo "Running preflight checks..."
python -m src.preflight || echo "[WARN] Preflight check had failures - review logs above"

echo "Running database migrations..."
alembic upgrade head

echo "Starting scheduler in background..."
python -m src.tasks.scheduler &

echo "Starting Telegram bot in background..."
python -m src.bot.main &

echo "Starting API server..."
exec python -m src.api.app
