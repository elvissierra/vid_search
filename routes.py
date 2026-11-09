import os
import re
import uuid

from flask import Flask, request, jsonify
from flask_cors import CORS
import environ

import auth
import exports
from db import get_conn
from languages import normalize_language
import uploads
from vid_search import reserve_record, release_record

env = environ.Env()
environ.Env.read_env()

cors_origins = env("CORS_ORIGINS").split(",")
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": cors_origins}})
app.config["MAX_CONTENT_LENGTH"] = uploads.max_upload_bytes()


@app.errorhandler(413)
def too_large(_e):
    limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return jsonify({"error": f"File too large; limit is {limit_mb} MB"}), 413


@app.errorhandler(auth.AuthRequired)
def auth_required(_e):
    return jsonify({"error": "Authentication required"}), 401


def viewer():
    """User id for this request (None = anonymous); raises AuthRequired.

    Call it before a handler's try block so the 401 is not caught by the
    handler's generic 500.
    """
    return auth.viewer_id(request.headers.get('Authorization'))


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

    Records are scoped to the logged-in user (bearer token); without a token
    only unowned records are visible. Labels are unique per owner.
    """
    user_id = viewer()
    data = request.get_json()
    video_url = data.get('url')
    record = data.get('record')
    keyword = data.get('keyword')

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
            regex_clean = rf"\m{re.escape(keyword)}\M"

            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT word, start_time, end_time, speaker
                        FROM transcripts
                        WHERE video_id = %s AND word ~* %s
                        ORDER BY start_time
                    """, (video_id, regex_clean))
                    rows = cursor.fetchall()

            results = [
                {"word": word, "start": start, "end": end, "speaker": speaker}
                for (word, start, end, speaker) in rows
            ]
            return jsonify({"video_id": video_id, "results": results}), 200

        return jsonify({"video_id": video_id, "message": "Transcription complete."}), 200

    except Exception:
        app.logger.exception("Transcription or search failed")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/upload', methods=['POST'])
def upload_media():
    """
    Queue an uploaded audio/video file for transcription. Multipart form with
    `file`, `record` and an optional `language`. The file is validated
    (extension allow-list, MAX_UPLOAD_MB), stored under a server-generated
    name, and queued with its path in jobs.upload_path; the worker deletes it
    after the job. Returns 202 with the job id, like /api/search. The record
    belongs to the logged-in user (see /api/search).
    """
    user_id = viewer()
    record = (request.form.get('record') or '').strip()
    if not record:
        return jsonify({"error": "Record is required"}), 400

    try:
        language = normalize_language(request.form.get('language'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

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
