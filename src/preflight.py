import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any

from aiogram import Bot
from redis.asyncio import Redis
from sqlalchemy import select

from src.core.config import get_settings
from src.db.session import engine

PLACEHOLDER_BOT_TOKENS = {"replace_me", "", None}
PLACEHOLDER_DISPATCHER_IDS = {None, -1000000000000}


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _redact_database_dsn(dsn: str) -> str:
    if "@" not in dsn:
        return dsn

    scheme, sep, rest = dsn.partition("://")
    if not sep or "@" not in rest:
        return dsn

    _, _, host_part = rest.partition("@")
    return f"{scheme}://***@{host_part}"


async def check_bot_token(settings) -> CheckResult:
    token = settings.bot_token
    if token in PLACEHOLDER_BOT_TOKENS:
        return CheckResult(
            name="bot_token",
            ok=False,
            detail="BOT_TOKEN not configured (replace_me or empty)",
            required=True,
        )

    bot = Bot(token=token)
    try:
        me = await bot.get_me()
        return CheckResult(
            name="telegram_auth",
            ok=True,
            detail=f"Bot authorized as @{me.username or me.first_name}",
            required=True,
        )
    except Exception as exc:  # pragma: no cover
        return CheckResult(
            name="telegram_auth",
            ok=False,
            detail=f"Bot token validation failed: {exc}",
            required=True,
        )
    finally:
        await bot.session.close()


async def check_db(settings) -> CheckResult:
    try:
        async with engine.begin() as conn:
            await conn.execute(select(1))
        return CheckResult(name="database", ok=True, detail="Database connection successful")
    except Exception as exc:  # pragma: no cover
        target = _redact_database_dsn(settings.resolved_database_dsn)
        return CheckResult(
            name="database",
            ok=False,
            detail=f"Database connection failed ({target}): {exc}",
            required=True,
        )


async def check_redis(settings) -> CheckResult:
    if not settings.use_redis:
        return CheckResult(
            name="redis",
            ok=True,
            detail="Redis disabled by configuration (USE_REDIS=false)",
            required=False,
        )

    redis = Redis.from_url(settings.redis_dsn)
    try:
        await redis.ping()
        return CheckResult(name="redis", ok=True, detail="Redis ping successful")
    except Exception as exc:  # pragma: no cover
        return CheckResult(
            name="redis",
            ok=False,
            detail=f"Redis connection failed ({settings.redis_host}:{settings.redis_port}): {exc}",
            required=True,
        )
    finally:
        await redis.aclose()


def check_dispatcher_config(settings) -> CheckResult:
    if settings.dispatcher_chat_id in PLACEHOLDER_DISPATCHER_IDS:
        return CheckResult(
            name="dispatcher_chat_id",
            ok=False,
            detail="DISPATCHER_CHAT_ID is missing or placeholder",
            required=True,
        )
    return CheckResult(
        name="dispatcher_chat_id",
        ok=True,
        detail=f"Dispatcher chat id configured ({settings.dispatcher_chat_id})",
        required=True,
    )


def check_runtime_tuning(settings) -> CheckResult:
    if settings.dependency_wait_attempts < 5:
        return CheckResult(
            name="startup_retry",
            ok=False,
            detail="DEPENDENCY_WAIT_ATTEMPTS should be at least 5 for resilient startup",
            required=False,
        )
    if settings.dependency_wait_delay_seconds <= 0:
        return CheckResult(
            name="startup_retry",
            ok=False,
            detail="DEPENDENCY_WAIT_DELAY_SECONDS must be > 0",
            required=False,
        )
    return CheckResult(
        name="startup_retry",
        ok=True,
        detail=(
            f"Retry config: attempts={settings.dependency_wait_attempts}, "
            f"delay={settings.dependency_wait_delay_seconds}s"
        ),
        required=False,
    )


def summarize(results: list[CheckResult]) -> dict[str, Any]:
    required_failures = [r for r in results if r.required and not r.ok]
    warnings = [r for r in results if not r.required and not r.ok]
    return {
        "ok": len(required_failures) == 0,
        "required_failures": [asdict(r) for r in required_failures],
        "warnings": [asdict(r) for r in warnings],
        "checks": [asdict(r) for r in results],
    }


async def main() -> int:
    settings = get_settings()

    results: list[CheckResult] = []
    results.append(check_dispatcher_config(settings))
    results.append(check_runtime_tuning(settings))
    results.append(await check_bot_token(settings))
    results.append(await check_db(settings))
    results.append(await check_redis(settings))

    payload = summarize(results)
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
