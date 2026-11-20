"""Segment embeddings, POST /api/search/semantic and the embedding backfill."""
import hashlib
import math
import os

import pytest

import embeddings
import vid_search


def fake_embed(texts):
    """Deterministic bag-of-words vectors: texts sharing words are similar."""
    out = []
    for text in texts:
        vec = [0.0] * embeddings.DIMENSIONS
        for word in text.lower().split():
            word = word.strip(".,!?")
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % embeddings.DIMENSIONS] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        out.append([x / norm for x in vec])
    return out


@pytest.fixture(autouse=True)
def _fake_model(monkeypatch):
    monkeypatch.setattr(embeddings, "embed", fake_embed)


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    monkeypatch.setenv("RATE_LIMIT_SEARCH_PER_MIN", "0")
    import routes
    routes.app.config["TESTING"] = True
    return routes.app.test_client()


def login(client, email):
    resp = client.post("/api/signup", json={"email": email, "password": "hunter2hunter2"})
    return {"Authorization": f"Bearer {resp.get_json()['token']}"}


def user_id(client, headers):
    return client.get("/api/me", headers=headers).get_json()["user"]["id"]


def seed(db, record, video_id, segments, user_id=None):
    """A record with embedded segments: [(text, start, end), ...]."""
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO records (record, video_id, user_id) VALUES (%s, %s, %s);",
                (record, video_id, user_id),
            )
            vectors = fake_embed([text for (text, _, _) in segments])
            embeddings.store(cursor, video_id, [
                (i, text, start, end, vec)
                for i, ((text, start, end), vec) in enumerate(zip(segments, vectors))
            ])


def ask(client, query, headers=None, **extra):
    return client.post("/api/search/semantic", json={"query": query, **extra}, headers=headers or {})


def test_ranks_by_similarity(client, db):
    seed(db, "talk", "v1", [
        ("the quarterly budget was approved", 0.0, 4.0),
        ("we adopted a rescue dog last week", 4.0, 8.0),
        ("dog training takes patience", 8.0, 12.0),
    ])
    resp = ask(client, "rescue dog")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["query"] == "rescue dog"
    texts = [r["text"] for r in body["results"]]
    assert texts[0] == "we adopted a rescue dog last week"
    assert texts[1] == "dog training takes patience"
    assert texts[-1] == "the quarterly budget was approved"
    scores = [r["score"] for r in body["results"]]
    assert scores == sorted(scores, reverse=True)
    top = body["results"][0]
    assert top["record"] == "talk" and top["video_id"] == "v1"
    assert (top["start"], top["end"]) == (4.0, 8.0)
    expected = sum(a * b for a, b in zip(*fake_embed(["rescue dog", "we adopted a rescue dog last week"])))
    assert top["score"] == pytest.approx(expected, abs=1e-6)


def test_searches_across_records_and_limits(client, db):
    seed(db, "a", "va", [("cats and dogs", 0.0, 1.0), ("tax forms", 1.0, 2.0)])
    seed(db, "b", "vb", [("dogs bark loudly", 0.0, 1.0)])
    body = ask(client, "dogs").get_json()
    assert {r["record"] for r in body["results"][:2]} == {"a", "b"}
    assert len(body["results"]) == 3
    assert len(ask(client, "dogs", limit=1).get_json()["results"]) == 1


def test_scoped_to_viewer(client, db):
    alice = login(client, "alice@example.com")
    bob = login(client, "bob@example.com")
    seed(db, "pub", "v0", [("secret recipe for soup", 0.0, 1.0)])
    seed(db, "alice-rec", "va", [("secret recipe for soup", 0.0, 1.0)], user_id(client, alice))

    anon = ask(client, "secret recipe").get_json()["results"]
    assert [r["record"] for r in anon] == ["pub"]
    mine = ask(client, "secret recipe", headers=alice).get_json()["results"]
    assert [r["record"] for r in mine] == ["alice-rec"]
    assert ask(client, "secret recipe", headers=bob).get_json()["results"] == []


