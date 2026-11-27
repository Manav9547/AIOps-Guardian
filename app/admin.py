"""Token-protected admin endpoints (commit 9; cache mode and search slots in commit 10).

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
from pydantic import BaseModel

from app import faults


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
