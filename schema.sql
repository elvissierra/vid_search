-- vid_search schema — idempotent, safe to re-apply:
--   psql -d $DB_NAME -f schema.sql

-- One row per ingested video/episode. The primary key on record is what
-- prevents two concurrent submissions of the same label from both
-- transcribing (reserve via INSERT ... ON CONFLICT DO NOTHING).
CREATE TABLE IF NOT EXISTS records (
    record      TEXT PRIMARY KEY,
    video_id    TEXT NOT NULL UNIQUE,
    source_url  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per transcribed word.
CREATE TABLE IF NOT EXISTS transcripts (
    id           BIGSERIAL PRIMARY KEY,
    video_id     TEXT NOT NULL,
    record       TEXT NOT NULL,
    segment_text TEXT,
    word         TEXT,
    start_time   DOUBLE PRECISION,
    end_time     DOUBLE PRECISION
);

-- Speaker diarization (pyannote): label per word + segment ordinal for
-- reconstructing segments later (exports).
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS segment_index INT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speaker TEXT;

CREATE INDEX IF NOT EXISTS idx_transcripts_video ON transcripts (video_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_video_word ON transcripts (video_id, word);

-- Transcription work queue. The API inserts a queued row and returns 202;
-- worker.py claims rows with FOR UPDATE SKIP LOCKED and processes them.
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'running', 'done', 'error')),
    progress      INT  NOT NULL DEFAULT 0,
    record        TEXT NOT NULL,
    url           TEXT,
    upload_path   TEXT,
    language      TEXT,
    video_id      TEXT,
    error         TEXT,
    audio_seconds DOUBLE PRECISION,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs (status, created_at);

-- ---------------------------------------------------------------------------
-- Migrating a pre-existing database (transcripts table created by hand,
-- before this file existed): run the statements below ONCE, then this file.
--
-- ALTER TABLE transcripts ADD COLUMN id BIGSERIAL PRIMARY KEY;
-- INSERT INTO records (record, video_id)
--     SELECT DISTINCT record, video_id FROM transcripts
--     ON CONFLICT (record) DO NOTHING;
-- ---------------------------------------------------------------------------
