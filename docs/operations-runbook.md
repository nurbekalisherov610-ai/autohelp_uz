# Operations Runbook (24/7)

## 1) First Deployment
1. Configure `.env`
2. Rotate bot token if it was ever shared
3. Run preflight:
   - `python -m src.preflight`
4. Run:
   - `docker compose up --build -d`
5. Verify:
   - `GET /health`
   - `GET /ready`
   - Bot responds to `/start`

## 1.1) Local Dry Run (without Redis/Postgres)
Use only for development/quick smoke tests:
- `DATABASE_URL=sqlite+aiosqlite:///./autohelp_local.db`
- `USE_REDIS=false`
- `AUTO_CREATE_SCHEMA=true`
- Start each service directly:
  - `python -m src.bot.main`
  - `python -m src.api.app`
  - `python -m src.tasks.scheduler`

## 2) Safe Upgrade
1. Pull new code
2. Run migration:
   - `docker compose run --rm migrate`
3. Restart app services:
   - `docker compose up --build -d api bot scheduler`

## 3) Incident Basics
- If bot stops responding:
  - Check `bot` logs
  - Check Redis availability
- If orders do not persist:
  - Check `db` and `migrate` logs
- If stale orders are not alerted:
  - Check `scheduler` logs and bot token validity

## 4) Backups
- Keep daily PostgreSQL dumps
- Keep at least 30 days retention
- Test restore monthly on staging

## 5) Security
- Never commit `.env`
- Rotate compromised bot token immediately in BotFather
- Restrict DB and Redis ports at firewall level in production
