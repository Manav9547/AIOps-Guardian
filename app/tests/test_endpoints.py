"""Public endpoints with the database stubbed (see conftest.fake_db)."""

import pytest

from app import db, main


def test_root_reports_version(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"service": "booking-api", "version": main.APP_VERSION}


def test_health_ok_when_db_answers(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["db"] == "ok"


def test_health_503_when_db_down(client, fake_db):
    fake_db.healthy = False
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["db"] == "unreachable"


def test_search_returns_trains_from_db(client, fake_db):
    r = client.get("/search")
    assert r.status_code == 200
    assert r.json()["cached"] is False
    assert len(r.json()["trains"]) == 2
    assert fake_db.search_calls == 1


def test_search_filters_by_route(client):
    r = client.get("/search", params={"origin": "mumbai", "destination": "goa"})
    assert [t["number"] for t in r.json()["trains"]] == ["T201"]


def test_search_429_when_every_slot_is_busy(client, clean_state, monkeypatch):
    monkeypatch.setattr(main, "SEARCH_QUEUE_TIMEOUT", 0.05)
    clean_state.used = clean_state.slots  # every slot held by someone else
    r = client.get("/search")
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "1"


def test_search_in_cache_mode_skips_db_and_queue(client, fake_db, clean_state, monkeypatch):
    import anyio

    from app import cache

    anyio.run(cache.enable)
    monkeypatch.setattr(main, "SEARCH_QUEUE_TIMEOUT", 0.05)
    clean_state.used = clean_state.slots  # queue full, but cache mode never waits for it
    r = client.get("/search", params={"origin": "Delhi"})
    assert r.status_code == 200
    assert r.json()["cached"] is True
    assert [t["number"] for t in r.json()["trains"]] == ["T101"]
    assert fake_db.search_calls == 0


def test_book_returns_201(client):
    r = client.post("/book", json={"train_id": 1, "passenger": "Asha", "seats": 2})
    assert r.status_code == 201
    assert r.json()["seats"] == 2
    assert r.json()["amount_cents"] == 2000


@pytest.mark.parametrize("error, status", [(db.SoldOut, 409), (db.TrainNotFound, 404)])
def test_book_maps_db_errors(client, fake_db, error, status):
    fake_db.book_error = error
    r = client.post("/book", json={"train_id": 1, "passenger": "Asha"})
    assert r.status_code == status


@pytest.mark.parametrize("body", [
    {"train_id": 0, "passenger": "Asha"},              # train_id must be > 0
    {"train_id": 1, "passenger": ""},                  # passenger required
    {"train_id": 1, "passenger": "Asha", "seats": 7},  # at most 6 seats
    {"train_id": 1, "passenger": "Asha", "seats": 0},
])
def test_book_rejects_invalid_body(client, body):
    assert client.post("/book", json=body).status_code == 422
