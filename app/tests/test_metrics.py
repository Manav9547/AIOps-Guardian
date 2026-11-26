from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import metrics


def make_client() -> TestClient:
    app = FastAPI()
    metrics.instrument(app)

    @app.get("/search")
    def search():
        return {"ok": True}

    @app.get("/book/{train_id}")
    def book(train_id: int):
        if train_id == 0:
            raise HTTPException(409, "sold out")
        return {"train": train_id}

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    @app.get("/health")
    def health():
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def sample(name: str, **labels) -> float:
    return metrics.REGISTRY.get_sample_value(name, labels) or 0.0


def test_counts_requests_per_endpoint_and_status():
    c = make_client()
    before_ok = sample("http_requests_total", method="GET", endpoint="/search", status="200")
    c.get("/search")
    c.get("/search")
    assert sample("http_requests_total", method="GET", endpoint="/search", status="200") == before_ok + 2


def test_uses_route_template_not_raw_path():
    c = make_client()
    before = sample("http_requests_total", method="GET", endpoint="/book/{train_id}", status="409")
    c.get("/book/0")
    assert sample("http_requests_total", method="GET", endpoint="/book/{train_id}", status="409") == before + 1
    assert sample("http_requests_total", method="GET", endpoint="/book/0", status="409") == 0


def test_unhandled_exception_counts_as_500():
    c = make_client()
    before = sample("http_requests_total", method="GET", endpoint="/boom", status="500")
    assert c.get("/boom").status_code == 500
    assert sample("http_requests_total", method="GET", endpoint="/boom", status="500") == before + 1


def test_latency_histogram_observed():
    c = make_client()
    before = sample("http_request_duration_seconds_count", method="GET", endpoint="/search")
    c.get("/search")
    assert sample("http_request_duration_seconds_count", method="GET", endpoint="/search") == before + 1


def test_health_and_metrics_not_counted():
    c = make_client()
    c.get("/health")
    c.get("/metrics")
    assert sample("http_requests_total", method="GET", endpoint="/health", status="200") == 0
    assert sample("http_requests_total", method="GET", endpoint="/metrics", status="200") == 0


def test_unknown_path_has_bounded_label():
    c = make_client()
    c.get("/no/such/path/123")
    assert sample("http_requests_total", method="GET", endpoint="unmatched", status="404") >= 1


def test_metrics_endpoint_exposes_all_series():
    c = make_client()
    c.get("/search")
    body = c.get("/metrics").text
    for name in ("http_requests_total", "http_request_duration_seconds_bucket",
                 "search_queue_depth", "search_slots_in_use", "search_slots_total"):
        assert name in body


def test_queue_gauges_follow_the_limiter():
    from app.admission import Limiter

    limiter = Limiter(4)
    limiter.used, limiter.waiting = 3, 2
    metrics.track_search_limiter(limiter)
    assert metrics.REGISTRY.get_sample_value("search_slots_total") == 4
    assert metrics.REGISTRY.get_sample_value("search_slots_in_use") == 3
    assert metrics.REGISTRY.get_sample_value("search_queue_depth") == 2
