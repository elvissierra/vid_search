"""Health endpoint, job metrics, structured logs and worker log lines."""
import json
import logging
import os
import uuid

import pytest

import logs
import metrics


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    import routes
    routes.app.config["TESTING"] = True
    return routes.app.test_client()


def add_job(db, status, *, started="NULL", finished="NULL", created="now()", audio=None):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO jobs (id, status, record, url, video_id, audio_seconds,
                                  created_at, started_at, finished_at)
                VALUES (%s, %s, 'r', 'http://x', %s, %s, {created}, {started}, {finished});
                """,
                (str(uuid.uuid4()), status, str(uuid.uuid4()), audio),
            )


# --- health -----------------------------------------------------------------

def test_health_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "db": "ok"}


def test_health_needs_no_auth_and_ignores_bad_token(client):
    resp = client.get("/api/health", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 200


def test_health_503_when_database_is_down(client, monkeypatch):
    import routes

    def broken():
        raise RuntimeError("connection refused")

    monkeypatch.setattr(routes, "get_conn", broken)
    resp = client.get("/api/health")
    assert resp.status_code == 503
    assert resp.get_json() == {"status": "degraded", "db": "error"}


# --- metrics ----------------------------------------------------------------

def test_metrics_disabled_without_token(client):
    assert client.get("/api/metrics").status_code == 404
    assert client.get("/api/metrics", headers={"Authorization": "Bearer x"}).status_code == 404


@pytest.mark.parametrize("header", [None, "", "Bearer wrong", "Basic secret", "secret"])
def test_metrics_rejects_bad_credentials(client, monkeypatch, header):
    monkeypatch.setenv("METRICS_TOKEN", "secret")
    headers = {} if header is None else {"Authorization": header}
    assert client.get("/api/metrics", headers=headers).status_code == 401


def test_metrics_empty_database(client, monkeypatch):
    monkeypatch.setenv("METRICS_TOKEN", "secret")
    resp = client.get("/api/metrics", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert resp.get_json() == {
        "jobs": {"queued": 0, "running": 0, "done": 0, "error": 0},
        "oldest_queued_age_seconds": None,
        "window_hours": 24,
        "finished_in_window": {
            "done": 0, "error": 0, "avg_processing_seconds": None, "audio_seconds": 0.0,
        },
    }


def test_metrics_counts_and_window(client, db, monkeypatch):
    monkeypatch.setenv("METRICS_TOKEN", "secret")
    add_job(db, "queued", created="now() - interval '120 seconds'")
    add_job(db, "queued", created="now() - interval '30 seconds'")
    add_job(db, "running", started="now()")
    # finished in the window: 100s and 200s of work -> avg 150s
    add_job(db, "done", started="now() - interval '200 seconds'", finished="now() - interval '100 seconds'", audio=600)
    add_job(db, "done", started="now() - interval '300 seconds'", finished="now() - interval '100 seconds'", audio=300)
    add_job(db, "error", started="now() - interval '50 seconds'", finished="now()", audio=50)
    # finished two days ago: counted by status, but outside the window
    add_job(db, "done", started="now() - interval '2 days'", finished="now() - interval '47 hours'", audio=9999)

    body = client.get("/api/metrics", headers={"Authorization": "Bearer secret"}).get_json()
    assert body["jobs"] == {"queued": 2, "running": 1, "done": 3, "error": 1}
    assert 119 <= body["oldest_queued_age_seconds"] <= 130
    window = body["finished_in_window"]
    assert window["done"] == 2 and window["error"] == 1
    assert window["avg_processing_seconds"] == 150.0
    assert window["audio_seconds"] == 950.0


def test_metrics_function_directly(db):
    add_job(db, "queued")
    with db() as conn:
        with conn.cursor() as cursor:
            out = metrics.job_metrics(cursor)
    assert out["jobs"]["queued"] == 1
    assert out["oldest_queued_age_seconds"] >= 0


# --- structured logs ----------------------------------------------------------

def format_record(service="svc", **kwargs):
    record = logging.LogRecord("x.y", logging.INFO, __file__, 1, kwargs.pop("msg", "hello %s"),
                               kwargs.pop("args", ("world",)), kwargs.pop("exc_info", None))
    for key, value in kwargs.items():
        setattr(record, key, value)
    return json.loads(logs.JsonFormatter(service).format(record))


def test_json_formatter_core_fields():
    line = format_record()
    assert line["message"] == "hello world"
    assert line["level"] == "INFO"
    assert line["service"] == "svc"
    assert line["logger"] == "x.y"
    assert line["ts"].endswith("+00:00")


def test_json_formatter_includes_extra_fields_only():
    line = format_record(job_id="j1", duration_seconds=1.5)
    assert line["job_id"] == "j1" and line["duration_seconds"] == 1.5
    assert "args" not in line and "msg" not in line and "levelno" not in line


def test_json_formatter_exception_and_unserialisable_extra():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        line = format_record(exc_info=sys.exc_info(), thing=object())
    assert "ValueError: boom" in line["exc_info"]
    assert isinstance(line["thing"], str)


def test_configure_is_idempotent_and_sets_level(monkeypatch):
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        monkeypatch.setenv("LOG_LEVEL", "debug")
        logs.configure("a")
        logs.configure("b")
        ours = [h for h in root.handlers if getattr(h, "_vid_search_json", False)]
        assert len(ours) == 1 and ours[0].formatter.service == "b"
        assert root.level == logging.DEBUG
        monkeypatch.setenv("LOG_LEVEL", "nonsense")
        logs.configure("b")
        assert root.level == logging.INFO
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_request_log_line(client, caplog):
    with caplog.at_level(logging.INFO, logger="api.request"):
        client.get("/api/me")
    rec = [r for r in caplog.records if r.name == "api.request"][-1]
    assert (rec.method, rec.path, rec.status) == ("GET", "/api/me", 401)
    assert rec.duration_ms >= 0


def test_health_requests_are_debug_only(client, caplog):
    with caplog.at_level(logging.INFO, logger="api.request"):
        client.get("/api/health")
    assert not [r for r in caplog.records if r.name == "api.request"]
    with caplog.at_level(logging.DEBUG, logger="api.request"):
        client.get("/api/health")
    assert [r for r in caplog.records if r.name == "api.request"]


# --- worker -----------------------------------------------------------------

def queue_one(db):
    job_id, video_id = str(uuid.uuid4()), str(uuid.uuid4())
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO records (record, video_id) VALUES ('ep', %s);", (video_id,))
            cursor.execute(
                "INSERT INTO jobs (id, record, url, video_id) VALUES (%s, 'ep', 'http://x', %s);",
                (job_id, video_id),
            )
    return job_id


def test_worker_logs_job_lifecycle(db, monkeypatch, caplog):
    import resolver
    import vid_search
    import worker

    job_id = queue_one(db)
    monkeypatch.setattr(resolver, "resolve_audio_url", lambda url: url)
    monkeypatch.setattr(vid_search, "download_video_audio", lambda url: "/nonexistent.mp3")

    def fake_process(audio_file, record, video_id, duration_cb=None, **kwargs):
        duration_cb(42.5)

    monkeypatch.setattr(vid_search, "process_audio", fake_process)
    with caplog.at_level(logging.INFO, logger="worker"):
        worker.process_job(worker.claim_job())

    started, done = [r for r in caplog.records if r.name == "worker"]
    assert started.getMessage() == "job started" and started.job_id == job_id
    assert done.getMessage() == "job done"
    assert (done.job_id, done.record, done.status, done.audio_seconds) == (job_id, "ep", "done", 42.5)
    assert done.duration_seconds >= 0


def test_worker_logs_failure_with_traceback(db, monkeypatch, caplog):
    import resolver
    import vid_search
    import worker

    job_id = queue_one(db)
    monkeypatch.setattr(resolver, "resolve_audio_url", lambda url: url)
    monkeypatch.setattr(vid_search, "download_video_audio", lambda url: "/nonexistent.mp3")

    def failing(*args, **kwargs):
        raise RuntimeError("whisper exploded")

    monkeypatch.setattr(vid_search, "process_audio", failing)
    with caplog.at_level(logging.INFO, logger="worker"):
        worker.process_job(worker.claim_job())

    failed = [r for r in caplog.records if r.getMessage() == "job failed"][0]
    assert failed.levelno == logging.ERROR
    assert (failed.job_id, failed.status, failed.audio_seconds) == (job_id, "error", None)
    assert "whisper exploded" in logs.JsonFormatter("worker").format(failed)
