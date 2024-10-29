
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import environ

env = environ.Env()
environ.Env.read_env()

cors_origins = env("CORS_ORIGINS").split(",")
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": cors_origins}})

@app.route('/api/search', methods=['GET'])
def search_keyword():
    keyword = request.args.get('keyword')
    video_id = request.args.get('video_id')

    with psycopg2.connect(
        dbname=env("DB_NAME"), user=env("DB_USER"), password=env("DB_PASSWORD"), host=env("DB_HOST")
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                               SELECT  word, start_time, end_time FROM transcripts
                               WHERE video_id = %s AND word ILIKE %s
                               """, (video_id, f"%{keyword}%"))
                results = cursor.fetchall()

    return jsonify(results)

if __name__ == '__main__':
    app.run(debug=True)