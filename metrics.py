"""Job queue metrics, read straight from the jobs table."""

WINDOW_HOURS = 24


def job_metrics(cursor):
    """Queue depth, backlog age and the last day's throughput.

    `oldest_queued_age_seconds` is the number to alert on: if it keeps growing
    while jobs are queued, the worker is down or stuck.
    """
    cursor.execute("SELECT status, count(*) FROM jobs GROUP BY status;")
    by_status = {"queued": 0, "running": 0, "done": 0, "error": 0}
    by_status.update({status: count for status, count in cursor.fetchall()})

    cursor.execute(
        "SELECT EXTRACT(EPOCH FROM now() - min(created_at)) FROM jobs WHERE status = 'queued';"
    )
    oldest = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT count(*) FILTER (WHERE status = 'done'),
               count(*) FILTER (WHERE status = 'error'),
               avg(EXTRACT(EPOCH FROM finished_at - started_at))
                   FILTER (WHERE status = 'done' AND started_at IS NOT NULL),
               COALESCE(sum(audio_seconds), 0)
        FROM jobs
        WHERE finished_at >= now() - make_interval(hours => %s);
        """,
        (WINDOW_HOURS,),
    )
    done, failed, avg_seconds, audio_seconds = cursor.fetchone()

    return {
        "jobs": by_status,
        "oldest_queued_age_seconds": None if oldest is None else round(float(oldest), 1),
        "window_hours": WINDOW_HOURS,
        "finished_in_window": {
            "done": done,
            "error": failed,
            "avg_processing_seconds": None if avg_seconds is None else round(float(avg_seconds), 1),
            "audio_seconds": round(float(audio_seconds), 1),
        },
    }
