"""Prometheus metrics for the booking API (commit 7).

Wired into the app in app/main.py:

    metrics.instrument(app)
    metrics.track_search_limiter(search_limiter)

Metric names are the ones the guardian queries (see "Guardian reference" in the
implementation guide). Prometheus adds the `namespace` label itself from pod
discovery, so it is not set here.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Own registry: only app metrics, and tests can import this module repeatedly.
REGISTRY = CollectorRegistry(auto_describe=True)

# Probe, scrape and chaos-panel polling traffic would inflate the request rate
# the guardian reads. (Admin actions such as POST /admin/fault/* still count.)
EXCLUDED_PATHS = frozenset({"/metrics", "/health", "/admin/state", "/chaos"})

REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests by endpoint and status code",
    ["method", "endpoint", "status"],
    registry=REGISTRY,
)

LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    # Fine below 1 s for normal traffic; 2-5 s catches the queue timeout and slow_db.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0),
    registry=REGISTRY,
)

SEARCH_QUEUE_DEPTH = Gauge(
    "search_queue_depth",
    "Requests waiting for a /search slot",
    registry=REGISTRY,
)

SEARCH_SLOTS_IN_USE = Gauge(
    "search_slots_in_use",
    "/search slots currently held",
    registry=REGISTRY,
)

SEARCH_SLOTS_TOTAL = Gauge(
    "search_slots_total",
    "Configured /search slots (resized via PUT /admin/search-slots)",
    registry=REGISTRY,
)


def track_search_limiter(limiter) -> None:
    """Read the /search queue gauges straight from the Limiter at scrape time."""
    SEARCH_QUEUE_DEPTH.set_function(lambda: limiter.waiting)
    SEARCH_SLOTS_IN_USE.set_function(lambda: limiter.used)
    SEARCH_SLOTS_TOTAL.set_function(lambda: limiter.slots)


def endpoint_label(request: Request) -> str:
    """Route template (e.g. /book/{train_id}), never the raw path, to bound label cardinality."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if path else "unmatched"


def observe(method: str, endpoint: str, status: int, seconds: float) -> None:
    REQUESTS.labels(method, endpoint, str(status)).inc()
    LATENCY.labels(method, endpoint).observe(seconds)


def instrument(app: FastAPI) -> None:
    """Add the timing middleware and the /metrics endpoint."""

    @app.middleware("http")
    async def _prometheus_middleware(request: Request, call_next):
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)
        start = time.perf_counter()
        status = 500  # an unhandled exception still counts as a 5xx
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            observe(request.method, endpoint_label(request), status, time.perf_counter() - start)

    @app.get("/metrics", include_in_schema=False)
    def _metrics() -> Response:
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
