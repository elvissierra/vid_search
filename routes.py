import re

from flask import Flask, request, jsonify
from flask_cors import CORS
import environ

from db import get_conn
from vid_search import transcribe_save

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
    Keyword search with record and video_id association.
    """
    data = request.get_json()
    video_url = data.get('url')
    record = data.get('record')
    keyword = request.args.get('keyword')

    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT video_id FROM records WHERE record = %s;", (record,))
                existing_record = cursor.fetchone()

        if not existing_record:
            if not video_url:
                return jsonify({"error": "Record or video URL is required"}), 400
            video_id = transcribe_save(video_url, record)
        else:
            video_id = existing_record[0]

        if keyword:
            regex_clean = rf"\m{re.escape(keyword)}\M"

            with get_conn() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT word, start_time, end_time
                        FROM transcripts
                        WHERE video_id = %s AND word ~* %s
                    """, (video_id, regex_clean))
                    results = cursor.fetchall()

            return jsonify({"video_id": video_id, "results": results}), 200

        return jsonify({"video_id": video_id, "message": "Transcription complete."}), 200

    except Exception:
        app.logger.exception("Transcription or search failed")
        return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    app.run(debug=True)
