import psycopg2
import environ
import whisper

env = environ.Env()
environ.Env.read_env()

with psycopg2.connet(
    dbname=env("DA_NAME"), user=env("DB_USER"), password=env("DB_PASSWORD"), host=env("DB_HOST")
    )as conn:
        with conn.cursor()as cursor:

            model = whisper.load_model("base")
            result = model.transcribe("videos/msg.mp4", word_timestamps=True)

            for segment in result["segments"]:
                segment_text = segment['text']
                for word in segment['words']:
                    start_time = word['start']
                    end_time = word['end']
                    word_text = word['word']

                    cursor.execute(
                        "INSERT INTO transcripts (video_id, segment_text, word, start_time, end_time) VALUES (%s, %s, %s, %s, %s)",
                        (1, segment_text, word_text, start_time, end_time)
                    )

            conn.commit()
            cursor.close()
            conn.close()