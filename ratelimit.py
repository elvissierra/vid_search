"""Rate limiting for the search and ingest endpoints.

Fixed one-minute windows counted in Postgres (table rate_limits), so the
limit holds across several api processes. Callers are keyed by user id when
logged in and by the connection's remote address otherwise; behind a reverse
proxy every anonymous caller shares the proxy's address unless the proxy
rewrites it (e.g. werkzeug ProxyFix).

Two buckets:
  search  every call to /api/search          RATE_LIMIT_SEARCH_PER_MIN (default 60)
  ingest  anything that queues a new job     RATE_LIMIT_INGEST_PER_MIN (default 10)
A limit of 0 turns that bucket off. Fixed windows allow a burst of up to
twice the limit across a window boundary; that is accepted for simplicity.
"""
import os
import random
from datetime import datetime, timezone

from db import get_conn

WINDOW_SECONDS = 60
DEFAULTS = {"search": 60, "ingest": 10}
ENV_VARS = {"search": "RATE_LIMIT_SEARCH_PER_MIN", "ingest": "RATE_LIMIT_INGEST_PER_MIN"}
PRUNE_CHANCE = 0.01
PRUNE_AFTER_SECONDS = 3600


def limit_for(bucket):
    """Requests per minute for a bucket (0 = unlimited)."""
    return int(os.environ.get(ENV_VARS[bucket], DEFAULTS[bucket]))


def client_key(user_id, remote_addr):
    return f"user:{user_id}" if user_id is not None else f"ip:{remote_addr or 'unknown'}"


def window_start(now):
    return datetime.fromtimestamp(now.timestamp() // WINDOW_SECONDS * WINDOW_SECONDS, timezone.utc)


def check(bucket, key, now=None):
    """Count one request. Returns None if allowed, else seconds until the window resets."""
    limit = limit_for(bucket)
    if limit <= 0:
        return None
    now = now or datetime.now(timezone.utc)
    start = window_start(now)
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO rate_limits (bucket, key, window_start, hits)
                VALUES (%s, %s, %s, 1)
                ON CONFLICT (bucket, key, window_start)
                DO UPDATE SET hits = rate_limits.hits + 1
                RETURNING hits;
                """,
                (bucket, key, start)
            )
            hits = cursor.fetchone()[0]
            if random.random() < PRUNE_CHANCE:
                cursor.execute(
                    "DELETE FROM rate_limits WHERE window_start < %s;",
                    (datetime.fromtimestamp(start.timestamp() - PRUNE_AFTER_SECONDS, timezone.utc),)
                )
    if hits <= limit:
        return None
    return max(1, int(start.timestamp() + WINDOW_SECONDS - now.timestamp()) + 1)
