"""Database access: connection settings, the two pools, schema setup and queries.

Two separate pools keep slow searches from starving bookings:
  * search   – max 5 connections, used only by /search
  * critical – max 10 connections, used by /book and /health
A search never borrows a critical connection, so when the slow_db fault
(commit 9) saturates the search pool, /book stays fast.
"""

import asyncio
import logging
import os
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_LOCK_ID = 4242  # stops two pods applying the schema at the same time

SEARCH_POOL_MAX = 5
CRITICAL_POOL_MAX = 10

_pools: dict[str, asyncpg.Pool] = {}


class TrainNotFound(Exception):
    pass


class SoldOut(Exception):
    pass


def settings() -> dict:
    """Connection settings from the environment (names match .env.example)."""
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DB", "booking"),
        "user": os.getenv("POSTGRES_USER", "booking"),
        "password": os.getenv("POSTGRES_PASSWORD"),
    }


def _pool(name: str) -> asyncpg.Pool:
    try:
        return _pools[name]
    except KeyError:
        raise RuntimeError(f"{name} pool is not initialised") from None


def search_pool() -> asyncpg.Pool:
    return _pool("search")


def critical_pool() -> asyncpg.Pool:
    return _pool("critical")


async def _create_pool(max_size: int) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        **settings(), min_size=1, max_size=max_size, command_timeout=10
    )


async def connect(retries: int = 30, delay: float = 1.0) -> None:
    """Create both pools, waiting for Postgres to come up, then apply the schema."""
    for attempt in range(1, retries + 1):
        try:
            _pools["critical"] = await _create_pool(CRITICAL_POOL_MAX)
            break
        except (OSError, asyncpg.PostgresError) as exc:
            if attempt == retries:
                raise
            log.warning("database not ready (%s), retry %d/%d", exc, attempt, retries)
            await asyncio.sleep(delay)
    _pools["search"] = await _create_pool(SEARCH_POOL_MAX)

    async with critical_pool().acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", SCHEMA_LOCK_ID)
        await conn.execute(SCHEMA_PATH.read_text())
    log.info("database connected and schema applied")


async def disconnect() -> None:
    for pool in _pools.values():
        await pool.close()
    _pools.clear()


async def ping(timeout: float = 2.0) -> bool:
    """True if the critical pool can serve SELECT 1 (used by /health)."""
    try:
        async with critical_pool().acquire(timeout=timeout) as conn:
            return await conn.fetchval("SELECT 1", timeout=timeout) == 1
    except Exception as exc:  # any failure means unhealthy
        log.warning("database ping failed: %s", exc)
        return False


# --- Queries -----------------------------------------------------------------

SEARCH_SQL = """
    SELECT id, number, name, origin, destination, departs_at, arrives_at,
           seats_available, fare_cents
    FROM trains
    WHERE seats_available > 0
      AND ($1::text IS NULL OR origin ILIKE $1)
      AND ($2::text IS NULL OR destination ILIKE $2)
    ORDER BY departs_at, number
"""


async def search_trains(origin: str | None, destination: str | None) -> list[dict]:
    """Trains with seats left, optionally filtered by route. Search pool only."""
    async with search_pool().acquire() as conn:
        rows = await conn.fetch(SEARCH_SQL, origin, destination)
    return [dict(row) for row in rows]


async def book(train_id: int, passenger: str, seats: int) -> dict:
    """Reserve seats, create the booking and record its payment in ONE transaction.

    The conditional UPDATE is the concurrency guard: two parallel bookings of
    the last seat both try it, Postgres serialises them on the row lock, and
    the second sees seats_available = 0, matches no row and gets SoldOut.
    """
    async with critical_pool().acquire() as conn, conn.transaction():
        fare = await conn.fetchval(
            """UPDATE trains SET seats_available = seats_available - $2
               WHERE id = $1 AND seats_available >= $2
               RETURNING fare_cents""",
            train_id, seats,
        )
        if fare is None:
            exists = await conn.fetchval("SELECT 1 FROM trains WHERE id = $1", train_id)
            raise SoldOut() if exists else TrainNotFound()

        booking_id = await conn.fetchval(
            "INSERT INTO bookings (train_id, passenger, seats) VALUES ($1, $2, $3) RETURNING id",
            train_id, passenger, seats,
        )
        amount = fare * seats
        payment_id = await conn.fetchval(
            "INSERT INTO payments (booking_id, amount_cents) VALUES ($1, $2) RETURNING id",
            booking_id, amount,
        )
    return {
        "booking_id": booking_id,
        "payment_id": payment_id,
        "train_id": train_id,
        "passenger": passenger,
        "seats": seats,
        "amount_cents": amount,
    }
