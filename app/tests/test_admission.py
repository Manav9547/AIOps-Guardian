"""The resizable bounded queue in front of /search."""

import anyio
import pytest

from app.admission import Limiter, QueueFull

pytestmark = pytest.mark.anyio


async def test_acquire_up_to_slots_then_queue_full():
    lim = Limiter(2)
    await lim.acquire(0.05)
    await lim.acquire(0.05)
    assert lim.used == 2
    with pytest.raises(QueueFull):
        await lim.acquire(0.05)
    assert lim.used == 2
    assert lim.waiting == 0


async def test_waiter_gets_slot_when_one_is_released():
    lim = Limiter(1)
    await lim.acquire()
    got_it = anyio.Event()

    async def waiter():
        await lim.acquire(1.0)
        got_it.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(waiter)
        await anyio.sleep(0.05)
        assert lim.waiting == 1 and not got_it.is_set()
        await lim.release()
        with anyio.fail_after(1):
            await got_it.wait()
    assert lim.used == 1
    assert lim.waiting == 0


async def test_wait_is_bounded_by_timeout():
    lim = Limiter(1)
    await lim.acquire()
    start = anyio.current_time()
    with pytest.raises(QueueFull):
        await lim.acquire(0.2)
    assert 0.15 <= anyio.current_time() - start < 1.0


async def test_growing_the_queue_wakes_waiters():
    lim = Limiter(1)
    await lim.acquire()
    done = []

    async def waiter():
        await lim.acquire(1.0)
        done.append(True)

    async with anyio.create_task_group() as tg:
        tg.start_soon(waiter)
        tg.start_soon(waiter)
        await anyio.sleep(0.05)
        await lim.resize(3)
    assert len(done) == 2
    assert lim.used == 3


async def test_shrinking_does_not_evict_but_blocks_new_requests():
    lim = Limiter(3)
    for _ in range(3):
        await lim.acquire()
    await lim.resize(1)
    assert lim.used == 3          # holders keep their slots
    await lim.release()
    await lim.release()           # used 1 == slots 1
    with pytest.raises(QueueFull):
        await lim.acquire(0.05)
    await lim.release()
    await lim.acquire(0.05)       # free again once below the new size


async def test_slot_context_manager_releases_on_error():
    lim = Limiter(1)
    with pytest.raises(ValueError):
        async with lim.slot(0.05):
            assert lim.used == 1
            raise ValueError("boom")
    assert lim.used == 0


@pytest.mark.parametrize("bad", [0, -3])
async def test_invalid_sizes_rejected(bad):
    with pytest.raises(ValueError):
        Limiter(bad)
    with pytest.raises(ValueError):
        await Limiter(1).resize(bad)