def test_bad_token_is_401(client, db):
    assert ask(client, "x", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_empty_library_returns_no_results(client, db):
    resp = ask(client, "anything")
    assert resp.status_code == 200
    assert resp.get_json()["results"] == []


@pytest.mark.parametrize("body", [
    {}, {"query": ""}, {"query": "   "}, {"query": 5}, {"query": ["a"]},
    {"query": "x" * 501},
    {"query": "ok", "limit": 0}, {"query": "ok", "limit": 51}, {"query": "ok", "limit": "5"},
    {"query": "ok", "limit": True}, {"query": "ok", "limit": 2.5},
])
def test_validation(client, db, body):
    assert client.post("/api/search/semantic", json=body).status_code == 400


def test_non_json_body_is_400(client, db):
    assert client.post("/api/search/semantic", data="nope").status_code == 400


def test_rate_limited(client, db, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SEARCH_PER_MIN", "1")
    assert ask(client, "a").status_code == 200
    resp = ask(client, "a")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_never_queues_a_job(client, db):
    ask(client, "hello")
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM jobs;")
            assert cursor.fetchone()[0] == 0


def test_model_failure_is_500(client, db, monkeypatch):
    def boom(_texts):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(embeddings, "embed", boom)
    assert ask(client, "hello").status_code == 500


def test_vector_literal_checks_dimensions():
    with pytest.raises(ValueError):
        embeddings.vector_literal([0.1, 0.2])


# --- writing embeddings from process_audio ---------------------------------

class FakeWhisper:
    def transcribe(self, audio_file, word_timestamps, language):
        return {"segments": [
            {"text": " hello brave world", "start": 0.0, "end": 2.0,
             "words": [{"word": " hello", "start": 0.0, "end": 0.5},
                       {"word": " brave", "start": 0.5, "end": 1.0},
                       {"word": " world", "start": 1.0, "end": 2.0}]},
            {"text": "   ", "start": 2.0, "end": 3.0, "words": []},
            {"text": " goodbye moon", "start": 3.0, "end": 5.0,
             "words": [{"word": " goodbye", "start": 3.0, "end": 4.0},
                       {"word": " moon", "start": 4.0, "end": 5.0}]},
        ]}


@pytest.fixture
def pipeline(db, monkeypatch):
    monkeypatch.setattr(vid_search, "get_model", lambda: FakeWhisper())
    monkeypatch.setattr(vid_search.diarize, "diarize", lambda _f: [])
    monkeypatch.setattr(vid_search.diarize, "assign_speaker", lambda *_a: "SPEAKER_00")
    return db


def stored(db):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT segment_index, text, start_time, end_time FROM segment_embeddings ORDER BY segment_index;"
            )
            return cursor.fetchall()


def test_process_audio_embeds_each_nonempty_segment(pipeline):
    vid_search.process_audio("a.mp3", "r", "vid")
    assert stored(pipeline) == [
        (0, "hello brave world", 0.0, 2.0),
        (2, "goodbye moon", 3.0, 5.0),
    ]


def test_embedding_failure_does_not_fail_the_job(pipeline, monkeypatch):
    def boom(_texts):
        raise RuntimeError("no model")
    monkeypatch.setattr(embeddings, "embed", boom)
    vid_search.process_audio("a.mp3", "r", "vid")
    assert stored(pipeline) == []
    with pipeline() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM transcripts WHERE video_id = 'vid';")
            assert cursor.fetchone()[0] == 5


def test_backfill_embeds_missing_segments_once(pipeline, monkeypatch):
    def boom(_texts):
        raise RuntimeError("no model")
    monkeypatch.setattr(embeddings, "embed", boom)
    vid_search.process_audio("a.mp3", "r", "vid")
    monkeypatch.setattr(embeddings, "embed", fake_embed)

    assert embeddings.backfill(pipeline) == 2
    assert [row[:2] for row in stored(pipeline)] == [(0, "hello brave world"), (2, "goodbye moon")]
    assert embeddings.backfill(pipeline) == 0


def test_migration_creates_table_without_ann_index(db):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'segment_embeddings';")
            defs = [row[0] for row in cursor.fetchall()]
    assert len(defs) == 1 and "UNIQUE" in defs[0]
    assert not any("hnsw" in d or "ivfflat" in d for d in defs)
