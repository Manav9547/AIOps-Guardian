"""Chaos control panel (commit 12): served page, and its polling kept out of the metrics."""

from app import metrics
from app.tests.conftest import AUTH


def _requests(endpoint: str) -> float:
    total = 0.0
    for metric in metrics.REGISTRY.collect():
        for s in metric.samples:
            if s.name == "http_requests_total" and s.labels.get("endpoint") == endpoint:
                total += s.value
    return total


def test_chaos_panel_is_served_as_html(client):
    r = client.get("/chaos")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Chaos control panel" in r.text
    for path in ("/admin/state", "/admin/fault/", "/admin/cache-mode", "/admin/search-slots"):
        assert path in r.text  # every endpoint the buttons call


def test_panel_page_needs_no_token_but_its_calls_do(client):
    assert client.get("/chaos").status_code == 200
    assert client.get("/admin/state").status_code == 401


def test_panel_polling_is_not_counted_as_traffic(client):
    before = _requests("/admin/state") + _requests("/chaos")
    client.get("/chaos")
    for _ in range(5):
        assert client.get("/admin/state", headers=AUTH).status_code == 200
    assert _requests("/admin/state") + _requests("/chaos") == before


def test_admin_actions_are_still_counted(client):
    before = _requests("/admin/fault/{name}")
    client.post("/admin/fault/slow_db", json={"enabled": False}, headers=AUTH)
    assert _requests("/admin/fault/{name}") == before + 1
