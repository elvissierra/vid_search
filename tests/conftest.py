"""Shared fixtures for db-backed tests.

These run against a real Postgres (FOR UPDATE SKIP LOCKED and ON CONFLICT
cannot be meaningfully mocked). Point DB_NAME/DB_USER/DB_HOST at a throwaway
database; the schema is applied once per session via migrate.main().
Without DB_NAME set, the db-marked tests are skipped.
"""
import os

import pytest


@pytest.fixture(scope="session")
def _schema():
    if not os.environ.get("DB_NAME"):
        pytest.skip("DB_NAME not set; db-backed tests need a postgres database")
    import migrate
    migrate.main()


@pytest.fixture
def db(_schema):
    """A clean database for one test: tables emptied before it runs."""
    from db import get_conn
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("TRUNCATE jobs, records, transcripts;")
    return get_conn
