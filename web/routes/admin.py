"""
AutoHelp.uz - Web Admin Panel (FastAPI)
Lightweight admin dashboard with Jinja2 templates and HTMX.
"""
from datetime import datetime

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings, TEMPLATES_DIR, STATIC_DIR
from core.database import async_session
from repositories.stats_repo import StatsRepo
from repositories.order_repo import OrderRepo
from repositories.master_repo import MasterRepo
from models.order import OrderStatus, PROBLEM_LABELS

app = FastAPI(
    title="AutoHelp.uz Admin Panel",
    version="1.0.0",
    docs_url="/api/docs",
)

# Mount static files
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Templates
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def get_db() -> AsyncSession:
    """Dependency: get database session."""
    async with async_session() as session:
        yield session


# ── Dashboard ─────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_db)):
    """Main dashboard page."""
    stats_repo = StatsRepo(session)
    stats = await stats_repo.get_dashboard_stats()
    leaderboard = await stats_repo.get_master_leaderboard(limit=10)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "stats": stats,
            "leaderboard": leaderboard,
            "now": datetime.utcnow(),
        },
    )


# ── Orders API ────────────────────────────────────────────────────

@app.get("/api/orders")
async def api_orders(
    status: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
):
    """Get orders list as JSON."""
    order_repo = OrderRepo(session)

    if status == "active":
        orders = await order_repo.get_active_orders()
    elif status == "new":
        orders = await order_repo.get_new_orders()
    else:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from models.order import Order

        query = select(Order).options(
            selectinload(Order.user),
            selectinload(Order.master),
        ).order_by(Order.created_at.desc()).limit(limit)

        if status:
            try:
                query = query.where(Order.status == OrderStatus(status))
            except ValueError:
                pass

        result = await session.scalars(query)
        orders = list(result.all())

    return [
        {
            "id": o.id,
            "order_uid": o.order_uid,
            "client": o.user.full_name if o.user else "—",
            "phone": o.user.phone if o.user else "—",
            "problem": PROBLEM_LABELS[o.problem_type]["uz"],
            "status": o.status.value,
            "master": o.master.full_name if o.master else "—",
            "amount": o.payment_amount,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "completed_at": o.completed_at.isoformat() if o.completed_at else None,
        }
        for o in orders
    ]


# ── Masters API ───────────────────────────────────────────────────

@app.get("/api/masters")
async def api_masters(session: AsyncSession = Depends(get_db)):
    """Get all masters as JSON."""
    master_repo = MasterRepo(session)
    masters = await master_repo.get_all_active()

    return [
        {
            "id": m.id,
            "name": m.full_name,
            "phone": m.phone,
            "status": m.status.value,
            "rating": m.rating,
            "completed_orders": m.completed_orders,
            "rejected_orders": m.rejected_orders,
        }
        for m in masters
    ]


# ── Stats API ─────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats(session: AsyncSession = Depends(get_db)):
    """Get dashboard stats as JSON (for HTMX polling)."""
    stats_repo = StatsRepo(session)
    return await stats_repo.get_dashboard_stats()
