"""Multi-word keywords match consecutive words, in order (phrase.py)."""
import os

import pytest

import phrase


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    import routes
    routes.app.config["TESTING"] = True
    return routes.app.test_client()


def seed(db, words, video_id="vid-1", record="ep", segments=None, speakers=None):
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
                    VALUES (%s, %s, %s, '', %s, %s, %s, %s);
                    """,
                    (
                        video_id, record, segments[i] if segments else 0, word,
                        float(i), float(i) + 1, speakers[i] if speakers else "SPEAKER_00",
                    ),
                )


def search(client, keyword, record="ep"):
    return client.post("/api/search", json={"record": record, "keyword": keyword})


def hits(resp):
    assert resp.status_code == 200, resp.get_json()
    return [(r["word"], r["start"], r["end"], r["speaker"]) for r in resp.get_json()["results"]]


def test_phrase_matches_consecutive_words(client, db):
    seed(db, [" the", " quick", " brown", " fox"])
    assert hits(search(client, "quick brown")) == [("quick brown", 1.0, 3.0, "SPEAKER_00")]


def test_words_must_be_adjacent_and_in_order(client, db):
    seed(db, [" quick", " red", " brown", " brown", " quick"])
    assert hits(search(client, "quick brown")) == []
    assert hits(search(client, "brown quick")) == [("brown quick", 3.0, 5.0, "SPEAKER_00")]


def test_every_occurrence_is_returned_in_order(client, db):
    seed(db, [" so", " it", " goes", " it", " goes", " on", " it", " goes"])
    assert hits(search(client, "it goes")) == [
        ("it goes", 1.0, 3.0, "SPEAKER_00"),
        ("it goes", 3.0, 5.0, "SPEAKER_00"),
        ("it goes", 6.0, 8.0, "SPEAKER_00"),
    ]


def test_overlapping_occurrences_are_both_found(client, db):
    seed(db, [" a", " a", " a"])
    assert [h[1] for h in hits(search(client, "a a"))] == [0.0, 1.0]


def test_case_punctuation_and_spacing_are_ignored(client, db):
    seed(db, [" Hello,", " “World!”", " again."])
    assert hits(search(client, "  HELLO,   world ")) == [("Hello, “World!”", 0.0, 2.0, "SPEAKER_00")]
    assert hits(search(client, "world again")) == [("“World!” again.", 1.0, 3.0, "SPEAKER_00")]


def test_punctuation_only_tokens_are_skipped_on_both_sides(client, db):
    seed(db, [" wait", " —", " what", " no", " ...", " way"])
    assert [h[1] for h in hits(search(client, "wait what"))] == [0.0]
    assert [h[1] for h in hits(search(client, "no way"))] == [3.0]
    # A dash typed into the keyword is dropped, leaving the plain phrase.
    assert [h[1] for h in hits(search(client, "wait — what"))] == [0.0]
    assert [h[1] for h in hits(search(client, "no ... way"))] == [3.0]


def test_phrase_can_span_segments(client, db):
    seed(db, [" end", " of", " one", " start", " of", " two"], segments=[0, 0, 0, 1, 1, 1])
    assert hits(search(client, "one start")) == [("one start", 2.0, 4.0, "SPEAKER_00")]


def test_speaker_comes_from_the_first_word(client, db):
    seed(db, [" hi", " there"], speakers=["SPEAKER_01", "SPEAKER_02"])
    assert hits(search(client, "hi there")) == [("hi there", 0.0, 2.0, "SPEAKER_01")]


def test_single_word_is_returned_as_stored(client, db):
    seed(db, [" Hello,", " world"])
    assert hits(search(client, "hello")) == [(" Hello,", 0.0, 1.0, "SPEAKER_00")]


def test_unmatched_and_symbol_only_phrases_return_nothing(client, db):
    seed(db, [" hello", " world"])
    assert hits(search(client, "hello there")) == []
    assert hits(search(client, "world hello")) == []
    assert hits(search(client, "— ...")) == []


def test_regex_metacharacters_in_a_phrase_are_plain_text(client, db):
    seed(db, [" a.b", " c(d"])
    assert [h[1] for h in hits(search(client, "a.b c(d"))] == [0.0]
    assert hits(search(client, "a.* .*")) == []


def test_phrase_is_scoped_to_its_video(client, db):
    seed(db, [" go", " now"], video_id="vid-a", record="a")
    seed(db, [" go", " later", " go", " now"], video_id="vid-b", record="b")
    assert [h[1] for h in hits(search(client, "go now", record="a"))] == [0.0]
    assert [h[1] for h in hits(search(client, "go now", record="b"))] == [2.0]


def test_phrase_longer_than_the_limit_is_a_400(client, db):
    seed(db, [" a"])
    ok = " ".join(["a"] * phrase.MAX_PHRASE_WORDS)
    assert search(client, ok).status_code == 200
    resp = search(client, ok + " a")
    assert resp.status_code == 400
    assert str(phrase.MAX_PHRASE_WORDS) in resp.get_json()["error"]


def test_phrase_at_the_limit_matches(client, db):
    words = [f" w{i}" for i in range(phrase.MAX_PHRASE_WORDS + 2)]
    seed(db, words)
    keyword = " ".join(w.strip() for w in words[1:phrase.MAX_PHRASE_WORDS + 1])
    assert [h[1] for h in hits(search(client, keyword))] == [1.0]


def test_ordered_walk_uses_the_order_index(db):
    seed(db, [" hello", " world"])
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET enable_seqscan = off;")
            cursor.execute(
                """
                EXPLAIN SELECT id FROM transcripts
                WHERE video_id = 'vid-1' AND word_norm <> '' AND (start_time, id) > (0.0, 1)
                ORDER BY start_time, id LIMIT 1;
                """
            )
            plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "idx_transcripts_video_order" in plan, plan
    assert "Sort" not in plan, plan
