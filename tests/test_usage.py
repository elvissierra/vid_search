"""Usage ledger (jobs.audio_seconds) and the free-tier quota at enqueue."""
import io
import os
import uuid
from datetime import datetime, timezone

import pytest

import usage
import vid_search


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    monkeypatch.setenv("CORS_ORIGINS", os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("FREE_TIER_MINUTES", "10")
    import routes
    routes.app.config["TESTING"] = True
    return routes.app.test_client()


def login(client, email="ess@example.com"):
    resp = client.post("/api/signup", json={"email": email, "password": "hunter2hunter2"})
    return {"Authorization": f"Bearer {resp.get_json()['token']}"}


def uid(client, headers):
    return client.get("/api/me", headers=headers).get_json()["user"]["id"]


def add_usage(db, user_id, seconds, created="now()", status="done"):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO jobs (id, status, record, url, video_id, user_id, audio_seconds, created_at)
                VALUES (%s, %s, 'r', 'http://x', %s, %s, %s, {created});
                """,
                (str(uuid.uuid4()), status, str(uuid.uuid4()), user_id, seconds),
            )


def search(client, headers=None, record="ep"):
    return client.post("/api/search", json={"url": "http://x/v", "record": record}, headers=headers or {})


def upload(client, headers=None, record="ep"):
    return client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"audio"), "a.mp3"), "record": record},
        headers=headers or {},
        content_type="multipart/form-data",
    )


# --- ledger ---------------------------------------------------------------

def test_period_bounds_cover_the_utc_month():
    start, end = usage.period_bounds(datetime(2026, 11, 10, 15, 30, tzinfo=timezone.utc))
    assert (start, end) == (datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 12, 1, tzinfo=timezone.utc))
    start, end = usage.period_bounds(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc))
    assert (start, end) == (datetime(2026, 12, 1, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc))


def test_free_tier_defaults_to_an_hour_and_reads_the_env(monkeypatch):
    monkeypatch.delenv("FREE_TIER_MINUTES", raising=False)
    assert usage.free_tier_seconds() == 3600
    monkeypatch.setenv("FREE_TIER_MINUTES", "2.5")
    assert usage.free_tier_seconds() == 150


def test_ledger_lists_only_owned_jobs_with_audio_seconds(client, db):
    ess = login(client)
    user = uid(client, ess)
    add_usage(db, user, 120)
    add_usage(db, user, None)   # not transcribed yet: not a ledger entry
    add_usage(db, None, 999)    # unowned: not metered
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id, audio_seconds FROM usage_ledger;")
            assert cursor.fetchall() == [(user, 120.0)]


def test_summary_sums_this_month_only_and_counts_failed_jobs(client, db):
    ess = login(client)
    user = uid(client, ess)
    add_usage(db, user, 100)
    add_usage(db, user, 50, status="error")  # transcribed, then failed: time was spent
    add_usage(db, user, 900, created="date_trunc('month', now() AT TIME ZONE 'utc') - interval '1 day'")
    summary = usage.usage_summary(user)
    assert summary["used_seconds"] == 150
    assert summary["limit_seconds"] == 600
    assert summary["remaining_seconds"] == 450


def test_other_users_usage_is_not_counted(client, db):
    a = uid(client, login(client, "a@example.com"))
    b = uid(client, login(client, "b@example.com"))
    add_usage(db, a, 500)
    assert usage.usage_summary(b)["used_seconds"] == 0


# --- /api/usage -----------------------------------------------------------

def test_usage_endpoint_reports_the_summary(client, db):
    ess = login(client)
    add_usage(db, uid(client, ess), 90)
    body = client.get("/api/usage", headers=ess).get_json()
    assert body["used_seconds"] == 90
    assert body["limit_seconds"] == 600
    assert body["remaining_seconds"] == 510
    assert body["period_start"] < body["period_end"]


def test_usage_endpoint_requires_login(client):
    assert client.get("/api/usage").status_code == 401
    assert client.get("/api/usage", headers={"Authorization": "Bearer nope"}).status_code == 401


# --- quota at enqueue -----------------------------------------------------

def test_under_quota_can_enqueue(client, db):
    ess = login(client)
    add_usage(db, uid(client, ess), 599)
    assert search(client, ess).status_code == 202
    assert upload(client, ess, record="ep2").status_code == 202


def test_search_is_refused_with_402_once_the_quota_is_used(client, db):
    ess = login(client)
    add_usage(db, uid(client, ess), 600)
    resp = search(client, ess)
    assert resp.status_code == 402
    body = resp.get_json()
    assert body["error"] == "Monthly free-tier quota used up"
    assert body["used_seconds"] == 600 and body["remaining_seconds"] == 0
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM records;")
            assert cursor.fetchone() == (0,)   # nothing reserved
            cursor.execute("SELECT count(*) FROM jobs WHERE audio_seconds IS NULL;")
            assert cursor.fetchone() == (0,)   # nothing queued


def test_upload_is_refused_with_402_before_the_file_is_stored(client, db, tmp_path):
    ess = login(client)
    add_usage(db, uid(client, ess), 601)
    resp = upload(client, ess)
    assert resp.status_code == 402
    assert not (tmp_path / "up").exists() or os.listdir(tmp_path / "up") == []


def test_quota_does_not_block_searching_an_existing_record(client, db):
    ess = login(client)
    assert search(client, ess).status_code == 202
    add_usage(db, uid(client, ess), 600)
    resp = client.post("/api/search", json={"record": "ep", "keyword": "hello"}, headers=ess)
    assert resp.status_code == 200


def test_quota_is_per_user_and_anonymous_is_unmetered(client, db):
    a = login(client, "a@example.com")
    b = login(client, "b@example.com")
    add_usage(db, uid(client, a), 600)
    assert search(client, a).status_code == 402
    assert search(client, b).status_code == 202
    assert search(client, None, record="anon").status_code == 202


# --- worker records the ledger entry --------------------------------------

class FakeModel:
    def transcribe(self, audio_file, word_timestamps, language):
        return {"segments": [
            {"text": "hello", "words": [{"word": "hello", "start": 0.0, "end": 1.0}], "end": 1.0},
            {"text": "world", "words": [{"word": "world", "start": 61.0, "end": 62.5}], "end": 62.5},
        ]}


def test_process_audio_reports_the_transcribed_length(db, monkeypatch):
    monkeypatch.setattr(vid_search, "get_model", lambda: FakeModel())
    monkeypatch.setattr(vid_search.diarize, "diarize", lambda f: [])
    seen = []
    video_id, _ = vid_search.reserve_record("ep", source_url="http://x")
    vid_search.process_audio("a.mp3", "ep", video_id, duration_cb=seen.append)
    assert seen == [62.5]


def test_worker_stores_audio_seconds_on_the_job(client, db, monkeypatch):
    import worker
    ess = login(client)
    resp = search(client, ess)
    job_id = resp.get_json()["job_id"]

    def fake_process(audio_file, record, video_id, duration_cb=None, **kwargs):
        duration_cb(125.5)

    monkeypatch.setattr(vid_search, "download_video_audio", lambda url: "nonexistent.mp3")
    monkeypatch.setattr(vid_search, "process_audio", fake_process)
    worker.process_job(worker.claim_job())

    assert usage.usage_summary(uid(client, ess))["used_seconds"] == 125.5
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT audio_seconds FROM jobs WHERE id = %s;", (job_id,))
            assert cursor.fetchone() == (125.5,)
