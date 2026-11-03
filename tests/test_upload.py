"""POST /api/upload: validation, size limit, and what gets queued."""
import io
import os

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


def test_traversal_in_filename_cannot_choose_the_path(client, db, tmp_path):
    resp = post(client, name="../../evil.mp3")
    assert resp.status_code == 202
    (path,), = rows(db, "SELECT upload_path FROM jobs")
    assert os.path.dirname(path) == str(tmp_path / "up")
    assert not (tmp_path / "evil.mp3").exists()


def test_extension_helper():
    assert uploads.extension_of("A.Mp4") == ".mp4"
    assert uploads.extension_of("") == ""
    assert uploads.extension_of(None) == ""
