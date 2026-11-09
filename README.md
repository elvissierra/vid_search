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
cp .env.example .env                     # then fill in DB credentials
python migrate.py                        # create/upgrade the schema, re-run any time

# Frontend
cd search_ui
npm install
cp .env.example .env
```

### Database migrations

The schema lives in [migrations/](migrations/) as numbered SQL files
(`001_baseline.sql`, `002_….sql`, …). `python migrate.py` applies the ones not
yet recorded in the `schema_migrations` table, each in its own transaction, so
it is safe to run on a fresh database, an existing one, or repeatedly.

To change the schema, add the next numbered file. Never edit one that has
already been applied.

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
just stay queued. Downloaded and uploaded audio is deleted after each job.

In the UI, drop an audio or video file onto the upload box (or click it to browse) instead of entering a URL. The file is posted to `/api/upload` with a progress bar, then the job is polled like any other. If no record label is given, the file name is used. The accepted types mirror the backend allow-list; the size limit is enforced by the API (`MAX_UPLOAD_MB`).

### Docker

One command runs the whole stack (Postgres, migrations, API, worker, UI):

```bash
docker compose up --build
```

The UI is at http://localhost:8080 and the API at http://localhost:5000. A one-shot `migrate` service applies `migrations/` before the API and worker start. The backend image installs the full `requirements.txt` (CPU-only torch) plus ffmpeg; Whisper and pyannote checkpoints are cached in the `model_cache` volume and the database in `pgdata`; uploads live in the shared `uploads` volume (limit via `MAX_UPLOAD_MB`). Set `HF_TOKEN` (shell or a compose `.env`) for diarization. Other overrides: `DB_PASSWORD`, `API_PORT`, `UI_PORT`, `VITE_API_URL` (baked into the UI at build time, so rebuild after changing it).

## Environment variables

| File | Variable | Purpose |
|---|---|---|
| `.env` | `DB_NAME` `DB_USER` `DB_PASSWORD` `DB_HOST` `DB_PORT` | Postgres connection |
| `.env` | `CORS_ORIGINS` | Comma-separated allowed frontend origins |
| `.env` | `UPLOAD_DIR` | Where uploaded files are stored (default `uploads/`); API and worker must share it |
| `.env` | `MAX_UPLOAD_MB` | Upload size limit in MB (default `500`) |
| `.env` | `HF_TOKEN` | Hugging Face token for pyannote diarization models |
| `search_ui/.env` | `VITE_API_URL` | API base URL for the frontend |

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/records` | List the viewer's previously ingested record labels |
| POST | `/api/search` | Body `{url, record, keyword, language?}`. `language` is a whisper code or name (`es`, `Spanish`); omitted or `auto` detects it, anything else unsupported is `400`. It applies when a new record is queued. Existing record → `200` `{video_id, results: [{word, start, end, speaker}]}`. New record → job queued, `202` `{job_id, record}` (or `409` if the label is taken) |
| POST | `/api/upload` | Multipart form: `file` (audio/video: mp3, wav, m4a, aac, flac, ogg, opus, wma, mp4, mov, mkv, webm, avi, m4v), `record`, optional `language` (same rules as `/api/search`). Stored under a server-generated name in `UPLOAD_DIR` and queued via `jobs.upload_path`; the worker deletes it after the job. `202` `{job_id, record}`; `400` bad type/missing file/record/language; `409` label taken; `413` over `MAX_UPLOAD_MB` |
| POST | `/api/signup` | Body `{email, password}` (password 8-128 characters; email is lowercased). `201` `{user: {id, email}, token}`; `400` invalid email/password; `409` email already registered. Send the token as `Authorization: Bearer <token>`. Passwords are stored as scrypt hashes and only the sha256 of each token is stored; sessions last 30 days |
| POST | `/api/login` | Body `{email, password}`. `200` `{user, token}` (a new session each time); `401` for bad credentials, with the same answer for an unknown email |
| POST | `/api/logout` | Revokes the bearer token used. `204`; `401` if not logged in |
| GET | `/api/me` | The logged-in user `{user: {id, email}}`; `401` without a valid token |
| GET | `/api/jobs/<job_id>` | Job status (`404` for another owner's job): `{id, status, progress, record, video_id, error, created_at, finished_at}` |
| GET | `/api/export/<video_id>?format=` | Transcript as `srt`, `vtt`, `txt` (default) or `json`; `404` unless the viewer owns the record |

### Ownership

Records and jobs belong to the user whose bearer token created them, and every records, search, upload, job and export endpoint only sees the viewer's own rows. A label is unique per owner, so two users can each have an `episode-1`. A request without an `Authorization` header is anonymous and only sees rows that have no owner (everything ingested before accounts existed); a header whose token is invalid or expired is `401`, never a silent fall back to anonymous. Another owner's job or export is `404`, the same as one that does not exist.

## Tests

The suite includes db-backed tests for the job queue and record reservation, which need a real Postgres. Point the `DB_*` variables at a scratch database, then:

```
python migrate.py
pytest
```

Without `DB_NAME` set, the db-backed tests are skipped. The tests only need the light dependencies in `requirements-ci.txt`; the ML packages are imported lazily and are not required.

GitHub Actions (`.github/workflows/ci.yml`) runs `migrate.py` and `pytest` against a Postgres 16 service with `DB_NAME` set, so the db-backed tests run rather than skip, and builds the UI with `npm run build`.
