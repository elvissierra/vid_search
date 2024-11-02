from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import environ
from vid_search import transcribe_save

env = environ.Env()
environ.Env.read_env()

cors_origins = env("CORS_ORIGINS").split(",")
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": cors_origins}})


@app.route('/api/search', methods=['POST'])
def transcribe_search():
    """
    Keyword search, refactor to optimize word search
    """
    data = request.get_json()
    video_url = data.get('url')
    keyword = request.args.get('keyword')

    if not video_url:
        return jsonify({"error": "Url is required"}), 400

    try:
        video_id = transcribe_save(video_url)

        if keyword:
            with psycopg2.connect(
                dbname=env("DB_NAME"), user=env("DB_USER"), password=env("DB_PASSWORD"), host=env("DB_HOST")
            ) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT word, start_time, end_time
                        FROM transcripts
                        WHERE video_id = %s AND word ILIKE %s
                        """, (video_id, f"%{keyword}%"))
                    results = cursor.fetchall()

            return jsonify({"video_id": video_id, "results": results}), 200
        return jsonify({"video_id": video_id, "message": "Transcription complete."}), 200

    except Exception as e:
        print(f"Error during transcription or search: {e}")
        return jsonify({"error": f"Error occurred during transcription or search: {e}"}), 500

if __name__ == '__main__':
    app.run(debug=True)