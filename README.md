# 🚗 AutoHelp.uz — Telegram Bot

> **24/7 Roadside Assistance Dispatch System**
> Built with Python • Aiogram 3 • PostgreSQL • Redis • Docker

---

## 📋 Overview

AutoHelp.uz automates the entire workflow of an auto emergency company:

1. **Driver** creates an emergency request via Telegram bot
2. **Dispatcher** receives notification, assigns a **Master** (mechanic)
3. **Dispatcher** sends video confirmation to the driver
4. **Master** accepts, navigates via Google Maps, fixes the issue
5. **Master** records completion video, enters payment amount
6. **Driver** rates the service (1-5 stars)
7. **Admin** monitors everything via dashboard & reports

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 16
- Redis 7
- Docker & Docker Compose (for production)

### Local Development

```bash
# 1. Clone and enter the project
cd auto_help

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup environment variables
copy .env.example .env
# Edit .env with your values (BOT_TOKEN, DB credentials, etc.)

# 5. Initialize database
python seed.py

# 6. Add initial staff
python manage.py add_dispatcher <TELEGRAM_ID> "Dispatcher Name" "+998901234567"
python manage.py add_master <TELEGRAM_ID> "Master Name" "+998901234567"

# 7. Run the bot
python main.py
```

### Production (Docker)

```bash
# 1. Copy files to server
scp -r . root@your-server:/opt/autohelp/

# 2. SSH into server
ssh root@your-server

# 3. Run deployment script
cd /opt/autohelp
chmod +x deploy.sh
./deploy.sh

# 4. Configure .env
cp .env.example .env
nano .env

# 5. Start all services
docker compose up -d

# 6. Seed database
docker compose exec bot python seed.py

# 7. Add staff
docker compose exec bot python manage.py add_dispatcher 123456789 "Ali" "+998901234567"
docker compose exec bot python manage.py add_master 987654321 "Usta Vali" "+998907654321"
```

---

## 🏗 Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Driver 🚗   │     │ Dispatcher 📋│     │  Master 🔧   │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       └────────────────────┼────────────────────┘
                            │
                    ┌───────▼───────┐
                    │ Telegram API  │
                    └───────┬───────┘
                            │
                    ┌───────▼───────┐
                    │  Aiogram 3    │
                    │  Bot Engine   │
                    └──┬─────┬──┬──┘
                       │     │  │
              ┌────────┘     │  └────────┐
              ▼              ▼           ▼
        ┌──────────┐  ┌──────────┐ ┌──────────┐
        │PostgreSQL│  │  Redis   │ │APScheduler│
        │    16    │  │    7     │ │  Tasks    │
        └──────────┘  └──────────┘ └──────────┘
```

---

## 📁 Project Structure

```
auto_help/
├── alembic/              # Database migrations
├── bot/                  # Telegram bot logic
│   ├── handlers/         # Message & callback handlers
│   │   ├── client/       # Driver flow
│   │   ├── dispatcher/   # Dispatcher flow
│   │   ├── master/       # Master flow
│   │   └── admin/        # Admin commands
│   ├── keyboards/        # Inline & reply keyboards
│   ├── states/           # FSM states
│   ├── middlewares/      # Auth, DB, throttling
│   └── filters/          # Role-based filters
├── core/                 # Configuration, DB, Redis
├── locales/              # i18n (Uzbek + Russian)
├── models/               # SQLAlchemy models
├── repositories/         # Database access layer
├── schemas/              # Pydantic validation
├── services/             # Business logic
├── tasks/                # Background tasks (SLA, backup, reports)
├── web/                  # FastAPI admin panel
├── main.py               # Entry point
├── manage.py             # CLI management tool
├── seed.py               # Database seeding
├── docker-compose.yml    # Docker orchestration
├── Dockerfile            # Container image
└── nginx.conf            # Reverse proxy config
```

---

## 🔧 Management CLI

```bash
# Add a master
python manage.py add_master 123456789 "Usta Akbar" "+998901234567"

# Add a dispatcher
python manage.py add_dispatcher 987654321 "Dispatcher Ali" "+998907654321"

# List all masters
python manage.py list_masters

# List all staff
python manage.py list_staff

# View statistics
python manage.py stats
```

---

## ⚙️ Configuration (.env)

| Variable | Description | Default |
|----------|-----------|---------|
| `BOT_TOKEN` | Telegram Bot API token | required |
| `ADMIN_IDS` | Comma-separated admin Telegram IDs | required |
| `DISPATCHER_GROUP_ID` | Telegram group chat ID (optional, for hybrid/group mode) | 0 |
| `DISPATCH_MODE` | Dispatch routing mode: `bot_only` / `hybrid` / `group_only` | bot_only |
| `VIDEO_CHANNEL_ID` | Channel for video confirmations | required |
| `DB_HOST` | PostgreSQL host | localhost |
| `DB_PORT` | PostgreSQL port | 5432 |
| `DB_NAME` | Database name | autohelp |
| `DB_USER` | Database user | autohelp_user |
| `DB_PASSWORD` | Database password | required |
| `REDIS_HOST` | Redis host | localhost |
| `REDIS_PASSWORD` | Redis password | required |
| `SLA_ASSIGN_TIMEOUT` | Minutes before assignment alert | 5 |
| `SLA_ON_THE_WAY_TIMEOUT` | Minutes before travel alert | 60 |
| `SLA_CONFIRM_TIMEOUT` | Minutes before confirmation alert | 15 |

Recommended for one dispatcher: set `DISPATCH_MODE=bot_only`.

---

## 📊 Monitoring

- **Uptime Kuma**: http://your-server:3001 (auto-deployed with Docker)
- **Admin Dashboard**: https://autohelp.uz (FastAPI web panel)
- **Bot Reports**: Daily at 23:55, Weekly on Mondays at 08:00

---

## 📄 License

Proprietary — AutoHelp.uz © 2026
