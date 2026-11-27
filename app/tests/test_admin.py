"""Admin endpoints: token auth on every route, faults, cache mode, search slots."""

import pytest

from app import faults
from app.tests.conftest import ADMIN_TOKEN, AUTH

ADMIN_CALLS = [
    ("GET", "/admin/state", None),
    ("GET", "/admin/faults", None),
    ("POST", "/admin/fault/slow_db", {"enabled": True}),
    ("PUT", "/admin/cache-mode", {"enabled": True}),
    ("PUT", "/admin/search-slots", {"slots": 3}),
]


@pytest.mark.parametrize("method, path, body", ADMIN_CALLS)
@pytest.mark.parametrize("headers", [
    {},                                                    # no header
    {"Authorization": "Bearer wrong-token"},               # wrong token
    {"Authorization": f"Basic {ADMIN_TOKEN}"},             # wrong scheme
    {"Authorization": ADMIN_TOKEN},                        # no scheme
    {"Authorization": "Bearer "},                          # empty token
], ids=["missing", "wrong", "basic", "no-scheme", "empty"])
def test_admin_without_valid_token_is_401(client, method, path, body, headers):
    r = client.request(method, path, json=body, headers=headers)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("method, path, body", ADMIN_CALLS)
def test_admin_with_token_succeeds(client, method, path, body):
    assert client.request(method, path, json=body, headers=AUTH).status_code == 200


def test_admin_refuses_everyone_when_no_token_configured(client, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN")
    assert client.get("/admin/state", headers={"Authorization": "Bearer "}).status_code == 401
    assert client.get("/admin/state", headers=AUTH).status_code == 401


def test_rejected_call_changes_nothing(client):
    client.post("/admin/fault/slow_db", json={"enabled": True})
    assert faults.state()["slow_db"] is False


def test_all_faults_off_by_default(client):
    r = client.get("/admin/faults", headers=AUTH)
    assert r.json() == {"faults": {"cpu_hog": False, "memory_leak": False, "slow_db": False}}


def test_fault_set_and_toggle(client):
    r = client.post("/admin/fault/slow_db", json={"enabled": True}, headers=AUTH)
    assert r.json()["faults"]["slow_db"] is True
    r = client.post("/admin/fault/slow_db", headers=AUTH)          # no body: toggle
    assert r.json()["faults"]["slow_db"] is False
    r = client.post("/admin/fault/slow_db", headers=AUTH)
    assert r.json()["faults"]["slow_db"] is True


def test_memory_leak_switch_through_api(client):
    r = client.post("/admin/fault/memory_leak", json={"enabled": True}, headers=AUTH)
    assert r.json()["faults"]["memory_leak"] is True
    r = client.post("/admin/fault/memory_leak", json={"enabled": False}, headers=AUTH)
    assert r.json()["faults"]["memory_leak"] is False


def test_unknown_fault_is_404(client):
    assert client.post("/admin/fault/disk_full", json={"enabled": True}, headers=AUTH).status_code == 404


def test_cache_mode_on_and_off(client, fake_db):
    r = client.put("/admin/cache-mode", json={"enabled": True}, headers=AUTH)
    assert r.json()["search"]["cache"]["enabled"] is True
    assert r.json()["search"]["cache"]["trains"] == len(fake_db.trains)
    assert client.get("/search").json()["cached"] is True

    r = client.put("/admin/cache-mode", json={"enabled": False}, headers=AUTH)
    assert r.json()["search"]["cache"]["enabled"] is False
    assert client.get("/search").json()["cached"] is False


def test_search_slots_resize_live(client, clean_state):
    r = client.put("/admin/search-slots", json={"slots": 12}, headers=AUTH)
    assert r.json()["search"]["slots"] == 12
    assert clean_state.slots == 12
    assert client.get("/admin/state", headers=AUTH).json()["search"]["slots"] == 12


@pytest.mark.parametrize("slots", [0, -1, 101])
def test_search_slots_out_of_range_is_422(client, clean_state, slots):
    assert client.put("/admin/search-slots", json={"slots": slots}, headers=AUTH).status_code == 422
    assert clean_state.slots == 5
