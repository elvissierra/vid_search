# vid_search

Paste a video URL, get a searchable word-level transcript. Flask + Postgres
backend, Vue 3 (Vite) frontend. Audio is extracted with `yt-dlp` and
transcribed locally with OpenAI Whisper (word-level timestamps); every word is
stored as a row in Postgres so keyword search returns exact timestamps.

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

## Running

```bash
python routes.py            # API on http://localhost:5000
cd search_ui && npm run dev # UI on http://localhost:5173
```

## Environment variables

| File | Variable | Purpose |
|---|---|---|
| `.env` | `DB_NAME` `DB_USER` `DB_PASSWORD` `DB_HOST` `DB_PORT` | Postgres connection |
| `.env` | `CORS_ORIGINS` | Comma-separated allowed frontend origins |
| `search_ui/.env` | `VITE_API_URL` | API base URL for the frontend |

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/records` | List previously ingested record labels |
| POST | `/api/search` | Body `{url, record}`, query `?keyword=` — transcribes if the record is new, then searches. Returns `{video_id, results}` |
