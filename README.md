# vid_search

Paste a video URL, get a searchable word-level transcript. Flask + Postgres
backend, Vue 3 (Vite) frontend. Audio is extracted with `yt-dlp` and
transcribed locally with OpenAI Whisper (word-level timestamps); every word is
stored as a row in Postgres so keyword search returns exact timestamps. Each
word is also tagged with a speaker label (`SPEAKER_00`, …) via pyannote
speaker diarization.

## Prerequisites

- **Python 3.10–3.12** (recommended — PyTorch/Whisper wheels lag behind the
  newest Python; 3.13+/3.14 may not resolve)
- **PostgreSQL** (any recent version)
- **ffmpeg** on PATH (used by yt-dlp for audio extraction)
- **Node 18+** for the frontend

## Setup

```bash
# Backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

createdb vid_search
psql -d vid_search -f schema.sql        # idempotent, re-run any time

cp .env.example .env                     # then fill in DB credentials

# Frontend
cd search_ui
npm install
cp .env.example .env
```

If you have a database from before `schema.sql` existed, see the migration
comments at the bottom of [schema.sql](schema.sql).

### Speaker diarization (one-time setup)

Diarization uses gated Hugging Face models. Before the first run:

1. Create a token at https://huggingface.co/settings/tokens
2. Accept the terms on **both** model pages:
   https://huggingface.co/pyannote/speaker-diarization-3.1 and
   https://huggingface.co/pyannote/segmentation-3.0
3. Set `HF_TOKEN` in `.env`

The first transcription downloads the model checkpoints; a 401 during
pipeline load means the token is wrong or the terms weren't accepted. Note
that `pip install -r requirements.txt` pulls in PyTorch (~2 GB+), and
diarization roughly doubles per-video processing time.

## Running

Three processes (see also [Procfile](Procfile)):

```bash
python routes.py            # API on http://localhost:5000
python worker.py            # transcription worker (loads ML models at startup)
cd search_ui && npm run dev # UI on http://localhost:5173
```

Transcription is asynchronous: submitting a new record returns `202` with a
job id immediately; the worker picks the job up from the `jobs` table and the
UI polls `/api/jobs/<id>` showing progress. If the worker isn't running, jobs
just stay queued. Downloaded audio is deleted after each job.

## Environment variables

| File | Variable | Purpose |
|---|---|---|
| `.env` | `DB_NAME` `DB_USER` `DB_PASSWORD` `DB_HOST` `DB_PORT` | Postgres connection |
| `.env` | `CORS_ORIGINS` | Comma-separated allowed frontend origins |
| `.env` | `HF_TOKEN` | Hugging Face token for pyannote diarization models |
| `search_ui/.env` | `VITE_API_URL` | API base URL for the frontend |

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/records` | List previously ingested record labels |
| POST | `/api/search` | Body `{url, record, keyword}`. Existing record → `200` `{video_id, results: [{word, start, end, speaker}]}`. New record → job queued, `202` `{job_id, record}` (or `409` if the label is taken) |
| GET | `/api/jobs/<job_id>` | Job status: `{id, status, progress, record, video_id, error, created_at, finished_at}` |
