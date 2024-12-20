import psycopg2
import environ
import whisper
import yt_dlp
import uuid
import numpy as np

env = environ.Env()
environ.Env.read_env()

def download_video_audio(url):
    try:
        print(f"Attempting to download audio from: {url}")
        ydl_opts = {
             'format': 'bestaudio/best',
             'postprocessors': [{
                  'key': 'FFmpegExtractAudio',
                  'preferredcodec': 'mp3',
                  'preferredquality': '192',
             }], 
             'outtmpl': 'video/%(id)s.%(ext)s',
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
             info_dict = ydl.extract_info(url, download=True)
             audio_file = ydl.prepare_filename(info_dict).replace('.webm', '.mp3')
             print(f"Audio downloaded successfully: {audio_file}")
             return audio_file
    except Exception as e:
         print(f"Error downloading video: {e}")
         raise e

def transcribe_save(url, record=None):

        with psycopg2.connect(
            dbname=env("DB_NAME"), user=env("DB_USER"), password=env("DB_PASSWORD"), host=env("DB_HOST")
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT video_id FROM transcripts WHERE record = %s LIMIT 1;", (record,))
                existing_record = cursor.fetchone()
                if existing_record:
                     return existing_record[0]

                audio_file = download_video_audio(url)
                model = whisper.load_model("base")
                result = model.transcribe(audio_file, word_timestamps=True)

                video_id = str(uuid.uuid4())

                for segment in result["segments"]:
                    segment_text = str(segment['text'])
                    for word in segment['words']:
                        word_text = str(word['word'])
                        start_time = float(word['start'])
                        end_time = float(word['end'])

                        cursor.execute(
                            """
                            INSERT INTO transcripts (video_id, record, segment_text, word, start_time, end_time)
                            VALUES (%s, %s, %s, %s, %s, %s);
                            """,
                            (video_id, record, segment_text, word_text, start_time, end_time)
                        )

                conn.commit()
        return video_id