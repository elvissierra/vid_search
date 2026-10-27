"""db-backed tests for the job queue (worker.py) and record reservation."""
import threading
import uuid

import pytest

import vid_search
import worker


def insert_job(db, record, status="queued", created_offset_s=0, started_offset_s=None):
    """Insert a job; created_offset_s orders jobs (smaller = older)."""
    job_id = str(uuid.uuid4())
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO jobs (id, status, record, url, video_id, created_at, started_at)
                VALUES (%s, %s, %s, 'http://x', %s,
                        now() + make_interval(secs => %s),
                        CASE WHEN %s::float IS NULL THEN NULL
                             ELSE now() + make_interval(secs => %s) END);
                """,
                (job_id, status, record, str(uuid.uuid4()), created_offset_s,
                 started_offset_s, started_offset_s),
            )
    return job_id


def job_row(db, job_id):
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status, progress, error, started_at, finished_at FROM jobs WHERE id = %s;",
                (job_id,),
            )
            return cursor.fetchone()


def run_concurrently(fn, count):
    """Run fn(i) on `count` threads released together; return results in order."""
    barrier = threading.Barrier(count)
    results = [None] * count
    errors = []

    def runner(i):
        try:
            barrier.wait()
            results[i] = fn(i)
        except Exception as e:  # surfaced below so a thread failure fails the test
            errors.append(e)

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    return results


# --- claim_job ---------------------------------------------------------------

def test_claim_returns_none_when_queue_empty(db):
    assert worker.claim_job() is None


def test_claim_takes_oldest_first_and_marks_running(db):
    newer = insert_job(db, "newer", created_offset_s=10)
    older = insert_job(db, "older", created_offset_s=-10)

    job = worker.claim_job()

    assert job[0] == older
    status, progress, _, started_at, _ = job_row(db, older)
    assert (status, progress) == ("running", 5)
    assert started_at is not None
    assert job_row(db, newer)[0] == "queued"


def test_claim_ignores_non_queued_jobs(db):
    for status in ("running", "done", "error"):
        insert_job(db, f"r-{status}", status=status)
    assert worker.claim_job() is None


def test_claim_returns_columns_in_process_job_order(db):
    job_id = insert_job(db, "label")
    job_id_, record, url, language, upload_path, video_id = worker.claim_job()
    assert (job_id_, record, url) == (job_id, "label", "http://x")
    assert language is None and upload_path is None and video_id


def test_concurrent_claims_never_hand_out_the_same_job(db):
    ids = {insert_job(db, f"r{i}") for i in range(8)}

    claimed = run_concurrently(lambda i: worker.claim_job(), 8)

    claimed_ids = [job[0] for job in claimed if job]
    assert len(claimed_ids) == len(set(claimed_ids)) == 8
    assert set(claimed_ids) == ids


def test_concurrent_claims_on_fewer_jobs_than_workers(db):
    insert_job(db, "a")
    insert_job(db, "b")

    claimed = run_concurrently(lambda i: worker.claim_job(), 6)

    assert sum(1 for job in claimed if job) == 2


# --- finish_job / requeue_running --------------------------------------------

def test_finish_done_sets_progress_100(db):
    job_id = insert_job(db, "r")
    worker.claim_job()
    worker.finish_job(job_id, "done")
    status, progress, error, _, finished_at = job_row(db, job_id)
    assert (status, progress, error) == ("done", 100, None)
    assert finished_at is not None


def test_finish_error_keeps_progress_and_records_message(db):
    job_id = insert_job(db, "r")
    worker.claim_job()
    worker.set_progress(job_id, 60)
    worker.finish_job(job_id, "error", error="boom")
    status, progress, error, _, finished_at = job_row(db, job_id)
    assert (status, progress, error) == ("error", 60, "boom")
    assert finished_at is not None


def test_requeue_running_resets_all_running_jobs(db):
    running = insert_job(db, "a", status="running", started_offset_s=-5)
    done = insert_job(db, "b", status="done")

    worker.requeue_running()

    status, progress, _, started_at, _ = job_row(db, running)
    assert (status, progress, started_at) == ("queued", 0, None)
    assert job_row(db, done)[0] == "done"


def test_requeue_only_stale_leaves_recent_running_jobs(db):
    stale = insert_job(db, "stale", status="running", started_offset_s=-3 * 3600)
    fresh = insert_job(db, "fresh", status="running", started_offset_s=-60)

    worker.requeue_running(only_stale=True)

    assert job_row(db, stale)[0] == "queued"
    assert job_row(db, fresh)[0] == "running"


# --- record reservation -------------------------------------------------------

def test_reserve_new_record(db):
    video_id, is_new = vid_search.reserve_record("episode-1", source_url="http://x")
    assert is_new is True
    with db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT video_id, source_url FROM records WHERE record = 'episode-1';")
            assert cursor.fetchone() == (video_id, "http://x")


def test_reserve_existing_record_returns_owner(db):
    first_id, first_new = vid_search.reserve_record("episode-1")
    second_id, second_new = vid_search.reserve_record("episode-1")
    assert (first_new, second_new) == (True, False)
    assert second_id == first_id


def test_concurrent_reservations_have_exactly_one_winner(db):
    results = run_concurrently(lambda i: vid_search.reserve_record("contested"), 8)

    assert sum(1 for _, is_new in results if is_new) == 1
    assert len({video_id for video_id, _ in results}) == 1


def test_release_frees_label_for_retry(db):
    video_id, _ = vid_search.reserve_record("episode-1")
    vid_search.release_record("episode-1", video_id)
    new_id, is_new = vid_search.reserve_record("episode-1")
    assert is_new is True
    assert new_id != video_id


def test_release_with_wrong_video_id_is_a_noop(db):
    video_id, _ = vid_search.reserve_record("episode-1")
    vid_search.release_record("episode-1", "someone-elses-video-id")
    again_id, is_new = vid_search.reserve_record("episode-1")
    assert (again_id, is_new) == (video_id, False)
