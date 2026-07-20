import re
import uuid

from flask import Flask, request, jsonify
from flask_cors import CORS
import environ

import exports
from db import get_conn
from vid_search import reserve_record

env = environ.Env()
environ.Env.read_env()

cors_origins = env("CORS_ORIGINS").split(",")
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": cors_origins}})


@app.route('/api/records', methods=['GET'])
def get_records():
    """
    Retrieve all previous entries for search
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT record FROM records ORDER BY record;")
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
    """
    data = request.get_json()
    video_url = data.get('url')
    record = data.get('record')
    keyword = data.get('keyword')

    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT video_id FROM records WHERE record = %s;", (record,))
                existing_record = cursor.fetchone()

        if not existing_record:
            if not video_url:
                return jsonify({"error": "Record or video URL is required"}), 400

            video_id, is_new = reserve_record(record, source_url=video_url)
            if not is_new:
                return jsonify({"error": "Record already exists or is being processed"}), 409

            job_id = str(uuid.uuid4())
            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO jobs (id, record, url, video_id)
                        VALUES (%s, %s, %s, %s);
                        """,
                        (job_id, record, video_url, video_id)
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


@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    """
    Poll a transcription job's status and progress.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, status, progress, record, video_id, error, created_at, finished_at
                    FROM jobs WHERE id = %s;
                    """,
                    (job_id,)
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
    Export a transcribed video's segments as srt, vtt, txt, or json.
    """
    fmt = request.args.get('format', 'txt').lower()
    if fmt not in exports.FORMATS and fmt != 'json':
        return jsonify({"error": "format must be one of: srt, vtt, txt, json"}), 400

    try:
        segments = exports.fetch_segments(video_id)
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
