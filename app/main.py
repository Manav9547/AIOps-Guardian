"""Booking API entry point.

Run locally from the repo root:
    uvicorn app.main:app --env-file .env --port 8000
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import db

APP_VERSION = os.getenv("APP_VERSION", "dev")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title="Booking API", version=APP_VERSION, lifespan=lifespan)


@app.get("/")
async def root() -> dict:
    return {"service": "booking-api", "version": APP_VERSION}


@app.get("/health")
async def health():
    """Readiness check: 200 only if the database answers."""
    if await db.ping():
        return {"status": "ok", "db": "ok"}
    return JSONResponse(status_code=503, content={"status": "error", "db": "unreachable"})
