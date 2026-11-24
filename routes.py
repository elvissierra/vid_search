import hmac
import logging
import os
import time
import uuid

from flask import Flask, g, request, jsonify
from flask_cors import CORS
import environ

import auth
import embeddings
import exports
import feeds
import logs
import metrics
import phrase
import ratelimit
from db import get_conn
from languages import normalize_language
import uploads
import usage
from vid_search import reserve_record, release_record

env = environ.Env()
environ.Env.read_env()

logs.configure("api")
request_log = logging.getLogger("api.request")

cors_origins = env("CORS_ORIGINS").split(",")
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": cors_origins}})
app.config["MAX_CONTENT_LENGTH"] = uploads.max_upload_bytes()

LIBRARY_RESULTS_DEFAULT = 100
MAX_LIBRARY_RESULTS = 500
SEMANTIC_RESULTS_DEFAULT = 10
MAX_SEMANTIC_RESULTS = 50
MAX_SEMANTIC_QUERY_CHARS = 500
BULK_ENTRIES_DEFAULT = 10
MAX_BULK_ENTRIES = 25
MAX_RECORD_CHARS = 200


@app.before_request
def start_timer():
    g.started = time.monotonic()


@app.after_request
def log_request(response):
    started = getattr(g, "started", None)
    # Health probes fire every few seconds; keep them out of the INFO stream.
    level = logging.DEBUG if request.path == "/api/health" else logging.INFO
    request_log.log(level, "request", extra={
        "method": request.method,
        "path": request.path,
        "status": response.status_code,
        "duration_ms": None if started is None else round((time.monotonic() - started) * 1000, 1),
    })
    return response


@app.errorhandler(413)
def too_large(_e):
    limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return jsonify({"error": f"File too large; limit is {limit_mb} MB"}), 413


@app.errorhandler(auth.AuthRequired)
def auth_required(_e):
    return jsonify({"error": "Authentication required"}), 401


def quota_response(summary):
    """402 body for a user who has used up this month's free tier."""
    return jsonify({"error": "Monthly free-tier quota used up", **summary}), 402


def rate_limited(bucket, user_id):
    """A 429 response if this caller is over the bucket's limit, else None.

    Fails open: if the limiter's database call breaks, the request goes
    through (the endpoint's own queries will surface a real outage).
    """
    try:
        retry_after = ratelimit.check(bucket, ratelimit.client_key(user_id, request.remote_addr))
    except Exception:
        app.logger.exception("Rate limit check failed")
        return None
    if retry_after is None:
        return None
    resp = jsonify({"error": "Too many requests", "retry_after_seconds": retry_after})
    resp.status_code = 429
    resp.headers["Retry-After"] = str(retry_after)
    return resp


def viewer():
    """User id for this request (None = anonymous); raises AuthRequired.

    Call it before a handler's try block so the 401 is not caught by the
    handler's generic 500.
    """
    return auth.viewer_id(request.headers.get('Authorization'))


