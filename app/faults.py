"""Fault switches the guardian must later detect (commit 9). All off by default.

  cpu_hog      a child process spinning one core. A child process, not a thread:
               a thread would fight the event loop for the GIL and raise latency
               too, blurring it with other faults. Container CPU goes to ~1 core
               at normal request rate and the HPA starts scaling.
  memory_leak  a background task appending a 2 MB bytearray to a module-level
               list every 5 s (~400 KB/s): container memory climbs in a line.
  slow_db      every search first runs SELECT pg_sleep(0.5) on its search-pool
               connection: search p95 up sharply, CPU low, search pool
               saturated, /book unaffected (it uses the critical pool).

Faults are per process. With one uvicorn worker per pod that means per pod.
Toggled through the token-protected /admin endpoints in app/admin.py.
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import signal

log = logging.getLogger("booking.faults")

NAMES = ("cpu_hog", "memory_leak", "slow_db")

LEAK_CHUNK_BYTES = 2 * 1024 * 1024
LEAK_INTERVAL_S = 5.0
SLOW_DB_SLEEP_S = 0.5

# spawn, not fork: a forked child would inherit uvicorn's signal handlers and
# could ignore terminate(). A spawned child starts clean.
_mp = multiprocessing.get_context("spawn")

_cpu_proc: multiprocessing.process.BaseProcess | None = None
_leak_task: asyncio.Task | None = None
_leaked: list[bytearray] = []
_slow_db = False


# --- cpu_hog -----------------------------------------------------------------

def _spin(parent_pid: int) -> None:
    """Child process: burn one core until terminated or the parent is gone."""
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    n = 0
    while True:
        n += 1
        if n % 5_000_000 == 0 and os.getppid() != parent_pid:
            return  # parent died: never leave an orphan spinning


def _cpu_on() -> None:
    global _cpu_proc
    if _cpu_proc is None or not _cpu_proc.is_alive():
        _cpu_proc = _mp.Process(target=_spin, args=(os.getpid(),), name="cpu_hog", daemon=True)
        _cpu_proc.start()


def _cpu_off() -> None:
    global _cpu_proc
    if _cpu_proc is not None:
        _cpu_proc.terminate()
        _cpu_proc.join(timeout=2)
        if _cpu_proc.is_alive():
            _cpu_proc.kill()
            _cpu_proc.join(timeout=2)
        _cpu_proc = None


# --- memory_leak -------------------------------------------------------------

async def _leak() -> None:
    while True:
        # Filled with a non-zero byte so every page is really written (resident),
        # not just reserved.
        _leaked.append(bytearray(b"\x01") * LEAK_CHUNK_BYTES)
        await asyncio.sleep(LEAK_INTERVAL_S)


def _leak_on() -> None:
    global _leak_task
    if _leak_task is None or _leak_task.done():
        _leak_task = asyncio.get_running_loop().create_task(_leak(), name="memory_leak")


def _leak_off() -> None:
    global _leak_task
    if _leak_task is not None:
        _leak_task.cancel()
        _leak_task = None
    _leaked.clear()  # 2 MB chunks are mmap-backed, so this returns memory to the OS


# --- slow_db -----------------------------------------------------------------

def slow_db_delay() -> float:
    """Seconds of pg_sleep to add to each search (0 when the fault is off)."""
    return SLOW_DB_SLEEP_S if _slow_db else 0.0


# --- public API --------------------------------------------------------------

def state() -> dict[str, bool]:
    return {
        "cpu_hog": _cpu_proc is not None and _cpu_proc.is_alive(),
        "memory_leak": _leak_task is not None and not _leak_task.done(),
        "slow_db": _slow_db,
    }


def set_fault(name: str, enabled: bool) -> dict[str, bool]:
    """Turn one fault on or off (idempotent). Must run inside the event loop."""
    global _slow_db
    if name not in NAMES:
        raise KeyError(name)
    if name == "cpu_hog":
        _cpu_on() if enabled else _cpu_off()
    elif name == "memory_leak":
        _leak_on() if enabled else _leak_off()
    else:
        _slow_db = enabled
    log.warning("fault %s %s", name, "ON" if enabled else "OFF",
                extra={"event": "fault", "fault": name, "enabled": enabled})
    return state()


def stop_all() -> None:
    """Switch every fault off (app shutdown, and demo reset later)."""
    global _slow_db
    _cpu_off()
    _leak_off()
    _slow_db = False
