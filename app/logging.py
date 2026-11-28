"""Structured JSON logging with a request id (commit 8).

Wired into the app in app/main.py:

    applog.setup()
    applog.instrument(app)

Every request writes one JSON line to stdout (Filebeat ships it to Logstash):

    {"time": "...", "level": "INFO", "component": "booking-api",
     "event": "request", "method": "GET", "endpoint": "/search",
     "path": "/search", "status": 200, "latency_ms": 12.4,
     "request_id": "..."}

Note: this module is named like the stdlib module, as in the guide's layout.
That is fine while the app runs as the package `app` (uvicorn app.main:app
from the repo root, or WORKDIR above app/ in the Dockerfile). Running
`uvicorn main:app` from inside app/ would shadow the stdlib `logging`.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, Request

REQUEST_ID_HEADER = "X-Request-ID"
COMPONENT = "booking-api"

# Probes and the chaos panel's polling every few seconds would drown the real
# traffic in Kibana. Errors on these paths are still logged.
QUIET_PATHS = frozenset({"/metrics", "/health", "/admin/state", "/chaos"})

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

log = logging.getLogger("booking")

# Standard LogRecord attributes, plus uvicorn's ANSI-coloured duplicate of the message.
_STD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {
    "message", "asctime", "color_message",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Extra fields passed via `extra=` become top-level keys."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds")
        entry = {
            "time": ts.replace("+00:00", "Z"),
            "level": record.levelname,
            "component": COMPONENT,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in vars(record).items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup(level: int = logging.INFO) -> None:
    """Send every logger (including uvicorn's) through the JSON formatter on stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Our middleware logs each request, so uvicorn's access log would be a duplicate.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True


def _endpoint(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


def instrument(app: FastAPI) -> None:
    """Assign a request id (reuse the caller's X-Request-ID if sent) and log each request."""

    @app.middleware("http")
    async def _logging_middleware(request: Request, call_next):
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = rid
            return response
        except Exception:
            log.exception("unhandled error", extra={"event": "error", "path": request.url.path})
            raise
        finally:
            if request.url.path not in QUIET_PATHS or status >= 400:
                log.info(
                    "request",
                    extra={
                        "event": "request",
                        "method": request.method,
                        "endpoint": _endpoint(request),
                        "path": request.url.path,
                        "status": status,
                        "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                    },
                )
            request_id_var.reset(token)