@app.route('/api/health', methods=['GET'])
def health():
    """Liveness plus a database round trip, for load balancers and compose.
    Unauthenticated and not rate limited. 200 when the database answers, else 503."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.fetchone()
    except Exception:
        app.logger.exception("Health check failed")
        return jsonify({"status": "degraded", "db": "error"}), 503
    return jsonify({"status": "ok", "db": "ok"}), 200


@app.route('/api/metrics', methods=['GET'])
def get_metrics():
    """
    Job queue metrics for operators. Disabled (404) unless METRICS_TOKEN is
    set; then the request must send `Authorization: Bearer <METRICS_TOKEN>`.
    """
    expected = os.environ.get("METRICS_TOKEN", "")
    if not expected:
        return jsonify({"error": "Not found"}), 404
    header = request.headers.get("Authorization", "")
    supplied = header[7:] if header.startswith("Bearer ") else ""
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        return jsonify({"error": "Authentication required"}), 401
    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                return jsonify(metrics.job_metrics(cursor)), 200
    except Exception:
        app.logger.exception("Failed to compute metrics")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/signup', methods=['POST'])
def signup():
    """
    Create an account. Body `{email, password}`. Returns 201 with the user
    and a bearer token (send as `Authorization: Bearer <token>`); 400 for an
    invalid email/password, 409 if the email is already registered.
    """
    data = request.get_json(silent=True) or {}
    try:
        email = auth.normalize_email(data.get('email'))
        password = auth.validate_password(data.get('password'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        user = auth.create_user(email, password)
        if not user:
            return jsonify({"error": "Email already registered"}), 409
        return jsonify({"user": user, "token": auth.create_session(user["id"])}), 201
    except Exception:
        app.logger.exception("Signup failed")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/login', methods=['POST'])
def login():
    """
    Body `{email, password}`. Returns 200 with the user and a new bearer
    token, or 401 for bad credentials (the same answer for an unknown email).
    """
    data = request.get_json(silent=True) or {}
    email, password = data.get('email'), data.get('password')
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify({"error": "Invalid email or password"}), 401

    try:
        user = auth.authenticate(email.strip().lower(), password[:auth.MAX_PASSWORD])
        if not user:
            return jsonify({"error": "Invalid email or password"}), 401
        return jsonify({"user": user, "token": auth.create_session(user["id"])}), 200
    except Exception:
        app.logger.exception("Login failed")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/logout', methods=['POST'])
def logout():
    """Revoke the bearer token used for this request. 204, or 401 if not logged in."""
    token = auth.bearer_token(request.headers.get('Authorization'))
    try:
        if not auth.user_for_token(token):
            return jsonify({"error": "Authentication required"}), 401
        auth.revoke_token(token)
        return '', 204
    except Exception:
        app.logger.exception("Logout failed")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/me', methods=['GET'])
def me():
    """The logged-in user, or 401."""
    try:
        user = auth.user_for_token(auth.bearer_token(request.headers.get('Authorization')))
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        return jsonify({"user": user}), 200
    except Exception:
        app.logger.exception("Failed to load current user")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/usage', methods=['GET'])
def get_usage():
    """
    This month's transcription usage for the logged-in user:
    `{used_seconds, limit_seconds, remaining_seconds, period_start, period_end}`.
    401 without a valid token (anonymous requests are not metered).
    """
    user_id = viewer()
    if user_id is None:
        return jsonify({"error": "Authentication required"}), 401
    try:
        return jsonify(usage.usage_summary(user_id)), 200
    except Exception:
        app.logger.exception("Failed to load usage")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/records', methods=['GET'])
def get_records():
    """
    Retrieve the viewer's previous entries for search
    """
    user_id = viewer()
    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT record FROM records WHERE user_id IS NOT DISTINCT FROM %s ORDER BY record;",
                    (user_id,)
                )
                records = cursor.fetchall()
        record_list = [record[0] for record in records]
        return jsonify({"records": record_list}), 200
    except Exception:
        app.logger.exception("Failed to list records")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/search', methods=['POST'])
def transcribe_search():
    """
    Keyword search within a record. New records are queued for the worker:
    the label is reserved, a job row is inserted, and a 202 with the job id
    is returned for the client to poll via /api/jobs/<job_id>.

    An optional `language` (whisper code or name, e.g. "es" or "Spanish";
    omitted or "auto" means detect) is validated up front and stored on the
    job. It only matters when a new record is queued.

    The keyword matches whole words, case-insensitively and ignoring
    surrounding punctuation ("hello" finds " Hello,"), via the indexed
    transcripts.word_norm column. A keyword of several words is a phrase: it
    matches those words in order, back to back (see phrase.py), and is limited
    to phrase.MAX_PHRASE_WORDS words (400 beyond that). A keyword with no
    letters or digits matches nothing.

    Records are scoped to the logged-in user (bearer token); without a token
    only unowned records are visible. Labels are unique per owner. Queueing a
    new record is refused with 402 once the user has used up this month's
    free tier (see usage.py). Calls are rate limited per caller (see
    ratelimit.py): every call counts against the search bucket and queueing
    a new record also against the ingest bucket; over the limit is 429 with
    a Retry-After header.
    """
    user_id = viewer()
    limited = rate_limited("search", user_id)
    if limited:
        return limited
    data = request.get_json()
    video_url = data.get('url')
    record = data.get('record')
    keyword = data.get('keyword')
    if keyword is not None and not isinstance(keyword, str):
        return jsonify({"error": "keyword must be a string"}), 400
    if keyword and len(phrase.split_keyword(keyword)) > phrase.MAX_PHRASE_WORDS:
        return jsonify({"error": f"keyword is limited to {phrase.MAX_PHRASE_WORDS} words"}), 400

    try:
        language = normalize_language(data.get('language'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT video_id FROM records WHERE record = %s AND user_id IS NOT DISTINCT FROM %s;",
                    (record, user_id)
                )
                existing_record = cursor.fetchone()

        if not existing_record:
            if not video_url:
                return jsonify({"error": "Record or video URL is required"}), 400

            limited = rate_limited("ingest", user_id)
            if limited:
                return limited

            over = usage.quota_exceeded(user_id)
            if over:
                return quota_response(over)

            video_id, is_new = reserve_record(record, source_url=video_url, user_id=user_id)
            if not is_new:
                return jsonify({"error": "Record already exists or is being processed"}), 409

            job_id = str(uuid.uuid4())
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO jobs (id, record, url, video_id, language, user_id)
                        VALUES (%s, %s, %s, %s, %s, %s);
                        """,
                        (job_id, record, video_url, video_id, language, user_id)
                    )
            return jsonify({"job_id": job_id, "record": record}), 202

        video_id = existing_record[0]

        if keyword:
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    rows = phrase.search_words(cursor, video_id, keyword)

            results = [
                {"word": word, "start": start, "end": end, "speaker": speaker}
                for (word, start, end, speaker) in rows
            ]
            return jsonify({"video_id": video_id, "results": results}), 200

        return jsonify({"video_id": video_id, "message": "Transcription complete."}), 200

    except Exception:
        app.logger.exception("Transcription or search failed")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/search/all', methods=['POST'])
