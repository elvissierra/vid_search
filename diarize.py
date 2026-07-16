import environ

env = environ.Env()
environ.Env.read_env()

_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        # Imported lazily: pulls in torch (~GBs), which the API process
        # should never load.
        from pyannote.audio import Pipeline

        token = env("HF_TOKEN", default=None)
        if not token:
            raise RuntimeError(
                "HF_TOKEN is not set. Speaker diarization needs a Hugging Face "
                "token with access to pyannote/speaker-diarization-3.1."
            )
        try:
            _pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1", use_auth_token=token
            )
        except Exception as e:
            raise RuntimeError(
                "Failed to load pyannote/speaker-diarization-3.1. Check that "
                "HF_TOKEN is valid and that you have accepted the gated-model "
                "terms for BOTH pyannote/speaker-diarization-3.1 and "
                "pyannote/segmentation-3.0 on huggingface.co."
            ) from e
    return _pipeline


def diarize(audio_file):
    """Run diarization; returns speaker turns as [(start, end, speaker), ...]."""
    annotation = get_pipeline()(audio_file)
    return [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]


def assign_speaker(start, end, turns):
    """Pick the speaker whose turn contains the word's midpoint, else the
    turn nearest to it. Returns None when there are no turns at all."""
    if not turns:
        return None
    mid = (start + end) / 2
    for turn_start, turn_end, speaker in turns:
        if turn_start <= mid <= turn_end:
            return speaker
    nearest = min(turns, key=lambda t: min(abs(t[0] - mid), abs(t[1] - mid)))
    return nearest[2]
