"""Usage ledger and the free-tier quota.

Usage is the sum of audio_seconds over a user's jobs in the current calendar
month (UTC), read from the usage_ledger view. The quota is checked when a job
is enqueued: a user who has already used up the month is refused. The length
of a new file is not known until the worker transcribes it, so one job can
carry a user past the limit, and concurrent enqueues can overshoot by the
same margin; the check stops the *next* job, it is not a hard cap.

Only logged-in users are metered. Anonymous requests (the pre-accounts
rows) are unmetered.
"""
import os
from datetime import datetime, timezone

from db import get_conn

DEFAULT_FREE_TIER_MINUTES = 60


def free_tier_seconds():
    """Monthly allowance in seconds from FREE_TIER_MINUTES (default 60)."""
    return float(os.environ.get("FREE_TIER_MINUTES", DEFAULT_FREE_TIER_MINUTES)) * 60


def period_bounds(now=None):
    """(start, end) of the UTC calendar month containing `now`."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 \
        else start.replace(month=start.month + 1)
    return start, end


def usage_summary(user_id, now=None):
    """This month's usage for a user against the free-tier limit."""
    start, end = period_bounds(now)
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(SUM(audio_seconds), 0)
                FROM usage_ledger
                WHERE user_id = %s AND created_at >= %s AND created_at < %s;
                """,
                (user_id, start, end)
            )
            used = float(cursor.fetchone()[0])
    limit = free_tier_seconds()
    return {
        "used_seconds": used,
        "limit_seconds": limit,
        "remaining_seconds": max(limit - used, 0.0),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
    }


def quota_exceeded(user_id):
    """The usage summary if the user has used up the month, else None.

    Anonymous (user_id None) is never over quota.
    """
    if user_id is None:
        return None
    summary = usage_summary(user_id)
    return summary if summary["used_seconds"] >= summary["limit_seconds"] else None
