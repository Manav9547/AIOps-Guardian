"""Admission control for /search: a resizable bounded queue.

asyncio.Semaphore cannot change size at runtime, so this small limiter is
used instead. A request waits up to `timeout` seconds for a slot; if none
frees up it gets QueueFull and the endpoint returns 429. Slot count can be
changed live (PUT /admin/search-slots, commit 10; the guardian shrinks it
under overload).

The queue is per pod: total search capacity is slots x pods. Run one uvicorn
worker per pod so the limiter, metrics and faults all live in one process.
"""

import asyncio
import os
from contextlib import asynccontextmanager


class QueueFull(Exception):
    """No search slot became free within the timeout."""


class Limiter:
    def __init__(self, slots: int):
        if slots < 1:
            raise ValueError("slots must be at least 1")
        self.slots = slots
        self.used = 0
        self.waiting = 0  # requests queued for a slot; exported as a gauge in commit 7
        self.cond = asyncio.Condition()

    async def acquire(self, timeout: float = 2.0) -> None:
        async with self.cond:
            self.waiting += 1
            try:
                await asyncio.wait_for(
                    self.cond.wait_for(lambda: self.used < self.slots), timeout
                )
            except TimeoutError:
                raise QueueFull() from None
            finally:
                self.waiting -= 1
            self.used += 1

    async def release(self) -> None:
        async with self.cond:
            self.used -= 1
            self.cond.notify_all()

    async def resize(self, slots: int) -> None:
        if slots < 1:
            raise ValueError("slots must be at least 1")
        async with self.cond:
            self.slots = slots
            self.cond.notify_all()

    @asynccontextmanager
    async def slot(self, timeout: float = 2.0):
        """`async with limiter.slot(): ...` holds one slot for the block."""
        await self.acquire(timeout)
        try:
            yield
        finally:
            await self.release()


# Default matches the search pool size (db.SEARCH_POOL_MAX), so requests queue
# here (and can get a clean 429) rather than inside the connection pool.
SEARCH_SLOTS = int(os.getenv("SEARCH_SLOTS", "5"))
SEARCH_QUEUE_TIMEOUT = float(os.getenv("SEARCH_QUEUE_TIMEOUT", "2.0"))

search_limiter = Limiter(SEARCH_SLOTS)
