"""POST /api/upload: validation, size limit, and what gets queued."""
import io
import os
import uuid

import pytest

import uploads


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    monkeypatch.setenv("CORS_ORIGINS", os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "up"))
    import routes
    routes.app.config["TESTING"] = True
    monkeypatch.setitem(routes.app.config, "MAX_CONTENT_LENGTH", 1024)
    return routes.app.test_client()


def post(client, name="talk.mp3", data=b"abc", **form):
    form.setdefault("record", "ep1")
    body = dict(form)
    if name is not None:
        body["file"] = (io.BytesIO(data), name)
    return client.post("/api/upload", data=body, content_type="multipart/form-data")


def rows(db, sql):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()


def stored_files(tmp_path):
    d = tmp_path / "up"
    return sorted(os.listdir(d)) if d.exists() else []


def test_upload_is_queued_with_server_generated_path(client, db, tmp_path):
    resp = post(client, name="My Talk.MP3", language="Spanish")
    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]

    (status, url, upload_path, language, record), = rows(
        db, f"SELECT status, url, upload_path, language, record FROM jobs WHERE id = '{job_id}'")
    assert (status, url, language, record) == ("queued", None, "es", "ep1")
    assert os.path.dirname(upload_path) == str(tmp_path / "up")
    assert upload_path.endswith(".mp3")
    assert "Talk" not in os.path.basename(upload_path)
    assert open(upload_path, "rb").read() == b"abc"
    assert rows(db, "SELECT record, source_url FROM records") == [("ep1", None)]


@pytest.mark.parametrize("name", ["notes.txt", "run.exe", "noext", "archive.mp3.zip", ".mp3"])
def test_disallowed_types_are_rejected_without_side_effects(client, db, tmp_path, name):
    resp = post(client, name=name)
    assert resp.status_code == 400
    assert rows(db, "SELECT 1 FROM records") == []
    assert rows(db, "SELECT 1 FROM jobs") == []
    assert stored_files(tmp_path) == []


def test_missing_file_record_and_bad_language(client, db, tmp_path):
    assert post(client, name=None).status_code == 400
    assert post(client, record="  ").status_code == 400
    assert post(client, language="klingon").status_code == 400
    assert rows(db, "SELECT 1 FROM records") == []
    assert stored_files(tmp_path) == []


def test_oversized_upload_is_413_json(client, db, tmp_path):
    resp = post(client, data=b"x" * 5000)
    assert resp.status_code == 413
    assert "too large" in resp.get_json()["error"].lower()
    assert rows(db, "SELECT 1 FROM records") == []
    assert stored_files(tmp_path) == []


def test_duplicate_record_is_409_and_file_is_discarded(client, db, tmp_path):
    assert post(client).status_code == 202
    assert post(client, name="again.wav").status_code == 409
    assert len(stored_files(tmp_path)) == 1
    assert len(rows(db, "SELECT 1 FROM jobs")) == 1


@pytest.mark.parametrize("name", [
    "../../evil.mp3",
    "..\\..\\evil.mp3",
    "/etc/cron.d/evil.mp3",
    "C:\\Windows\\evil.mp3",
    "a/b/c/evil.mp3",
    "sp ace; rm -rf.mp3",
    "t\u00e9st\u202e3pm.mp3",
    ("x" * 300) + ".mp3",
])
def test_client_filename_cannot_choose_the_path(client, db, tmp_path, name):
    resp = post(client, name=name)
    assert resp.status_code == 202
    (path,), = rows(db, "SELECT upload_path FROM jobs")
    assert os.path.dirname(path) == str(tmp_path / "up")
    stored = os.path.basename(path)
    assert uuid.UUID(os.path.splitext(stored)[0])
    assert stored.endswith(".mp3")
    # nothing was written anywhere but the upload directory
    assert stored_files(tmp_path) == [stored]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["up"]


def test_extension_is_lowercased_and_only_the_last_one_counts(client, db, tmp_path):
    assert post(client, name="clip.tar.MP4").status_code == 202
    (path,), = rows(db, "SELECT upload_path FROM jobs")
    assert path.endswith(".mp4")
    assert ".tar" not in os.path.basename(path)


def test_failed_job_insert_removes_file_and_releases_record(client, db, tmp_path, monkeypatch):
    import routes

    real_get_conn = routes.get_conn
    calls = {"n": 0}

    def failing_get_conn():
        calls["n"] += 1
        raise RuntimeError("db down")

    # reserve_record uses vid_search.get_conn, so only the job insert fails.
    monkeypatch.setattr(routes, "get_conn", failing_get_conn)
    resp = post(client)
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Internal server error"}
    assert calls["n"] == 1
    monkeypatch.setattr(routes, "get_conn", real_get_conn)

    assert stored_files(tmp_path) == []
    assert rows(db, "SELECT 1 FROM records") == []
    assert rows(db, "SELECT 1 FROM jobs") == []
    # the label is free again, so a retry succeeds
    assert post(client).status_code == 202


def test_failed_reservation_removes_file(client, db, tmp_path, monkeypatch):
    import routes

    def boom(record, source_url=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(routes, "reserve_record", boom)
    resp = post(client)
    assert resp.status_code == 500
    assert stored_files(tmp_path) == []
    assert rows(db, "SELECT 1 FROM jobs") == []


def test_failed_save_leaves_nothing_behind(client, db, tmp_path, monkeypatch):
    def boom(_file_storage):
        raise OSError("disk full")

    monkeypatch.setattr(uploads, "save_upload", boom)
    resp = post(client)
    assert resp.status_code == 500
    assert rows(db, "SELECT 1 FROM records") == []
    assert rows(db, "SELECT 1 FROM jobs") == []


def claim_uploaded_job(db):
    import worker
    job = worker.claim_job()
    assert job is not None
    return worker, job


def test_worker_deletes_upload_after_success(client, db, tmp_path, monkeypatch):
    import vid_search
    assert post(client).status_code == 202
    (path,), = rows(db, "SELECT upload_path FROM jobs")
    seen = {}

    def fake_process(audio_file, record, video_id, **kwargs):
        seen["file"] = audio_file
        assert os.path.exists(audio_file)

    monkeypatch.setattr(vid_search, "process_audio", fake_process)
    worker, job = claim_uploaded_job(db)
    worker.process_job(job)

    assert seen["file"] == path
    assert not os.path.exists(path)
    (status,), = rows(db, "SELECT status FROM jobs")
    assert status == "done"


def test_worker_deletes_upload_and_frees_record_after_failure(client, db, tmp_path, monkeypatch):
    import vid_search
    assert post(client).status_code == 202
    (path,), = rows(db, "SELECT upload_path FROM jobs")

    def failing_process(*args, **kwargs):
        raise RuntimeError("whisper exploded")

    monkeypatch.setattr(vid_search, "process_audio", failing_process)
    worker, job = claim_uploaded_job(db)
    worker.process_job(job)

    assert not os.path.exists(path)
    (status, error), = rows(db, "SELECT status, error FROM jobs")
    assert status == "error" and "whisper exploded" in error
    assert rows(db, "SELECT 1 FROM records") == []
    # the label can be uploaded again
    assert post(client).status_code == 202


def test_extension_helper():
    assert uploads.extension_of("A.Mp4") == ".mp4"
    assert uploads.extension_of("") == ""
    assert uploads.extension_of(None) == ""
