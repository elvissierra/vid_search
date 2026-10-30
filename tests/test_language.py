"""Language hint on /api/search: normalization and what gets queued."""
import os
import sys

import pytest

import languages


@pytest.mark.parametrize("value, expected", [
    ("es", "es"),
    ("ES", "es"),
    (" fr ", "fr"),
    ("Spanish", "es"),
    ("castilian", "es"),
    ("Mandarin", "zh"),
    ("auto", None),
    ("AUTO", None),
    ("", None),
    ("   ", None),
    (None, None),
])
def test_normalize_language(value, expected):
    assert languages.normalize_language(value) == expected


@pytest.mark.parametrize("value", ["xx", "klingon", "english-us", 5, ["en"], {}])
def test_normalize_language_rejects_unsupported(value):
    with pytest.raises(ValueError):
        languages.normalize_language(value)


def test_language_table_is_whisper_sized_and_consistent():
    assert len(languages.LANGUAGES) == 100
    assert all(code == code.lower() for code in languages.LANGUAGES)
    assert set(languages.ALIASES.values()) <= set(languages.LANGUAGES)


def test_languages_module_does_not_import_whisper():
    assert "whisper" not in sys.modules


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    import routes
    routes.app.config["TESTING"] = True
    return routes.app.test_client()


def jobs(db):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT record, language FROM jobs ORDER BY created_at;")
            return cursor.fetchall()


def test_language_is_stored_on_the_queued_job(client, db):
    resp = client.post("/api/search", json={
        "url": "http://example.com/v", "record": "spanish talk", "language": "Spanish"})
    assert resp.status_code == 202
    assert jobs(db) == [("spanish talk", "es")]


@pytest.mark.parametrize("language", [None, "", "auto"])
def test_missing_or_auto_language_queues_null(client, db, language):
    body = {"url": "http://example.com/v", "record": "detect me"}
    if language is not None:
        body["language"] = language
    assert client.post("/api/search", json=body).status_code == 202
    assert jobs(db) == [("detect me", None)]


def test_unsupported_language_is_rejected_without_side_effects(client, db):
    resp = client.post("/api/search", json={
        "url": "http://example.com/v", "record": "bad lang", "language": "klingon"})
    assert resp.status_code == 400
    assert "klingon" in resp.get_json()["error"]
    assert jobs(db) == []
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM records;")
            assert cursor.fetchone()[0] == 0
