import os
import uuid

from psycopg2.extras import execute_values

import diarize
from db import get_conn

_model = None


def get_model():
    global _model
    if _model is None:
        # Imported lazily: whisper pulls in torch, which the API process
        # (which imports this module for reserve_record) should never load.
        import whisper
        _model = whisper.load_model("base")
    return _model


def download_video_audio(url):
    import yt_dlp
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
             downloads = info_dict.get('requested_downloads') or []
             if downloads and downloads[0].get('filepath'):
                  audio_file = downloads[0]['filepath']
             else:
                  audio_file = os.path.splitext(ydl.prepare_filename(info_dict))[0] + '.mp3'
             print(f"Audio downloaded successfully: {audio_file}")
             return audio_file
    except Exception as e:
         print(f"Error downloading video: {e}")
         raise


def reserve_record(record, source_url=None):
    """Claim a record label, or return the video_id of whoever already owns it.

    Returns (video_id, is_new). The INSERT ... ON CONFLICT DO NOTHING against
    the records primary key is what makes two concurrent submissions of the
    same label safe: exactly one caller sees is_new=True.
    """
    video_id = str(uuid.uuid4())
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO records (record, video_id, source_url)
                VALUES (%s, %s, %s)
                ON CONFLICT (record) DO NOTHING
                RETURNING video_id;
                """,
                (record, video_id, source_url)
            )
            row = cursor.fetchone()
            if row:
                return row[0], True
            cursor.execute("SELECT video_id FROM records WHERE record = %s;", (record,))
            return cursor.fetchone()[0], False


def release_record(record, video_id):
    """Free a reserved label after a failed transcription so it can be retried."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM records WHERE record = %s AND video_id = %s;",
                (record, video_id)
            )


def process_audio(audio_file, record, video_id, language=None, progress_cb=None):
    """Transcribe + diarize a local audio file and persist the word rows.

    The record label must already be reserved (see reserve_record) and its
    video_id passed in. progress_cb, when given, receives percent milestones.
    """
    def report(progress):
        if progress_cb:
            progress_cb(progress)

    model = get_model()
    result = model.transcribe(audio_file, word_timestamps=True, language=language)
    report(60)
    turns = diarize.diarize(audio_file)
    report(85)

    rows = []
    for segment_index, segment in enumerate(result["segments"]):
        segment_text = str(segment['text'])
        for word in segment['words']:
            start_time = float(word['start'])
            end_time = float(word['end'])
            rows.append((
                video_id,
                record,
                segment_index,
                segment_text,
                str(word['word']),
                start_time,
                end_time,
                diarize.assign_speaker(start_time, end_time, turns),
            ))

    with get_conn() as conn:
        with conn.cursor() as cursor:
            execute_values(
                cursor,
                """
                INSERT INTO transcripts
                    (video_id, record, segment_index, segment_text, word, start_time, end_time, speaker)
                VALUES %s;
                """,
                rows
            )

    return video_id
