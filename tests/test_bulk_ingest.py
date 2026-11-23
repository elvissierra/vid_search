"""feeds.py parsing and POST /api/ingest/bulk."""
import os

import pytest

import feeds

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Show</title>
<item><title>Ep 3</title><enclosure url="https://cdn.example/ep3.mp3" type="audio/mpeg"/></item>
<item><title>No audio</title></item>
<item><title>Ep 2</title><enclosure url="https://cdn.example/ep2.mp3" type="audio/mpeg"/></item>
<item><enclosure url="https://cdn.example/ep1.mp3"/></item>
</channel></rss>"""


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setattr(feeds, "check_public_url", lambda url: None)


def test_parse_rss_keeps_only_items_with_enclosures(public):
    assert feeds.parse_rss(RSS, 10) == [
        {"title": "Ep 3", "url": "https://cdn.example/ep3.mp3"},
        {"title": "Ep 2", "url": "https://cdn.example/ep2.mp3"},
        {"title": "", "url": "https://cdn.example/ep1.mp3"},
    ]


def test_parse_rss_respects_limit():
    assert len(feeds.parse_rss(RSS, 2)) == 2


@pytest.mark.parametrize("data", [b"<html><body>hi</body></html>", b"not xml", b"<?xml version='1.0'?><feed/>", b"<?xml version='1.0'?><rss"])
def test_parse_rss_returns_none_when_not_rss(data):
    assert feeds.parse_rss(data, 5) is None


def test_parse_rss_refuses_entities():
    evil = b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaa">]><rss><channel/></rss>'
    with pytest.raises(feeds.FeedError):
        feeds.parse_rss(evil, 5)


def test_list_entries_prefers_rss_and_falls_back_to_playlist(public):
    rss = feeds.list_entries("https://x.example/feed", 5, fetch=lambda u: RSS, playlist=lambda u, n: pytest.fail("no"))
    assert [e["title"] for e in rss] == ["Ep 3", "Ep 2", ""]
    seen = {}

    def playlist(url, limit):
        seen["args"] = (url, limit)
        return [{"title": "v", "url": "https://y.example/v"}]

    out = feeds.list_entries("https://y.example/list", 7, fetch=lambda u: b"<html/>", playlist=playlist)
    assert out == [{"title": "v", "url": "https://y.example/v"}]
    assert seen["args"] == ("https://y.example/list", 7)


@pytest.mark.parametrize("url", ["ftp://x.example/f", "file:///etc/passwd", "http://127.0.0.1/f", "http://localhost/f",
                                 "http://10.0.0.5/f", "http://169.254.169.254/latest", "http://[::1]/f", "javascript:1", ""])
def test_check_public_url_rejects_non_public(url):
    with pytest.raises(feeds.InvalidUrl):
        feeds.check_public_url(url)


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    monkeypatch.setenv("RATE_LIMIT_INGEST_PER_MIN", "0")
    import routes
    routes.app.config["TESTING"] = True
    return routes.app.test_client()


def login(client, email):
    resp = client.post("/api/signup", json={"email": email, "password": "hunter2hunter2"})
    return {"Authorization": f"Bearer {resp.get_json()['token']}"}


def stub(monkeypatch, entries):
    calls = []

    def fake(url, limit):
        calls.append((url, limit))
        return entries

    monkeypatch.setattr(feeds, "list_entries", fake)
    return calls


def bulk(client, headers=None, **body):
    return client.post("/api/ingest/bulk", json=body, headers=headers or {})


def jobs(db):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT record, url, language, user_id, status FROM jobs ORDER BY record;")
            return cursor.fetchall()


def test_queues_one_job_per_entry(client, db, monkeypatch):
    calls = stub(monkeypatch, [{"title": "A", "url": "https://c/a.mp3"}, {"title": "B", "url": "https://c/b.mp3"}])
    resp = bulk(client, url="https://show/feed", language="es")
    assert resp.status_code == 202
    body = resp.get_json()
    assert [(q["record"], q["url"]) for q in body["queued"]] == [("A", "https://c/a.mp3"), ("B", "https://c/b.mp3")]
    assert body["skipped"] == []
    assert calls == [("https://show/feed", 10)]
    assert jobs(db) == [("A", "https://c/a.mp3", "es", None, "queued"), ("B", "https://c/b.mp3", "es", None, "queued")]
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT record, source_url FROM records ORDER BY record;")
            assert cursor.fetchall() == [("A", "https://c/a.mp3"), ("B", "https://c/b.mp3")]


def test_untitled_and_long_titles(client, db, monkeypatch):
    stub(monkeypatch, [{"title": "", "url": "https://c/1.mp3"}, {"title": "x" * 500, "url": "https://c/2.mp3"}])
    queued = bulk(client, url="https://show/feed").get_json()["queued"]
    assert sorted(len(q["record"]) for q in queued) == [9, 200]
    assert any(q["record"] == "Episode 1" for q in queued)


def test_rerun_skips_what_is_already_ingested(client, db, monkeypatch):
    entries = [{"title": "A", "url": "https://c/a.mp3"}, {"title": "B", "url": "https://c/b.mp3"}]
    stub(monkeypatch, entries)
    assert len(bulk(client, url="https://show/feed").get_json()["queued"]) == 2
    entries.append({"title": "C", "url": "https://c/c.mp3"})
    body = bulk(client, url="https://show/feed").get_json()
    assert [q["record"] for q in body["queued"]] == ["C"]
    assert {s["reason"] for s in body["skipped"]} == {"already ingested"}
    assert len(jobs(db)) == 3


def test_label_clash_with_different_url_is_skipped(client, db, monkeypatch):
    stub(monkeypatch, [{"title": "Same", "url": "https://c/1.mp3"}, {"title": "Same", "url": "https://c/2.mp3"}])
    body = bulk(client, url="https://show/feed").get_json()
    assert len(body["queued"]) == 1
    assert body["skipped"] == [{"record": "Same", "reason": "label already exists"}]


def test_entries_belong_to_the_viewer(client, db, monkeypatch):
    stub(monkeypatch, [{"title": "A", "url": "https://c/a.mp3"}])
    headers = login(client, "a@example.com")
    assert bulk(client, headers, url="https://show/feed").status_code == 202
    # an anonymous caller does not see the owned record, so it queues its own
    assert bulk(client, url="https://show/feed").status_code == 202
    owners = [row[3] for row in jobs(db)]
    assert len(owners) == 2 and None in owners and any(o is not None for o in owners)


def test_failed_job_insert_releases_the_label(client, db, monkeypatch):
    import routes
    stub(monkeypatch, [{"title": "A", "url": "https://c/a.mp3"}, {"title": "B", "url": "https://c/b.mp3"}])
    # the same job id twice: the second insert violates the primary key
    monkeypatch.setattr(routes.uuid, "uuid4", lambda: "11111111-1111-1111-1111-111111111111")
    body = bulk(client, url="https://show/feed").get_json()
    assert [q["record"] for q in body["queued"]] == ["A"]
    assert body["skipped"] == [{"record": "B", "reason": "could not be queued"}]
    failed = "B"
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT record FROM records;")
            assert failed not in [r[0] for r in cursor.fetchall()]


@pytest.mark.parametrize("body", [{}, {"url": ""}, {"url": 5}, {"url": "https://x", "limit": 0}, {"url": "https://x", "limit": 26},
                                  {"url": "https://x", "limit": "3"}, {"url": "https://x", "limit": True},
                                  {"url": "https://x", "language": "klingon"}])
def test_validation_errors_are_400(client, monkeypatch, body):
    stub(monkeypatch, [{"title": "A", "url": "https://c/a.mp3"}])
    assert bulk(client, **body).status_code == 400


def test_non_object_body_is_400(client):
    assert client.post("/api/ingest/bulk", data="[1]", content_type="application/json").status_code == 400


def test_private_url_is_400_and_unreadable_feed_is_502(client, monkeypatch):
    assert bulk(client, url="http://127.0.0.1/feed").status_code == 400

    def broken(url, limit):
        raise feeds.FeedError("Could not fetch the feed: boom")

    monkeypatch.setattr(feeds, "list_entries", broken)
    resp = bulk(client, url="https://show/feed")
    assert resp.status_code == 502 and "boom" in resp.get_json()["error"]


def test_empty_feed_is_422(client, monkeypatch):
    stub(monkeypatch, [])
    assert bulk(client, url="https://show/feed").status_code == 422


def test_bad_token_is_401(client):
    assert bulk(client, {"Authorization": "Bearer nope"}, url="https://x").status_code == 401


def test_quota_exhausted_is_402_and_nothing_is_fetched_or_queued(client, db, monkeypatch):
    calls = stub(monkeypatch, [{"title": "A", "url": "https://c/a.mp3"}])
    headers = login(client, "q@example.com")
    monkeypatch.setenv("FREE_TIER_MINUTES", "1")
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM users;")
            uid = cursor.fetchone()[0]
            cursor.execute("INSERT INTO records (record, video_id, user_id) VALUES ('old', 'v-old', %s);", (uid,))
            cursor.execute(
                "INSERT INTO jobs (id, record, url, video_id, user_id, status, audio_seconds) "
                "VALUES ('j-old', 'old', 'u', 'v-old', %s, 'done', 120);", (uid,))
    resp = bulk(client, headers, url="https://show/feed")
    assert resp.status_code == 402 and resp.get_json()["remaining_seconds"] == 0
    assert calls == []
    assert len(jobs(db)) == 1


def test_rate_limited_once_per_call(client, db, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_INGEST_PER_MIN", "1")
    stub(monkeypatch, [{"title": "A", "url": "https://c/a.mp3"}, {"title": "B", "url": "https://c/b.mp3"}])
    assert bulk(client, url="https://show/feed").status_code == 202
    resp = bulk(client, url="https://show/feed")
    assert resp.status_code == 429 and "Retry-After" in resp.headers
