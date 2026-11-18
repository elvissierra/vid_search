"""Keyword lookup runs on the indexed transcripts.word_norm column."""
import os

import pytest


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    import routes
    routes.app.config["TESTING"] = True
    return routes.app.test_client()


def seed(db, words, video_id="vid-1", record="ep"):
    """Insert `words` (as whisper emits them) at one second each."""
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO records (record, video_id) VALUES (%s, %s);", (record, video_id)
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


def search(client, keyword, record="ep"):
    return client.post("/api/search", json={"record": record, "keyword": keyword})


def found(resp):
    assert resp.status_code == 200, resp.get_json()
    return [(r["word"], r["start"]) for r in resp.get_json()["results"]]


@pytest.mark.parametrize("word, expected", [
    (" Hello,", "hello"),
    ("hello", "hello"),
    ("  “Hello!”  ", "hello"),
    (" don't", "don't"),
    (" don’t", "don't"),
    (" 'quoted'", "quoted"),
    (" well-known.", "well-known"),
    (" ¿Qué?", "qué"),
    (" 3.5%", "3.5"),
    (" —", ""),
    (" ...", ""),
])
def test_normalize_word(db, word, expected):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT normalize_word(%s);", (word,))
            assert cursor.fetchone()[0] == expected


def test_stored_words_are_normalized_by_the_database(db):
    seed(db, [" Hello,", " world."])
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT word_norm FROM transcripts ORDER BY start_time;")
            assert [r[0] for r in cursor.fetchall()] == ["hello", "world"]


def test_matches_case_and_punctuation_insensitively(client, db):
    seed(db, [" Hello,", " world", " HELLO!", " hello"])
    assert found(search(client, "hello")) == [(" Hello,", 0.0), (" HELLO!", 2.0), (" hello", 3.0)]
    assert found(search(client, "HeLLo")) == found(search(client, "hello"))
    assert found(search(client, " hello, ")) == found(search(client, "hello"))


def test_matches_whole_words_only(client, db):
    seed(db, [" start", " art", " Art.", " party", " artist"])
    assert found(search(client, "art")) == [(" art", 1.0), (" Art.", 2.0)]


def test_apostrophes_and_hyphens_are_part_of_the_word(client, db):
    seed(db, [" don't", " don’t", " dont", " well-known", " well"])
    assert found(search(client, "don't")) == [(" don't", 0.0), (" don’t", 1.0)]
    assert found(search(client, "well-known")) == [(" well-known", 3.0)]
    assert found(search(client, "well")) == [(" well", 4.0)]


def test_regex_metacharacters_are_plain_text(client, db):
    seed(db, [" a", " b", " c++", " ab"])
    for keyword in ["a(b", "(a+)+b$", ".*", "[", "\\", "a|b"]:
        assert found(search(client, keyword)) == [], keyword


def test_non_ascii_words(client, db):
    seed(db, [" ¿Qué", " pasó?", " año,"])
    assert found(search(client, "qué")) == [(" ¿Qué", 0.0)]
    assert found(search(client, "año")) == [(" año,", 2.0)]


def test_keyword_without_letters_or_digits_matches_nothing(client, db):
    seed(db, [" —", " ...", " hello"])
    for keyword in ["—", "...", "!!!", "  "]:
        assert found(search(client, keyword)) == [], keyword


def test_results_are_ordered_by_start_time_and_scoped_to_the_video(client, db):
    seed(db, [" go", " stop", " go"], video_id="vid-a", record="a")
    seed(db, [" go"], video_id="vid-b", record="b")
    assert found(search(client, "go", record="a")) == [(" go", 0.0), (" go", 2.0)]
    assert found(search(client, "go", record="b")) == [(" go", 0.0)]


@pytest.mark.parametrize("keyword", [5, ["hello"], {"a": 1}, True])
def test_non_string_keyword_is_a_400(client, db, keyword):
    seed(db, [" hello"])
    resp = search(client, keyword)
    assert resp.status_code == 400
    assert "keyword" in resp.get_json()["error"]


def test_lookup_uses_the_word_norm_index(db):
    seed(db, [" hello"])
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET enable_seqscan = off;")
            cursor.execute(
                """
                EXPLAIN SELECT word FROM transcripts
                WHERE video_id = 'vid-1' AND word_norm <> '' AND word_norm = normalize_word('Hello')
                ORDER BY start_time;
                """
            )
            plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "idx_transcripts_video_word_norm" in plan, plan
    assert "Seq Scan" not in plan, plan


def test_superseded_index_is_gone(db):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'transcripts';"
            )
            names = {row[0] for row in cursor.fetchall()}
    assert "idx_transcripts_video_word" not in names
    assert "idx_transcripts_video_word_norm" in names
