"""Accounts: password hashing, signup, login, sessions."""
import os

import pytest

import auth


def test_hash_is_salted_and_verifies():
    a, b = auth.hash_password("correct horse"), auth.hash_password("correct horse")
    assert a != b
    assert auth.verify_password("correct horse", a)
    assert not auth.verify_password("wrong horse", a)


@pytest.mark.parametrize("stored", ["", "garbage", "bcrypt$1$2$3$aa$bb", "scrypt$x$8$1$zz$zz"])
def test_verify_rejects_malformed_hashes(stored):
    assert not auth.verify_password("anything", stored)


@pytest.mark.parametrize("value, expected", [
    ("  Ess@Example.COM ", "ess@example.com"),
    ("a@b.co", "a@b.co"),
])
def test_normalize_email(value, expected):
    assert auth.normalize_email(value) == expected


@pytest.mark.parametrize("value", [None, 5, "", "nope", "a@b", "a b@c.com", "@x.com", "a@" + "b" * 260 + ".com"])
def test_normalize_email_rejects(value):
    with pytest.raises(ValueError):
        auth.normalize_email(value)


@pytest.mark.parametrize("value", [None, 12345678, "", "short", "x" * 129])
def test_validate_password_rejects(value):
    with pytest.raises(ValueError):
        auth.validate_password(value)


@pytest.mark.parametrize("header, expected", [
    ("Bearer abc", "abc"), ("bearer abc", "abc"), ("Bearer  abc ", "abc"),
    ("Basic abc", None), ("Bearer", None), ("Bearer ", None), ("", None), (None, None),
])
def test_bearer_token(header, expected):
    assert auth.bearer_token(header) == expected


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", os.environ.get("CORS_ORIGINS", "http://localhost:5173"))
    import routes
    routes.app.config["TESTING"] = True
    return routes.app.test_client()


def signup(client, email="ess@example.com", password="hunter2hunter2"):
    return client.post("/api/signup", json={"email": email, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def count(db, sql, params=()):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()[0]


def test_signup_returns_user_and_a_working_token(client):
    resp = signup(client, email=" Ess@Example.com ")
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["user"]["email"] == "ess@example.com"
    me = client.get("/api/me", headers=bearer(body["token"]))
    assert me.status_code == 200
    assert me.get_json() == {"user": body["user"]}


def test_password_and_token_are_not_stored_in_the_clear(client, db):
    body = signup(client, password="hunter2hunter2").get_json()
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT password_hash FROM users;")
            stored = cursor.fetchone()[0]
            cursor.execute("SELECT token_hash FROM sessions;")
            token_hash = cursor.fetchone()[0]
    assert "hunter2hunter2" not in stored and stored.startswith("scrypt$")
    assert body["token"] != token_hash and body["token"] not in token_hash


def test_duplicate_email_is_409_case_insensitively(client, db):
    assert signup(client).status_code == 201
    resp = signup(client, email="ESS@example.com")
    assert resp.status_code == 409
    assert count(db, "SELECT count(*) FROM users;") == 1


@pytest.mark.parametrize("body", [
    {}, {"email": "ess@example.com"}, {"password": "hunter2hunter2"},
    {"email": "not-an-email", "password": "hunter2hunter2"},
    {"email": "ess@example.com", "password": "short"},
])
def test_signup_validation_creates_nothing(client, db, body):
    assert client.post("/api/signup", json=body).status_code == 400
    assert count(db, "SELECT count(*) FROM users;") == 0


def test_signup_without_json_is_400(client):
    assert client.post("/api/signup", data="x").status_code == 400


def test_login_issues_a_fresh_session(client, db):
    first = signup(client).get_json()
    resp = client.post("/api/login", json={"email": "ESS@example.com", "password": "hunter2hunter2"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["user"] == first["user"]
    assert body["token"] != first["token"]
    assert count(db, "SELECT count(*) FROM sessions;") == 2


@pytest.mark.parametrize("creds", [
    {"email": "ess@example.com", "password": "wrong-password"},
    {"email": "nobody@example.com", "password": "hunter2hunter2"},
    {"email": "ess@example.com"},
    {"email": 5, "password": ["x"]},
    {},
])
def test_bad_login_is_401_with_one_message(client, creds):
    signup(client)
    resp = client.post("/api/login", json=creds)
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "Invalid email or password"}


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"},
])
def test_me_requires_a_valid_token(client, headers):
    signup(client)
    assert client.get("/api/me", headers=headers).status_code == 401


def test_expired_session_is_rejected(client, db):
    token = signup(client).get_json()["token"]
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE sessions SET expires_at = now() - interval '1 second';")
    assert client.get("/api/me", headers=bearer(token)).status_code == 401


def test_logout_revokes_only_that_token(client, db):
    token = signup(client).get_json()["token"]
    other = client.post("/api/login", json={"email": "ess@example.com", "password": "hunter2hunter2"}).get_json()["token"]
    assert client.post("/api/logout", headers=bearer(token)).status_code == 204
    assert client.get("/api/me", headers=bearer(token)).status_code == 401
    assert client.get("/api/me", headers=bearer(other)).status_code == 200
    assert client.post("/api/logout", headers=bearer(token)).status_code == 401
    assert client.post("/api/logout").status_code == 401


def test_sessions_are_removed_with_their_user(client, db):
    signup(client)
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM users;")
    assert count(db, "SELECT count(*) FROM sessions;") == 0


def test_email_check_constraint_blocks_mixed_case_rows(db):
    import psycopg2
    with pytest.raises(psycopg2.errors.CheckViolation):
        with db() as conn:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO users (email, password_hash) VALUES ('A@B.co', 'x');")
