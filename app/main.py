"""Booking API entry point.

Run locally from the repo root:
    uvicorn app.main:app --env-file .env --port 8000
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import admin, cache, db, faults, metrics
from app import logging as applog
from app.admission import SEARCH_QUEUE_TIMEOUT, QueueFull, search_limiter

APP_VERSION = os.getenv("APP_VERSION", "dev")

# JSON lines on stdout for Filebeat; runs after uvicorn's own logging setup.
applog.setup()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.connect()
    yield
    faults.stop_all()  # never leave a cpu_hog child spinning after shutdown
    await db.disconnect()


app = FastAPI(title="Booking API", version=APP_VERSION, lifespan=lifespan)
app.include_router(admin.router)
metrics.instrument(app)
metrics.track_search_limiter(search_limiter)
# Added last so it is the outermost middleware: the request id exists for everything inside.
applog.instrument(app)


class BookingRequest(BaseModel):
    train_id: int = Field(gt=0)
    passenger: str = Field(min_length=1, max_length=100)
    seats: int = Field(default=1, ge=1, le=6)


@app.get("/")
async def root() -> dict:
    return {"service": "booking-api", "version": APP_VERSION}


@app.get("/health")
async def health():
    """Readiness check: 200 only if the database answers on the critical pool."""
    if await db.ping():
        return {"status": "ok", "db": "ok"}
    return JSONResponse(status_code=503, content={"status": "error", "db": "unreachable"})


@app.get("/search")
async def search(origin: str | None = None, destination: str | None = None):
    """Trains with seats left. Waits up to SEARCH_QUEUE_TIMEOUT for a slot, else 429.

    In cache mode (PUT /admin/cache-mode) it answers from memory: no slot, no DB.
    """
    if cache.enabled():
        return {"trains": cache.search(origin, destination), "cached": True}
    try:
        async with search_limiter.slot(SEARCH_QUEUE_TIMEOUT):
            trains = await db.search_trains(origin, destination)
    except QueueFull:
        return JSONResponse(
            status_code=429,
            content={"detail": "search is busy, try again shortly"},
            headers={"Retry-After": "1"},
        )
    return {"trains": trains, "cached": False}


@app.post("/book", status_code=201)
async def book(req: BookingRequest):
    """Reserve seats and take payment in one transaction: 404 unknown train, 409 sold out."""
    try:
        return await db.book(req.train_id, req.passenger, req.seats)
    except db.TrainNotFound:
        raise HTTPException(status_code=404, detail="train not found") from None
    except db.SoldOut:
        raise HTTPException(status_code=409, detail="not enough seats left") from None
