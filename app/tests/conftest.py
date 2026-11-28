"""Shared fixtures.

Two kinds of tests:
  * unit tests: the database is stubbed, so they run anywhere;
  * `@pytest.mark.db` tests: a real Postgres, in a separate `booking_test`
    database that is created on demand and reset before every test. They are
    skipped when Postgres is unreachable, unless REQUIRE_DB=1 (as `make test`
    sets), so a broken DB setup can never pass silently.
"""

from __future__ import annotations

import os

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import admin, cache, db, faults, main, metrics
from app.admission import Limiter

ADMIN_TOKEN = "test-admin-token"
AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _reset_faults() -> None:
    """Switch every fault off, even if its task belonged to an event loop that is gone."""
    try:
        faults.stop_all()
    except RuntimeError:  # leak task from a closed loop: just forget it
        faults._leak_task = None
        faults._leaked.clear()
        faults._cpu_off()
        faults._slow_db = False


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """Every test starts with all faults off, cache off, a fresh 5-slot limiter and a known token."""
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    # A fresh limiter per test: its asyncio.Condition binds to the first event loop that waits on it.
    limiter = Limiter(5)
    monkeypatch.setattr(main, "search_limiter", limiter)
    monkeypatch.setattr(admin, "search_limiter", limiter)
    metrics.track_search_limiter(limiter)
    cache.disable()
    _reset_faults()
    yield limiter
    cache.disable()
    _reset_faults()


@pytest.fixture
def fake_db(monkeypatch):
    """Stub every db call the endpoints make; tests tweak `fake_db.*` as needed."""

    class FakeDB:
        healthy = True
        trains = [
            {"id": 1, "number": "T101", "origin": "Delhi", "destination": "Mumbai", "seats_available": 200},
            {"id": 2, "number": "T201", "origin": "Mumbai", "destination": "Goa", "seats_available": 150},
        ]
        search_calls = 0
        book_error: type[Exception] | None = None

    fake = FakeDB()

    async def connect(*_a, **_k):
        return None

    async def ping(*_a, **_k):
        return fake.healthy

    async def search_trains(origin, destination):
        fake.search_calls += 1
        return [t for t in fake.trains
                if (origin is None or t["origin"].lower() == origin.lower())
                and (destination is None or t["destination"].lower() == destination.lower())]

    async def snapshot_trains():
        return list(fake.trains)

    async def book(train_id, passenger, seats):
        if fake.book_error:
            raise fake.book_error()
        return {"booking_id": 1, "payment_id": 1, "train_id": train_id,
                "passenger": passenger, "seats": seats, "amount_cents": 1000 * seats}

    monkeypatch.setattr(db, "connect", connect)
    monkeypatch.setattr(db, "disconnect", connect)
    monkeypatch.setattr(db, "ping", ping)
    monkeypatch.setattr(db, "search_trains", search_trains)
    monkeypatch.setattr(db, "snapshot_trains", snapshot_trains)
    monkeypatch.setattr(db, "book", book)
    return fake


@pytest.fixture
def client(fake_db):
    """App client with a stubbed DB. `with` keeps one event loop for the whole test,
    so background tasks (memory_leak) survive between requests."""
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


# --- real Postgres -------------------------------------------------------------

TEST_DB = os.getenv("TEST_POSTGRES_DB", "booking_test")


async def _ensure_test_database() -> None:
    s = db.settings()
    conn = await asyncpg.connect(host=s["host"], port=s["port"], user=s["user"],
                                 password=s["password"], database="postgres", timeout=3)
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB):
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()


@pytest.fixture
async def database(monkeypatch):
    """Real pools on the `booking_test` database, with seats and bookings reset."""
    monkeypatch.setenv("POSTGRES_DB", TEST_DB)
    try:
        await _ensure_test_database()
        await db.connect(retries=1)
    except (OSError, asyncpg.PostgresError) as exc:
        if os.getenv("REQUIRE_DB") == "1":
            raise
        pytest.skip(f"Postgres not reachable ({exc}); run `make test`")
    async with db.critical_pool().acquire() as conn:
        await conn.execute("TRUNCATE payments, bookings RESTART IDENTITY")
        await conn.execute("UPDATE trains SET seats_available = seats_total")
    yield db
    await db.disconnect()