def search_library():
    """
    Search every record the viewer can see (same scoping as /api/records) for
    a keyword or phrase, using the same matching as /api/search. Body
    `{keyword, limit?}`; `keyword` is required (a non-blank string of at most
    phrase.MAX_PHRASE_WORDS words, else 400) and `limit` is an integer from 1
    to MAX_LIBRARY_RESULTS (default LIBRARY_RESULTS_DEFAULT). Returns 200
    `{keyword, results: [{record, video_id, word, start, end, speaker}],
    truncated}`: records in label order, then position in the recording;
    `truncated` is true when more hits exist than `limit`. Counts against the
    search rate limit (429 over it). Never queues a job.
    """
    user_id = viewer()
    limited = rate_limited("search", user_id)
    if limited:
        return limited
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    keyword = data.get('keyword')
    if not isinstance(keyword, str) or not keyword.strip():
        return jsonify({"error": "keyword must be a non-empty string"}), 400
    if len(phrase.split_keyword(keyword)) > phrase.MAX_PHRASE_WORDS:
        return jsonify({"error": f"keyword is limited to {phrase.MAX_PHRASE_WORDS} words"}), 400
    limit = data.get('limit', LIBRARY_RESULTS_DEFAULT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIBRARY_RESULTS:
        return jsonify({"error": f"limit must be an integer from 1 to {MAX_LIBRARY_RESULTS}"}), 400

    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT record, video_id FROM records WHERE user_id IS NOT DISTINCT FROM %s ORDER BY record;",
                    (user_id,)
                )
                records = cursor.fetchall()
                labels = {video_id: record for (record, video_id) in records}
                rows = phrase.search_many(
                    cursor, [video_id for (_, video_id) in records], keyword, limit + 1
                ) if records else []

        results = [
            {"record": labels[video_id], "video_id": video_id,
             "word": word, "start": start, "end": end, "speaker": speaker}
            for (video_id, word, start, end, speaker) in rows[:limit]
        ]
        return jsonify({"keyword": keyword, "results": results, "truncated": len(rows) > limit}), 200
    except Exception:
        app.logger.exception("Library search failed")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/search/semantic', methods=['POST'])
