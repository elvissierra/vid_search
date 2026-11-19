"""POST /api/search/all searches every record the viewer can see."""
import os

import pytest


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


def seed(db, record, video_id, words, user_id=None):
    """Insert a record and its `words` (as whisper emits them), one second each."""
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO records (record, video_id, user_id) VALUES (%s, %s, %s);",
                (record, video_id, user_id),
            )
            for i, word in enumerate(words):
                cursor.execute(
                    """
                    INSERT INTO transcripts
                        (video_id, record, segment_index, segment_text, word, start_time, end_time, speaker)
                    VALUES (%s, %s, 0, '', %s, %s, %s, 'SPEAKER_00');
                    """,
                    (video_id, record, word, float(i), float(i) + 1),
                )


def search_all(client, headers=None, **body):
    return client.post("/api/search/all", json=body, headers=headers or {})


def hits(resp):
    assert resp.status_code == 200, resp.get_json()
    return [(r["record"], r["word"], r["start"]) for r in resp.get_json()["results"]]


def test_finds_hits_across_records_in_label_order(client, db):
    seed(db, "zeta", "v-z", [" the", " fox"])
    seed(db, "alpha", "v-a", [" fox", " and", " fox"])
    seed(db, "mid", "v-m", [" no", " match"])
    resp = search_all(client, keyword="fox")
    assert hits(resp) == [("alpha", " fox", 0.0), ("alpha", " fox", 2.0), ("zeta", " fox", 1.0)]
    body = resp.get_json()
    assert body["keyword"] == "fox"
    assert body["truncated"] is False
    assert body["results"][0]["video_id"] == "v-a"
    assert body["results"][0]["speaker"] == "SPEAKER_00"


def test_phrase_matches_stay_inside_one_recording(client, db):
    # "quick" ends one record and "brown" starts the next: not a phrase hit
    seed(db, "a", "v-a", [" the", " quick"])
    seed(db, "b", "v-b", [" brown", " fox"])
    seed(db, "c", "v-c", [" a", " quick", " brown", " dog"])
    assert hits(search_all(client, keyword="Quick, brown")) == [("c", "quick brown", 1.0)]


def test_no_hits_and_no_records(client, db):
    assert search_all(client, keyword="fox").get_json() == {
        "keyword": "fox", "results": [], "truncated": False,
    }
    seed(db, "a", "v-a", [" hello"])
    assert hits(search_all(client, keyword="goodbye")) == []
    assert hits(search_all(client, keyword="...")) == []


def test_limit_truncates_and_reports_it(client, db):
    seed(db, "a", "v-a", [" go"] * 3)
    seed(db, "b", "v-b", [" go"] * 3)
    resp = search_all(client, keyword="go", limit=4)
    assert [(r["record"], r["start"]) for r in resp.get_json()["results"]] == [
        ("a", 0.0), ("a", 1.0), ("a", 2.0), ("b", 0.0),
    ]
    assert resp.get_json()["truncated"] is True
    exact = search_all(client, keyword="go", limit=6).get_json()
    assert len(exact["results"]) == 6 and exact["truncated"] is False


def test_anonymous_sees_only_unowned_records(client, db):
    ess = login(client, "ess@example.com")
    seed(db, "mine", "v-mine", [" fox"], user_id=user_id(client, ess))
    seed(db, "old", "v-old", [" fox"])
    assert hits(search_all(client, keyword="fox")) == [("old", " fox", 0.0)]


def test_logged_in_user_sees_only_their_own_records(client, db):
    ess = login(client, "ess@example.com")
    sam = login(client, "sam@example.com")
    seed(db, "ep", "v-ess", [" fox"], user_id=user_id(client, ess))
    seed(db, "ep", "v-sam", [" fox", " fox"], user_id=user_id(client, sam))
    seed(db, "old", "v-old", [" fox"])
    assert [h[0] for h in hits(search_all(client, ess, keyword="fox"))] == ["ep"]
    resp = search_all(client, sam, keyword="fox").get_json()
    assert {r["video_id"] for r in resp["results"]} == {"v-sam"}
    assert len(resp["results"]) == 2


def test_invalid_token_is_401_not_anonymous(client, db):
    seed(db, "old", "v-old", [" fox"])
    resp = search_all(client, {"Authorization": "Bearer nope"}, keyword="fox")
    assert resp.status_code == 401


@pytest.mark.parametrize("body", [
    {}, {"keyword": None}, {"keyword": ""}, {"keyword": "   "}, {"keyword": 7}, {"keyword": ["a"]},
])
def test_keyword_is_required(client, db, body):
    assert search_all(client, **body).status_code == 400


def test_non_object_body_is_400(client, db):
    resp = client.post("/api/search/all", json=["fox"])
    assert resp.status_code == 400
    assert client.post("/api/search/all", data="nope").status_code == 400


def test_phrase_word_limit(client, db):
    import phrase
    ok = " ".join(["a"] * phrase.MAX_PHRASE_WORDS)
    assert search_all(client, keyword=ok).status_code == 200
    assert search_all(client, keyword=ok + " a").status_code == 400


@pytest.mark.parametrize("limit", [0, -1, 501, "5", 1.5, True, None])
def test_bad_limit_is_400(client, db, limit):
    assert search_all(client, keyword="fox", limit=limit).status_code == 400


def test_counts_against_the_search_rate_limit(client, db, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SEARCH_PER_MIN", "2")
    assert search_all(client, keyword="fox").status_code == 200
    assert search_all(client, keyword="fox").status_code == 200
    resp = search_all(client, keyword="fox")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_never_queues_a_job(client, db):
    seed(db, "a", "v-a", [" fox"])
    search_all(client, keyword="fox")
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM jobs;")
            assert cursor.fetchone()[0] == 0
