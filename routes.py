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

@app.route('/api/records', methods=['GET'])
def get_records():
    """
    Retrieve previous entries for re-use
    """
    try: 
        with psycopg2.connect(
            dbname=env("DB_NAME"), user=env("DB_USER"), password=env("DB_PASSWORD"), host=env("DB_HOST")
        ) as conn:
            with conn.cursor() as cursor:
                    cursor.execute("SELECT DISTINCT record FROM transcripts ORDER BY record;")
                    records = cursor.fetchall()
        record_list = [record[0] for record in records]
        return jsonify({"records": record_list}), 200
    except Exception as e:
        return jsonify({"error": f"Error occurred during transcription or search: {e}"}), 500        


@app.route('/api/search', methods=['POST'])
def transcribe_search():
    """
    Keyword search, optimized word search.
    """
    data = request.get_json()
    video_url = data.get('url')
    record = data.get('record')
    keyword = request.args.get('keyword')

    try:
        with psycopg2.connect(
            dbname=env("DB_NAME"), user=env("DB_USER"), password=env("DB_PASSWORD"), host=env("DB_HOST")
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT video_id FROM transcripts WHERE record = %s LIMIT 1;", (record,))
                existing_record = cursor.fetchone()
                
                if existing_record:
                    video_id = existing_record[0]
                else:
                    if not video_url:
                        return jsonify({"error": "Url is required for new records."}), 400
                    video_id = transcribe_save(video_url, record)

                if keyword:
                    regex_clean = rf"\m{keyword}\M"
                    cursor.execute("""
                        SELECT word, start_time, end_time
                        FROM transcripts
                        WHERE video_id = %s AND word ~* %s
                        """, (video_id, regex_clean))
                    results = cursor.fetchall()
                    return jsonify({"video_id": video_id, "results": results}), 200
            
            return jsonify({"video_id": video_id, "message": "Transcription complete."}), 200

    except Exception as e:
        print(f"Error during transcription or search: {e}")
        return jsonify({"error": f"Error occurred during transcription or search: {e}"}), 500

if __name__ == '__main__':
    app.run(debug=True)