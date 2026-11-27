"""Token-protected admin endpoints.

  commit 9   GET  /admin/faults, POST /admin/fault/{name}
  commit 10  GET  /admin/state, PUT /admin/cache-mode, PUT /admin/search-slots

Every /admin call needs the header  Authorization: Bearer <ADMIN_TOKEN>.
Without it, or with a wrong token, the answer is 401. If ADMIN_TOKEN is not set
at all, every admin call is refused, so a misconfigured pod is never open.

    curl -X POST localhost:8000/admin/fault/slow_db \
         -H "Authorization: Bearer $ADMIN_TOKEN" \
         -H 'content-type: application/json' -d '{"enabled": true}'
"""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app import cache, faults
from app.admission import search_limiter

MAX_SEARCH_SLOTS = 100


def _admin_token() -> str:
    # Read per request: tests can set it, and commit 24 adds the Vault file here.
    return os.getenv("ADMIN_TOKEN", "")


def require_admin(authorization: str | None = Header(default=None)) -> None:
    expected = _admin_token()
    scheme, _, given = (authorization or "").partition(" ")
    if not expected or scheme.lower() != "bearer" or not secrets.compare_digest(given, expected):
        raise HTTPException(
            status_code=401,
            detail="admin token required",
            headers={"WWW-Authenticate": "Bearer"},
        )


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class FaultUpdate(BaseModel):
    enabled: bool


class CacheUpdate(BaseModel):
    enabled: bool


class SlotsUpdate(BaseModel):
    slots: int = Field(ge=1, le=MAX_SEARCH_SLOTS)


def _search_state() -> dict:
    return {
        "cache": cache.state(),
        "slots": search_limiter.slots,
        "in_use": search_limiter.used,
        "waiting": search_limiter.waiting,
    }


@router.get("/state")
async def get_state() -> dict:
    """Everything the chaos panel and the guardian need in one call."""
    return {"faults": faults.state(), "search": _search_state()}


@router.put("/cache-mode")
async def set_cache_mode(update: CacheUpdate) -> dict:
    """Cache mode on: /search answers from an in-memory snapshot and skips the DB."""
    if update.enabled:
        await cache.enable()
    else:
        cache.disable()
    return {"search": _search_state()}


@router.put("/search-slots")
async def set_search_slots(update: SlotsUpdate) -> dict:
    """Resize the /search queue live. Requests already holding a slot finish normally."""
    await search_limiter.resize(update.slots)
    return {"search": _search_state()}


@router.get("/faults")
async def get_faults() -> dict:
    """Current state of every fault switch (the chaos panel reads this)."""
    return {"faults": faults.state()}


@router.post("/fault/{name}")
async def set_fault(name: str, update: FaultUpdate | None = None) -> dict:
    """Set a fault with {"enabled": true|false}; with no body, toggle it."""
    if name not in faults.NAMES:
        raise HTTPException(status_code=404, detail=f"unknown fault, use one of {list(faults.NAMES)}")
    enabled = (not faults.state()[name]) if update is None else update.enabled
    return {"faults": faults.set_fault(name, enabled)}
