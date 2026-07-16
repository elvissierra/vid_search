from contextlib import contextmanager

import environ
import psycopg2.pool

env = environ.Env()
environ.Env.read_env()

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(
            1, 10,
            dbname=env("DB_NAME"),
            user=env("DB_USER"),
            password=env("DB_PASSWORD"),
            host=env("DB_HOST"),
            port=env("DB_PORT", default="5432"),
        )
    return _pool


@contextmanager
def get_conn():
    """Pooled connection; commits on clean exit, rolls back on exception."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
