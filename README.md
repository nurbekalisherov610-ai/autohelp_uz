# AutoHelp.uz Emergency Bot Platform

Production-ready Python backend for AutoHelp.uz Telegram operations:
- Driver emergency order flow
- Dispatcher queue and assignment flow
- Master status workflow
- API + scheduler for 24/7 operations

## Core Stack
- Python 3.11+
- Aiogram 3 (Telegram bot)
- FastAPI (admin/API surface)
- PostgreSQL 16
- Redis 7
- APScheduler
- Docker + Docker Compose
- Alembic migrations

## Project Structure
- `src/bot`: Telegram bot logic
- `src/api`: FastAPI endpoints
- `src/services`: business service layer
- `src/db`: SQLAlchemy models/session/init
- `src/tasks`: scheduler jobs (SLA checks)
- `src/core`: config, logging, startup dependency checks
- `alembic`: migration scripts

## Quick Start
1. Copy env template:
```powershell
Copy-Item .env.example .env
```
2. Fill `.env` at minimum:
- `BOT_TOKEN`
- `DISPATCHER_CHAT_ID`
- For production: `POSTGRES_*` and `REDIS_*` (or `DATABASE_URL` + `REDIS_URL`)

## Run Modes
### Local mode (fast start, no Docker required)
Use SQLite + in-memory FSM storage:
```powershell
Copy-Item .env.local.example .env
```
or set these keys in current `.env`:
```env
APP_ENV=dev
DATABASE_URL=sqlite+aiosqlite:///./autohelp_local.db
USE_REDIS=false
AUTO_CREATE_SCHEMA=true
```
Run services:
```powershell
python -m src.preflight
python -m src.bot.main
```
```powershell
python -m src.api.app
```
```powershell
python -m src.tasks.scheduler
```

### Production mode (24/7 recommended)
Use PostgreSQL + Redis + Docker Compose.
3. Run:
```powershell
docker compose up --build
```
4. Compose flow:
- `migrate` runs `alembic upgrade head`
- then `api`, `bot`, `scheduler` start

## Preflight Check (Required Before Launch)
Run:
```powershell
python -m src.preflight
```
This verifies:
- Bot token validity
- Dispatcher chat configuration
- Database connectivity
- Redis connectivity (if `USE_REDIS=true`)
- Startup retry tuning

## Driver Flow
1. Tap `Tez yordam chaqirish`
2. Choose issue:
- `Zavod bo'lmayapti`
- `Akkumulyator o'tirgan`
- `Balon yorilgan`
- `Boshqa muammo`
3. Share phone
4. Share location
5. Confirm order

## Dispatcher Commands
- `/new_orders` - show NEW queue
- Inline `Qabul qilish #ID` - move `NEW -> ASSIGNED`
- `/assign_master <order_id> <master_telegram_id>` - attach master
- `/complete_order <order_id> <summa>` - move `AWAITING_CONFIRM -> COMPLETED`

## Master Commands
- `/master_help`
- `/my_jobs`
- `/accept <order_id>` - `ASSIGNED -> ACCEPTED`
- `/reject <order_id>` - `ASSIGNED -> REJECTED`
- `/status <order_id> <on_the_way|arrived|in_progress|awaiting_confirm>`

## API Endpoints
- `GET /health`
- `GET /ready`
- `GET /orders/new`
- `GET /orders/{order_id}`
- `GET /orders/master/{master_telegram_id}`
- `GET /stats/summary`

## 24/7 Reliability
- Dependency wait/retry on startup (DB + Redis)
- Redis FSM storage for bot sessions
- Global bot error handler
- Dedicated async scheduler with SLA watchdog:
  - `ASSIGNED > 5 min`
  - `ON_THE_WAY > 60 min`
  - `AWAITING_CONFIRM > 15 min`
- Optional local fallback mode: SQLite + in-memory FSM (`USE_REDIS=false`) for quick setup/testing.

## Migrations
Run manually if needed:
```powershell
alembic upgrade head
```

## Security Note
If a bot token is ever exposed, rotate it immediately in BotFather and update `.env`.
