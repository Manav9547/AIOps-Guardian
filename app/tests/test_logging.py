import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import logging as applog


@pytest.fixture
def client_and_logs():
    applog.setup()
    buf = io.StringIO()
    logging.getLogger().handlers[0].stream = buf

    app = FastAPI()
    applog.instrument(app)

    @app.get("/search")
    def search():
        logging.getLogger("booking.search").info("searching", extra={"rows": 4})
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    @app.get("/health")
    def health():
        return {"ok": True}

    def lines():
        return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]

    return TestClient(app, raise_server_exceptions=False), lines


def request_lines(lines):
    return [entry for entry in lines() if entry.get("event") == "request"]


def test_one_json_line_per_request_with_required_fields(client_and_logs):
    client, lines = client_and_logs
    r = client.get("/search")
    reqs = request_lines(lines)
    assert len(reqs) == 1
    entry = reqs[0]
    for key in ("time", "endpoint", "status", "latency_ms", "request_id"):
        assert key in entry
    assert entry["endpoint"] == "/search"
    assert entry["status"] == 200
    assert entry["time"].endswith("Z")
    assert entry["request_id"] == r.headers["X-Request-ID"]


def test_reuses_incoming_request_id_and_tags_app_logs(client_and_logs):
    client, lines = client_and_logs
    client.get("/search", headers={"X-Request-ID": "abc123"})
    app_line = next(e for e in lines() if e["message"] == "searching")
    assert app_line["request_id"] == "abc123"
    assert app_line["rows"] == 4
    assert request_lines(lines)[0]["request_id"] == "abc123"


def test_unhandled_error_logged_as_500(client_and_logs):
    client, lines = client_and_logs
    assert client.get("/boom").status_code == 500
    assert any(e.get("event") == "error" and "exc" in e for e in lines())
    assert request_lines(lines)[0]["status"] == 500


def test_health_probe_is_quiet(client_and_logs):
    client, lines = client_and_logs
    client.get("/health")
    assert request_lines(lines) == []
