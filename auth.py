"""Accounts: password hashing, signup, login, and bearer-token sessions.

Passwords are hashed with scrypt (stdlib, no extra dependency). A login mints
a random token returned once to the client; only its sha256 is stored in
`sessions`, so tokens can be revoked and a database leak cannot be replayed.
"""
import hashlib
import hmac
import os
import re
import secrets

from db import get_conn

SESSION_DAYS = 30
MIN_PASSWORD = 8
MAX_PASSWORD = 128
MAX_EMAIL = 254

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def normalize_email(value):
    """Lowercased, trimmed email, or ValueError if it is not plausible."""
    if not isinstance(value, str):
        raise ValueError("email is required")
    email = value.strip().lower()
    if len(email) > MAX_EMAIL or not _EMAIL.match(email):
        raise ValueError("email is not valid")
    return email


def validate_password(value):
    if not isinstance(value, str) or not value:
        raise ValueError("password is required")
    if len(value) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    if len(value) > MAX_PASSWORD:
        raise ValueError(f"password must be at most {MAX_PASSWORD} characters")
    return value


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), dklen=32,
            n=int(n), r=int(r), p=int(p),
        )
        return hmac.compare_digest(candidate, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


# Verified against when the email is unknown, so login takes the same time
# whether or not the account exists.
_DUMMY_HASH = hash_password("not-a-real-password")


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_user(email, password):
    """Insert a user; returns {id, email}, or None if the email is taken."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (email, password_hash) VALUES (%s, %s)
                ON CONFLICT (email) DO NOTHING
                RETURNING id;
                """,
                (email, hash_password(password)),
            )
            row = cursor.fetchone()
    return {"id": row[0], "email": email} if row else None


def authenticate(email, password):
    """The user dict for valid credentials, else None."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, password_hash FROM users WHERE email = %s;", (email,))
            row = cursor.fetchone()
    stored = row[1] if row else _DUMMY_HASH
    ok = verify_password(password, stored)
    return {"id": row[0], "email": email} if (row and ok) else None


def create_session(user_id):
    """Mint a session; returns the raw token (shown to the client once)."""
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sessions (token_hash, user_id, expires_at)
                VALUES (%s, %s, now() + make_interval(days => %s));
                """,
                (_token_hash(token), user_id, SESSION_DAYS),
            )
    return token


def user_for_token(token):
    """The {id, email} a live token belongs to, else None."""
    if not token:
        return None
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT u.id, u.email FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = %s AND s.expires_at > now();
                """,
                (_token_hash(token),),
            )
            row = cursor.fetchone()
    return {"id": row[0], "email": row[1]} if row else None


def revoke_token(token):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM sessions WHERE token_hash = %s;", (_token_hash(token),))


def bearer_token(header):
    """The token from an `Authorization: Bearer <token>` header value, or None."""
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token else None
