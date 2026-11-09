"""Records, jobs and exports are scoped to the owning user."""
import io
import os

import pytest

import vid_search


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    monkeypatch.setenv("CORS_ORIGINS", os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "up"))
    import routes
    routes.app.config["TESTING"] = True
    return routes.app.test_client()


def login(client, email):
    resp = client.post("/api/signup", json={"email": email, "password": "hunter2hunter2"})
    return {"Authorization": f"Bearer {resp.get_json()['token']}"}


def user_id(client, headers):
    return client.get("/api/me", headers=headers).get_json()["user"]["id"]


def seed_transcript(db, video_id, record="ep"):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO transcripts
                    (video_id, record, segment_index, segment_text, word, start_time, end_time, speaker)
                VALUES (%s, %s, 0, 'hello world', 'hello', 0, 1, 'SPEAKER_00'),
                       (%s, %s, 0, 'hello world', 'world', 1, 2, 'SPEAKER_00');
                """,
                (video_id, record, video_id, record),
            )


def search(client, headers=None, **body):
    return client.post("/api/search", json=body, headers=headers or {})


def test_new_record_and_job_belong_to_the_logged_in_user(client, db):
    ess = login(client, "ess@example.com")
    resp = search(client, ess, url="http://x/v", record="ep1")
    assert resp.status_code == 202
    uid = user_id(client, ess)
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id FROM records WHERE record = 'ep1';")
            assert cursor.fetchone() == (uid,)
            cursor.execute("SELECT user_id FROM jobs WHERE id = %s;", (resp.get_json()["job_id"],))
            assert cursor.fetchone() == (uid,)


def test_upload_belongs_to_the_logged_in_user(client, db):
    ess = login(client, "ess@example.com")
    resp = client.post(
        "/api/upload",
        data={"record": "up1", "file": (io.BytesIO(b"abc"), "a.mp3")},
        content_type="multipart/form-data", headers=ess,
    )
    assert resp.status_code == 202
    uid = user_id(client, ess)
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id FROM records WHERE record = 'up1';")
            assert cursor.fetchone() == (uid,)
            cursor.execute("SELECT user_id FROM jobs WHERE record = 'up1';")
            assert cursor.fetchone() == (uid,)


def test_records_list_only_shows_the_viewers_own(client):
    ess, other = login(client, "ess@example.com"), login(client, "other@example.com")
    search(client, ess, url="http://x/1", record="mine")
    search(client, other, url="http://x/2", record="theirs")
    search(client, None, url="http://x/3", record="public")

    assert client.get("/api/records", headers=ess).get_json() == {"records": ["mine"]}
    assert client.get("/api/records", headers=other).get_json() == {"records": ["theirs"]}
    assert client.get("/api/records").get_json() == {"records": ["public"]}


def test_same_label_can_exist_for_different_owners(client):
    ess, other = login(client, "ess@example.com"), login(client, "other@example.com")
    assert search(client, ess, url="http://x/1", record="ep").status_code == 202
    assert search(client, other, url="http://x/2", record="ep").status_code == 202
    assert search(client, None, url="http://x/3", record="ep").status_code == 202
    # Same owner, same label: the record exists now, so no new job is queued.
    assert search(client, ess, url="http://x/4", record="ep").status_code == 200


def test_reserve_record_is_unique_per_owner_including_unowned(db):
    a, a_new = vid_search.reserve_record("ep", user_id=None)
    b, b_new = vid_search.reserve_record("ep", user_id=None)
    assert a_new and not b_new and a == b
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO users (email, password_hash) VALUES ('u@x.co', 'h') RETURNING id;")
            uid = cursor.fetchone()[0]
    c, c_new = vid_search.reserve_record("ep", user_id=uid)
    assert c_new and c != a


def test_search_cannot_reach_another_users_record(client, db):
    ess, other = login(client, "ess@example.com"), login(client, "other@example.com")
    search(client, ess, url="http://x/1", record="secret")
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT video_id FROM records WHERE record = 'secret';")
            video_id = cursor.fetchone()[0]
    seed_transcript(db, video_id, "secret")

    mine = search(client, ess, record="secret", keyword="hello")
    assert mine.status_code == 200
    assert [r["word"] for r in mine.get_json()["results"]] == ["hello"]

    # Another user (or anonymous) naming the label without a url gets nothing.
    for headers in (login(client, "third@example.com"), other, None):
        resp = search(client, headers, record="secret", keyword="hello")
        assert resp.status_code == 400


def test_jobs_are_hidden_from_other_viewers(client):
    ess, other = login(client, "ess@example.com"), login(client, "other@example.com")
    job_id = search(client, ess, url="http://x/1", record="ep").get_json()["job_id"]

    assert client.get(f"/api/jobs/{job_id}", headers=ess).status_code == 200
    assert client.get(f"/api/jobs/{job_id}", headers=other).status_code == 404
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_exports_are_scoped_to_the_owner(client, db):
    ess, other = login(client, "ess@example.com"), login(client, "other@example.com")
    search(client, ess, url="http://x/1", record="ep")
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT video_id FROM records WHERE record = 'ep';")
            video_id = cursor.fetchone()[0]
    seed_transcript(db, video_id)

    ok = client.get(f"/api/export/{video_id}?format=txt", headers=ess)
    assert ok.status_code == 200 and b"hello world" in ok.data
    assert client.get(f"/api/export/{video_id}?format=txt", headers=other).status_code == 404
    assert client.get(f"/api/export/{video_id}?format=json").status_code == 404


def test_anonymous_still_reaches_unowned_legacy_rows(client, db):
    video_id, _ = vid_search.reserve_record("legacy")
    seed_transcript(db, video_id, "legacy")
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO jobs (id, record, video_id) VALUES ('legacy-job', 'legacy', %s);", (video_id,)
            )
    ess = login(client, "ess@example.com")

    assert client.get("/api/records").get_json() == {"records": ["legacy"]}
    assert client.get("/api/jobs/legacy-job").status_code == 200
    assert client.get(f"/api/export/{video_id}?format=txt").status_code == 200
    # A logged-in user does not see the unowned rows.
    assert client.get("/api/records", headers=ess).get_json() == {"records": []}
    assert client.get("/api/jobs/legacy-job", headers=ess).status_code == 404
    assert client.get(f"/api/export/{video_id}?format=txt", headers=ess).status_code == 404


@pytest.mark.parametrize("path, method", [
    ("/api/records", "get"), ("/api/jobs/x", "get"), ("/api/export/x", "get"),
    ("/api/search", "post"), ("/api/upload", "post"),
])
def test_invalid_token_is_401_not_anonymous(client, path, method):
    bad = {"Authorization": "Bearer not-a-real-token"}
    resp = getattr(client, method)(path, headers=bad, **({"json": {}} if path == "/api/search" else {}))
    assert resp.status_code == 401


def test_deleting_a_user_removes_their_records_and_jobs(client, db):
    ess = login(client, "ess@example.com")
    search(client, ess, url="http://x/1", record="ep")
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM users;")
            cursor.execute("SELECT count(*) FROM records;")
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT count(*) FROM jobs;")
            assert cursor.fetchone() == (0,)
