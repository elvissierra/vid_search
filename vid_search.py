import psycopg2
import environ
import whisper
import yt_dlp

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

def transcribe_save(url):
    audio_file = download_video_audio(url)
    model = whisper.load_model("base")
    result = model.transcribe(audio_file, word_timestamps=True)

    with psycopg2.connect(
        dbname=env("DB_NAME"), user=env("DB_USER"), password=env("DB_PASSWORD"), host=env("DB_HOST")
        ) as conn:
            with conn.cursor() as cursor:

                cursor.execute(
                    """
                    INSERT INTO transcripts (segment_text, word, start_time, end_time)
                    VALUES (%s, %s, %s, %s)
                    RETURNING video_id;
                    """,
                    (result['segments'][0]['text'], result['segments'][0]['words'][0]['word'], 
                    result['segments'][0]['words'][0]['start'], result['segments'][0]['words'][0]['end'])
                )
                video_id = cursor.fetchone()[0]

                for segment in result["segments"]:
                    segment_text = segment['text']
                    for word in segment['words']:
                        word_text = word['word']      
                        start_time = float(word['start'])
                        end_time = float(word['end'])     

                        cursor.execute(
                            """
                            INSERT INTO transcripts (video_id, segment_text, word, start_time, end_time)
                            VALUES (%s, %s, %s, %s, %s);
                            """,
                            (video_id, segment_text, word_text, start_time, end_time)
                        )
                conn.commit()

            return video_id
    
if __name__ == "__main__":
    video_url = 'https://www.youtube.com/watch?v=5GzFhlfxGxc&ab_channel=HouseofHighlights'
    video_id = 2 
    transcribe_save(video_url, video_id)