def search_semantic():
    """
    Find the transcript segments closest in meaning to a free-text query,
    across every record the viewer can see (same scoping as /api/records).
    Body `{query, limit?}`; `query` is a non-blank string of at most
    MAX_SEMANTIC_QUERY_CHARS characters and `limit` an integer from 1 to
    MAX_SEMANTIC_RESULTS (default SEMANTIC_RESULTS_DEFAULT), else 400.
    Returns 200 `{query, results: [{record, video_id, text, start, end,
    score}]}` best first, `score` being cosine similarity. Records without
    embeddings (see embeddings.py) never match. Counts against the search
    rate limit (429 over it). Never queues a job.
    """
    user_id = viewer()
    limited = rate_limited("search", user_id)
    if limited:
        return limited
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    query = data.get('query')
    if not isinstance(query, str) or not query.strip():
        return jsonify({"error": "query must be a non-empty string"}), 400
    if len(query) > MAX_SEMANTIC_QUERY_CHARS:
        return jsonify({"error": f"query is limited to {MAX_SEMANTIC_QUERY_CHARS} characters"}), 400
    limit = data.get('limit', SEMANTIC_RESULTS_DEFAULT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_SEMANTIC_RESULTS:
        return jsonify({"error": f"limit must be an integer from 1 to {MAX_SEMANTIC_RESULTS}"}), 400

    try:
        query_vector = embeddings.embed([query.strip()])[0]
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT record, video_id FROM records WHERE user_id IS NOT DISTINCT FROM %s;",
                    (user_id,)
                )
                labels = {video_id: record for (record, video_id) in cursor.fetchall()}
                rows = embeddings.search(cursor, list(labels), query_vector, limit)

        results = [
            {"record": labels[video_id], "video_id": video_id, "text": text,
             "start": start, "end": end, "score": score}
            for (video_id, text, start, end, score) in rows
        ]
        return jsonify({"query": query, "results": results}), 200
    except Exception:
        app.logger.exception("Semantic search failed")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/upload', methods=['POST'])
