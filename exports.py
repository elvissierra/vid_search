"""Serialize a transcribed video's words back into export formats.

Words are stored per-row in Postgres; segment_index groups them back into
the segments Whisper originally produced.
"""
from db import get_conn


def fetch_segments(video_id):
    """Return segments as a list of dicts: {index, text, start, end, words}.

    words is a list of {word, start, end, speaker}. A segment's start/end
    span its first and last word. Returns [] if video_id has no rows.
    """
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT segment_index, segment_text, word, start_time, end_time, speaker
                FROM transcripts
                WHERE video_id = %s
                ORDER BY segment_index, start_time;
                """,
                (video_id,)
            )
            rows = cursor.fetchall()

    segments = []
    current = None
    for segment_index, segment_text, word, start_time, end_time, speaker in rows:
        if current is None or current["index"] != segment_index:
            current = {"index": segment_index, "text": segment_text, "words": []}
            segments.append(current)
        current["words"].append(
            {"word": word, "start": start_time, "end": end_time, "speaker": speaker}
        )

    for segment in segments:
        segment["start"] = segment["words"][0]["start"]
        segment["end"] = segment["words"][-1]["end"]

    return segments


def _srt_timestamp(seconds):
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _vtt_timestamp(seconds):
    return _srt_timestamp(seconds).replace(",", ".")


def _segment_speaker(segment):
    """Majority speaker across a segment's words, or None if untagged."""
    speakers = [w["speaker"] for w in segment["words"] if w["speaker"]]
    if not speakers:
        return None
    return max(set(speakers), key=speakers.count)


def to_srt(segments):
    lines = []
    for i, segment in enumerate(segments, start=1):
        speaker = _segment_speaker(segment)
        text = segment["text"].strip()
        if speaker:
            text = f"{speaker}: {text}"
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(segment['start'])} --> {_srt_timestamp(segment['end'])}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def to_vtt(segments):
    lines = ["WEBVTT", ""]
    for segment in segments:
        speaker = _segment_speaker(segment)
        text = segment["text"].strip()
        if speaker:
            text = f"{speaker}: {text}"
        lines.append(f"{_vtt_timestamp(segment['start'])} --> {_vtt_timestamp(segment['end'])}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def to_txt(segments):
    lines = []
    for segment in segments:
        speaker = _segment_speaker(segment)
        text = segment["text"].strip()
        lines.append(f"{speaker}: {text}" if speaker else text)
    return "\n".join(lines) + "\n"


def to_json(segments, video_id):
    return {
        "video_id": video_id,
        "segments": [
            {
                "index": segment["index"],
                "text": segment["text"].strip(),
                "start": segment["start"],
                "end": segment["end"],
                "speaker": _segment_speaker(segment),
                "words": segment["words"],
            }
            for segment in segments
        ],
    }


FORMATS = {
    "srt": ("text/plain", to_srt),
    "vtt": ("text/vtt", to_vtt),
    "txt": ("text/plain", to_txt),
}
