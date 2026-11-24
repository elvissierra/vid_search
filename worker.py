"""Transcription worker. Run alongside the API: python worker.py

Claims queued jobs from the jobs table (FOR UPDATE SKIP LOCKED), runs the
download -> transcribe -> diarize -> save pipeline, and reports progress.
Models are loaded once at startup.
"""
import logging
import os
import time

import diarize
import logs
import resolver
import vid_search
from db import get_conn

log = logging.getLogger("worker")

POLL_SECONDS = 2
STALE_SWEEP_SECONDS = 600

CLAIM_SQL = """
    UPDATE jobs SET status = 'running', started_at = now(), progress = 5
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued'
        ORDER BY created_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id, record, url, language, upload_path, video_id;
"""


def set_progress(job_id, progress):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE jobs SET progress = %s WHERE id = %s;", (progress, job_id)
            )


def set_audio_seconds(job_id, seconds):
    """Record the transcribed length; this is the usage ledger entry."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE jobs SET audio_seconds = %s WHERE id = %s;", (seconds, job_id)
            )


def finish_job(job_id, status, error=None):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE jobs
                SET status = %s,
                    progress = CASE WHEN %s = 'done' THEN 100 ELSE progress END,
                    error = %s,
                    finished_at = now()
                WHERE id = %s;
                """,
                (status, status, error, job_id)
            )


def requeue_running(only_stale=False):
    """Put running jobs back in the queue. On startup nothing can really be
    running (single worker); the stale variant catches jobs orphaned by a
    crash while another worker keeps serving."""
    condition = "AND started_at < now() - interval '2 hours'" if only_stale else ""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE jobs
                SET status = 'queued', progress = 0, started_at = NULL
                WHERE status = 'running' {condition};
                """
            )
            if cursor.rowcount:
                log.warning("requeued interrupted jobs", extra={"count": cursor.rowcount})


def claim_job():
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(CLAIM_SQL)
            return cursor.fetchone()


def process_job(job):
    job_id, record, url, language, upload_path, video_id = job
    log.info("job started", extra={"job_id": job_id, "record": record})
    started = time.monotonic()
    seconds = {}

    def on_duration(audio_seconds):
        seconds["audio"] = audio_seconds
        set_audio_seconds(job_id, audio_seconds)

    audio_file = None
    try:
        if upload_path:
            audio_file = upload_path
        else:
            audio_file = vid_search.download_video_audio(resolver.resolve_audio_url(url))
        set_progress(job_id, 25)

        vid_search.process_audio(
            audio_file, record, video_id,
            language=language,
            progress_cb=lambda p: set_progress(job_id, p),
            duration_cb=on_duration,
        )
        finish_job(job_id, 'done')
        log.info("job done", extra={
            "job_id": job_id, "record": record, "status": "done",
            "duration_seconds": round(time.monotonic() - started, 2),
            "audio_seconds": seconds.get("audio"),
        })
    except Exception as e:
        # Free the reserved label so the record can be resubmitted.
        vid_search.release_record(record, video_id)
        finish_job(job_id, 'error', error=str(e)[:500])
        log.error("job failed", exc_info=True, extra={
            "job_id": job_id, "record": record, "status": "error",
            "duration_seconds": round(time.monotonic() - started, 2),
            "audio_seconds": seconds.get("audio"),
        })
    finally:
        if audio_file and os.path.exists(audio_file):
            os.remove(audio_file)


def main():
    logs.configure("worker")
    log.info("loading whisper model")
    vid_search.get_model()
    log.info("loading diarization pipeline")
    diarize.get_pipeline()

    requeue_running()
    log.info("worker ready, polling for jobs")

    last_sweep = time.monotonic()
    while True:
        job = claim_job()
        if job:
            process_job(job)
            continue
        if time.monotonic() - last_sweep > STALE_SWEEP_SECONDS:
            requeue_running(only_stale=True)
            last_sweep = time.monotonic()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
