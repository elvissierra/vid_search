"""Rate limiting on the search and ingest endpoints."""
import io
import os
from datetime import datetime, timezone

import pytest

import ratelimit


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    monkeypatch.setenv("CORS_ORIGINS", os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("RATE_LIMIT_SEARCH_PER_MIN", "3")
    monkeypatch.setenv("RATE_LIMIT_INGEST_PER_MIN", "2")
    import routes
    routes.app.config["TESTING"] = True
    return routes.app.test_client()


def login(client, email="ess@example.com"):
    resp = client.post("/api/signup", json={"email": email, "password": "hunter2hunter2"})
    return {"Authorization": f"Bearer {resp.get_json()['token']}"}


def search(client, headers=None, record="r", **extra):
    return client.post("/api/search", json={"record": record, "keyword": "x", **extra}, headers=headers or {})


def upload(client, record, headers=None):
    return client.post(
        "/api/upload",
        data={"record": record, "file": (io.BytesIO(b"abc"), "a.mp3")},
        content_type="multipart/form-data",
        headers=headers or {},
    )


def test_window_start_floors_to_the_minute():
    now = datetime(2026, 11, 11, 10, 5, 42, 123, tzinfo=timezone.utc)
    assert ratelimit.window_start(now) == datetime(2026, 11, 11, 10, 5, 0, tzinfo=timezone.utc)


def test_client_key_prefers_user_over_address():
    assert ratelimit.client_key(7, "1.2.3.4") == "user:7"
    assert ratelimit.client_key(None, "1.2.3.4") == "ip:1.2.3.4"


def test_check_counts_within_a_window_and_resets_in_the_next(db, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SEARCH_PER_MIN", "2")
    t0 = datetime(2026, 11, 11, 10, 0, 50, tzinfo=timezone.utc)
    assert ratelimit.check("search", "ip:a", t0) is None
    assert ratelimit.check("search", "ip:a", t0) is None
    wait = ratelimit.check("search", "ip:a", t0)
    assert wait == 11
    assert ratelimit.check("search", "ip:b", t0) is None
    later = datetime(2026, 11, 11, 10, 1, 0, tzinfo=timezone.utc)
    assert ratelimit.check("search", "ip:a", later) is None


def test_zero_disables_a_bucket(db, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SEARCH_PER_MIN", "0")
    for _ in range(5):
        assert ratelimit.check("search", "ip:a") is None
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM rate_limits;")
            assert cursor.fetchone()[0] == 0


def test_search_is_limited_with_retry_after(client):
    for _ in range(3):
        assert search(client).status_code == 400  # no record/url: allowed through, then refused
    resp = search(client)
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1
    body = resp.get_json()
    assert body["error"] == "Too many requests"
    assert body["retry_after_seconds"] == int(resp.headers["Retry-After"])


def test_limits_are_per_user(client):
    a, b = login(client, "a@example.com"), login(client, "b@example.com")
    for _ in range(3):
        search(client, a)
    assert search(client, a).status_code == 429
    assert search(client, b).status_code == 400
    assert search(client).status_code == 400  # anonymous has its own key


def test_upload_is_limited_before_anything_is_stored(client, tmp_path):
    assert upload(client, "one").status_code == 202
    assert upload(client, "two").status_code == 202
    resp = upload(client, "three")
    assert resp.status_code == 429
    stored = os.listdir(tmp_path / "up")
    assert len(stored) == 2
    from db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM records WHERE record = 'three';")
            assert cursor.fetchone()[0] == 0


def test_new_record_search_shares_the_ingest_bucket(client):
    assert search(client, record="a", url="http://x/1").status_code == 202
    assert upload(client, "b").status_code == 202
    resp = search(client, record="c", url="http://x/3")
    assert resp.status_code == 429
    assert resp.get_json()["error"] == "Too many requests"


def test_searching_an_existing_record_does_not_use_the_ingest_bucket(client):
    assert upload(client, "doc").status_code == 202
    for _ in range(3):
        assert search(client, record="doc").status_code == 200
    assert upload(client, "other").status_code == 202


def test_limiter_failure_fails_open(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(ratelimit, "check", boom)
    for _ in range(5):
        assert search(client).status_code == 400