def upload_media():
    """
    Queue an uploaded audio/video file for transcription. Multipart form with
    `file`, `record` and an optional `language`. The file is validated
    (extension allow-list, MAX_UPLOAD_MB), stored under a server-generated
    name, and queued with its path in jobs.upload_path; the worker deletes it
    after the job. Returns 202 with the job id, like /api/search; 402 if the
    free-tier quota is used up (checked before the file is stored); 429 when the
    caller exceeds the ingest rate limit (checked first). The record
    belongs to the logged-in user (see /api/search).
    """
    user_id = viewer()
    limited = rate_limited("ingest", user_id)
    if limited:
        return limited
    record = (request.form.get('record') or '').strip()
    if not record:
        return jsonify({"error": "Record is required"}), 400

    try:
        language = normalize_language(request.form.get('language'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        over = usage.quota_exceeded(user_id)
    except Exception:
        app.logger.exception("Quota check failed")
        return jsonify({"error": "Internal server error"}), 500
    if over:
        return quota_response(over)

    path = None
    video_id = None
    try:
        path = uploads.save_upload(request.files.get('file'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        app.logger.exception("Failed to store upload")
        return jsonify({"error": "Internal server error"}), 500

    try:
        video_id, is_new = reserve_record(record, source_url=None, user_id=user_id)
        if not is_new:
            os.remove(path)
            return jsonify({"error": "Record already exists or is being processed"}), 409

        job_id = str(uuid.uuid4())
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO jobs (id, record, url, video_id, language, upload_path, user_id)
                    VALUES (%s, %s, NULL, %s, %s, %s, %s);
                    """,
                    (job_id, record, video_id, language, path, user_id)
                )
        return jsonify({"job_id": job_id, "record": record}), 202
    except Exception:
        app.logger.exception("Failed to queue upload")
        if os.path.exists(path):
            os.remove(path)
        if video_id:
            release_record(record, video_id)
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/ingest/bulk', methods=['POST'])
def ingest_bulk():
    """
    Queue the episodes of a podcast RSS feed or a video playlist. Body
    `{url, limit?, language?}`; `url` is an http(s) link to a public host,
    `limit` an integer from 1 to MAX_BULK_ENTRIES (default
    BULK_ENTRIES_DEFAULT) and `language` as in /api/search. Each episode
    becomes a record labelled with its title, queued like /api/search does.
    Episodes whose label or source url the viewer already has are skipped, as
    are any that fail to queue. Returns 202 `{queued: [{job_id, record,
    url}], skipped: [{record, reason}]}`; 400 for bad input, 422 when the
    feed holds no episodes, 502 when it cannot be read, 402 when the
    free-tier quota is used up (checked once, before queueing), 429 over the
    ingest rate limit (one hit per call).
    """
    user_id = viewer()
    limited = rate_limited("ingest", user_id)
    if limited:
        return limited
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    url = data.get('url')
    if not isinstance(url, str) or not url.strip():
        return jsonify({"error": "url must be a non-empty string"}), 400
    url = url.strip()
    limit = data.get('limit', BULK_ENTRIES_DEFAULT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BULK_ENTRIES:
        return jsonify({"error": f"limit must be an integer from 1 to {MAX_BULK_ENTRIES}"}), 400
    try:
        language = normalize_language(data.get('language'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        over = usage.quota_exceeded(user_id)
    except Exception:
        app.logger.exception("Quota check failed")
        return jsonify({"error": "Internal server error"}), 500
    if over:
        return quota_response(over)

    try:
        entries = feeds.list_entries(url, limit)
    except feeds.InvalidUrl as e:
        return jsonify({"error": str(e)}), 400
    except feeds.FeedError as e:
        return jsonify({"error": str(e)}), 502
    except Exception:
        app.logger.exception("Feed listing failed")
        return jsonify({"error": "Internal server error"}), 500
    if not entries:
        return jsonify({"error": "No episodes found at that url"}), 422

    queued, skipped = [], []
    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT source_url FROM records WHERE user_id IS NOT DISTINCT FROM %s AND source_url IS NOT NULL;",
                    (user_id,)
                )
                known_urls = {row[0] for row in cursor.fetchall()}
    except Exception:
        app.logger.exception("Bulk ingest lookup failed")
        return jsonify({"error": "Internal server error"}), 500

    for number, entry in enumerate(entries, start=1):
        record = (entry["title"] or f"Episode {number}")[:MAX_RECORD_CHARS]
        if entry["url"] in known_urls:
            skipped.append({"record": record, "reason": "already ingested"})
            continue
        video_id = None
        try:
            video_id, is_new = reserve_record(record, source_url=entry["url"], user_id=user_id)
            if not is_new:
                skipped.append({"record": record, "reason": "label already exists"})
                continue
            job_id = str(uuid.uuid4())
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO jobs (id, record, url, video_id, language, user_id)
                        VALUES (%s, %s, %s, %s, %s, %s);
                        """,
                        (job_id, record, entry["url"], video_id, language, user_id)
                    )
            known_urls.add(entry["url"])
            queued.append({"job_id": job_id, "record": record, "url": entry["url"]})
        except Exception:
            app.logger.exception("Failed to queue bulk entry")
            if video_id:
                release_record(record, video_id)
            skipped.append({"record": record, "reason": "could not be queued"})

    return jsonify({"queued": queued, "skipped": skipped}), 202


@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    """
    Poll a transcription job's status and progress. Jobs of other owners
    are 404, the same as a job that does not exist.
    """
    user_id = viewer()
    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, status, progress, record, video_id, error, created_at, finished_at
                    FROM jobs WHERE id = %s AND user_id IS NOT DISTINCT FROM %s;
                    """,
                    (job_id, user_id)
                )
                row = cursor.fetchone()

        if not row:
            return jsonify({"error": "Job not found"}), 404

        keys = ("id", "status", "progress", "record", "video_id", "error", "created_at", "finished_at")
        return jsonify(dict(zip(keys, row))), 200
    except Exception:
        app.logger.exception("Failed to fetch job")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/export/<video_id>', methods=['GET'])
def export_transcript(video_id):
    """
    Export a transcribed video's segments as srt, vtt, txt, or json. Only
    the owner's records can be exported; others are 404.
    """
    user_id = viewer()
    fmt = request.args.get('format', 'txt').lower()
    if fmt not in exports.FORMATS and fmt != 'json':
        return jsonify({"error": "format must be one of: srt, vtt, txt, json"}), 400

    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM records WHERE video_id = %s AND user_id IS NOT DISTINCT FROM %s;",
                    (video_id, user_id)
                )
                owned = cursor.fetchone()
        segments = exports.fetch_segments(video_id) if owned else []
        if not segments:
            return jsonify({"error": "No transcript found for this video_id"}), 404

        if fmt == 'json':
            return jsonify(exports.to_json(segments, video_id)), 200

        content_type, serialize = exports.FORMATS[fmt]
        body = serialize(segments)
        return app.response_class(body, mimetype=content_type, headers={
            "Content-Disposition": f'attachment; filename="{video_id}.{fmt}"'
        })
    except Exception:
        app.logger.exception("Export failed")
        return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    app.run(debug=True)
