import exports


def sample_segments():
    return [
        {
            "index": 0,
            "text": " Hello world",
            "start": 0.0,
            "end": 1.5,
            "words": [
                {"word": " Hello", "start": 0.0, "end": 0.6, "speaker": "SPEAKER_00"},
                {"word": " world", "start": 0.6, "end": 1.5, "speaker": "SPEAKER_00"},
            ],
        },
        {
            "index": 1,
            "text": " Goodbye now",
            "start": 61.25,
            "end": 62.75,
            "words": [
                {"word": " Goodbye", "start": 61.25, "end": 62.0, "speaker": "SPEAKER_01"},
                {"word": " now", "start": 62.0, "end": 62.75, "speaker": "SPEAKER_01"},
            ],
        },
    ]


def test_srt_timestamp_formatting():
    assert exports._srt_timestamp(0.0) == "00:00:00,000"
    assert exports._srt_timestamp(61.25) == "00:01:01,250"
    assert exports._srt_timestamp(3661.999) == "01:01:01,999"


def test_vtt_timestamp_uses_dot_separator():
    assert exports._vtt_timestamp(61.25) == "00:01:01.250"


def test_segment_speaker_majority():
    segment = {"words": [
        {"speaker": "SPEAKER_00"}, {"speaker": "SPEAKER_00"}, {"speaker": "SPEAKER_01"},
    ]}
    assert exports._segment_speaker(segment) == "SPEAKER_00"


def test_segment_speaker_none_when_untagged():
    segment = {"words": [{"speaker": None}, {"speaker": None}]}
    assert exports._segment_speaker(segment) is None


def test_to_srt_contains_sequential_numbering_and_timestamps():
    output = exports.to_srt(sample_segments())
    lines = output.strip().split("\n")
    assert lines[0] == "1"
    assert "00:00:00,000 --> 00:00:01,500" in output
    assert "SPEAKER_00: Hello world" in output
    assert "2" in lines
    assert "00:01:01,250 --> 00:01:02,750" in output


def test_to_vtt_starts_with_webvtt_header():
    output = exports.to_vtt(sample_segments())
    assert output.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:01.500" in output


def test_to_txt_plain_lines_with_speaker_prefix():
    output = exports.to_txt(sample_segments())
    lines = output.strip().split("\n")
    assert lines == ["SPEAKER_00: Hello world", "SPEAKER_01: Goodbye now"]


def test_to_json_structure():
    payload = exports.to_json(sample_segments(), video_id="vid-123")
    assert payload["video_id"] == "vid-123"
    assert len(payload["segments"]) == 2
    first = payload["segments"][0]
    assert first["speaker"] == "SPEAKER_00"
    assert first["start"] == 0.0
    assert first["end"] == 1.5
    assert len(first["words"]) == 2
