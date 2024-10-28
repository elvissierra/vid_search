from flask import Flask, request, jsonify
import psycopg2
import environ

env = environ.Env()
environ.Env.read_env()

app = Flask(__name__)

@app.route('/app/search', methods=['GET'])
def search_keyword():
    keyword = request.args.get('keyword')
    video_id = request.args.get('video_id')

    with psycopg2.connect(
        dbname=env("DA_NAME"), user=env("DB_USER"), password=env("DB_PASSWORD"), host=env("DB_HOST")
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