"""Against a real Postgres (`booking_test` database): pools, booking transaction,
and the Checkpoint 1 property that slow_db slows /search but not /book."""

import time

import anyio
import httpx
import pytest

from app import cache, db, faults, main

pytestmark = [pytest.mark.anyio, pytest.mark.db]


def app_client() -> httpx.AsyncClient:
    # ASGITransport skips lifespan: the `database` fixture has already connected.
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test")


async def last_seat_train_id() -> int:
    async with db.critical_pool().acquire() as conn:
        return await conn.fetchval("SELECT id FROM trains WHERE number = 'T999'")


async def test_pool_sizes(database):
    assert db.search_pool().get_max_size() == db.SEARCH_POOL_MAX == 5
    assert db.critical_pool().get_max_size() == db.CRITICAL_POOL_MAX == 10
    assert db.search_pool() is not db.critical_pool()


async def test_schema_is_idempotent(database):
    await db.disconnect()
    await db.connect(retries=1)          # applies schema.sql a second time
    async with db.critical_pool().acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM trains WHERE number = 'T101'") == 1


async def test_health_and_search_against_real_db(database):
    async with app_client() as c:
        assert (await c.get("/health")).status_code == 200
        r = await c.get("/search", params={"origin": "delhi", "destination": "MUMBAI"})
    assert r.status_code == 200
    assert [t["number"] for t in r.json()["trains"]] == ["T101"]


async def test_booking_writes_booking_and_payment_in_one_go(database):
    async with app_client() as c:
        r = await c.post("/book", json={"train_id": 1, "passenger": "Asha", "seats": 2})
    assert r.status_code == 201
    body = r.json()
    async with db.critical_pool().acquire() as conn:
        seats = await conn.fetchval("SELECT seats_available FROM trains WHERE id = 1")
        paid = await conn.fetchval("SELECT amount_cents FROM payments WHERE booking_id = $1", body["booking_id"])
    assert seats == 198
    assert paid == body["amount_cents"] == 2 * 185000


async def test_unknown_train_is_404_and_writes_nothing(database):
    async with app_client() as c:
        r = await c.post("/book", json={"train_id": 99999, "passenger": "Asha"})
    assert r.status_code == 404
    async with db.critical_pool().acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM bookings") == 0


async def test_two_parallel_bookings_of_last_seat(database):
    train_id = await last_seat_train_id()
    statuses = []

    async def book(name):
        async with app_client() as c:
            r = await c.post("/book", json={"train_id": train_id, "passenger": name})
            statuses.append(r.status_code)

    async with anyio.create_task_group() as tg:
        tg.start_soon(book, "first")
        tg.start_soon(book, "second")

    assert sorted(statuses) == [201, 409]
    async with db.critical_pool().acquire() as conn:
        assert await conn.fetchval("SELECT seats_available FROM trains WHERE id = $1", train_id) == 0
        assert await conn.fetchval("SELECT count(*) FROM bookings WHERE train_id = $1", train_id) == 1
        assert await conn.fetchval("SELECT count(*) FROM payments") == 1


async def test_slow_db_slows_search_but_not_book(database):
    """Saturate the search pool with slow searches; /book and /health stay fast."""
    faults.set_fault("slow_db", True)
    search_times = []

    async def search():
        async with app_client() as c:
            t0 = time.perf_counter()
            r = await c.get("/search")
            search_times.append((r.status_code, time.perf_counter() - t0))

    async with anyio.create_task_group() as tg:
        for _ in range(db.SEARCH_POOL_MAX):
            tg.start_soon(search)
        await anyio.sleep(0.1)                              # every search connection now in pg_sleep
        assert db.search_pool().get_idle_size() == 0
        async with app_client() as c:
            t0 = time.perf_counter()
            booked = await c.post("/book", json={"train_id": 1, "passenger": "Asha"})
            book_s = time.perf_counter() - t0
            health = await c.get("/health")

    assert booked.status_code == 201
    assert health.status_code == 200
    assert book_s < 0.3, f"/book took {book_s:.2f}s while search was saturated"
    assert all(status == 200 and secs >= faults.SLOW_DB_SLEEP_S for status, secs in search_times)


async def test_cache_mode_answers_fast_while_db_is_slow(database):
    faults.set_fault("slow_db", True)
    await cache.enable()                                    # snapshot via the critical pool
    async with app_client() as c:
        t0 = time.perf_counter()
        r = await c.get("/search")
        secs = time.perf_counter() - t0
    assert r.status_code == 200 and r.json()["cached"] is True
    assert len(r.json()["trains"]) == 12
    assert secs < faults.SLOW_DB_SLEEP_S
