"""Database access: connection settings, pool lifecycle and schema setup.

Commit 4 splits the single pool below into a `search` pool and a `critical`
pool, so keep all pool access going through this module.
"""

import asyncio
import logging
import os
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_LOCK_ID = 4242  # stops two pods applying the schema at the same time

_pool: asyncpg.Pool | None = None


def settings() -> dict:
    """Connection settings from the environment (names agreed with .env.example)."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DB", "booking"),
        "user": os.getenv("POSTGRES_USER", "booking"),
        "password": os.getenv("POSTGRES_PASSWORD"),
    }


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database pool is not initialised")
    return _pool


async def connect(retries: int = 30, delay: float = 1.0) -> None:
    """Create the pool, waiting for Postgres to come up, then apply the schema."""
    global _pool
    for attempt in range(1, retries + 1):
        try:
            _pool = await asyncpg.create_pool(
                **settings(), min_size=1, max_size=10, command_timeout=10
            )
            break
        except (OSError, asyncpg.PostgresError) as exc:
            if attempt == retries:
                raise
            log.warning("database not ready (%s), retry %d/%d", exc, attempt, retries)
            await asyncio.sleep(delay)

    async with _pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", SCHEMA_LOCK_ID)
        await conn.execute(SCHEMA_PATH.read_text())
    log.info("database connected and schema applied")


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def ping(timeout: float = 2.0) -> bool:
    """True if a connection can be taken from the pool and answers SELECT 1."""
    try:
        async with pool().acquire(timeout=timeout) as conn:
            return await conn.fetchval("SELECT 1", timeout=timeout) == 1
    except Exception as exc:  # any failure means unhealthy
        log.warning("database ping failed: %s", exc)
        return False
