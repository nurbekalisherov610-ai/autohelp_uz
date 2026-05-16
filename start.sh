#!/bin/bash
set -e

echo "Running preflight checks..."
python -m src.preflight

echo "Running database migrations..."
alembic upgrade head

echo "Starting scheduler in background..."
python -m src.tasks.scheduler &

echo "Starting Telegram bot in background..."
python -m src.bot.main &

echo "Starting API server..."
python -m src.api.app
