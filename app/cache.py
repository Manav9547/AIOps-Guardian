"""Cache mode for /search (commit 10): serve searches from memory, skip the DB.

This is the guardian's remedy for a slow dependency: when the database is slow
(slow_db fault), switching cache mode on makes /search answer from an
in-memory snapshot of the trains table, so it neither waits for a search slot
nor holds a search-pool connection.

The snapshot is taken once, when cache mode is switched on, through the
critical pool (one short query, unaffected by slow_db). Seat counts in cached
results can therefore be stale; /book always checks the real count, so a
stale result can at worst lead to a 409.
"""

from __future__ import annotations

import time

from app import db

_enabled = False
_trains: list[dict] = []
_loaded_at: float | None = None


def enabled() -> bool:
    return _enabled


async def enable() -> None:
    """Take a fresh snapshot, then switch cache mode on (re-enabling refreshes it)."""
    global _enabled, _trains, _loaded_at
    _trains = await db.snapshot_trains()
    _loaded_at = time.time()
    _enabled = True


def disable() -> None:
    global _enabled, _trains, _loaded_at
    _enabled = False
    _trains = []
    _loaded_at = None


def search(origin: str | None, destination: str | None) -> list[dict]:
    """Same filter as db.SEARCH_SQL (case-insensitive route match), from memory."""
    o = origin.lower() if origin else None
    d = destination.lower() if destination else None
    return [
        t for t in _trains
        if (o is None or t["origin"].lower() == o)
        and (d is None or t["destination"].lower() == d)
    ]


def state() -> dict:
    return {
        "enabled": _enabled,
        "trains": len(_trains),
        "age_s": round(time.time() - _loaded_at, 1) if _loaded_at else None,
    }
