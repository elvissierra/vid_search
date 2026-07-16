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

CREATE INDEX IF NOT EXISTS idx_transcripts_video ON transcripts (video_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_video_word ON transcripts (video_id, word);

-- ---------------------------------------------------------------------------
-- Migrating a pre-existing database (transcripts table created by hand,
-- before this file existed): run the statements below ONCE, then this file.
--
-- ALTER TABLE transcripts ADD COLUMN id BIGSERIAL PRIMARY KEY;
-- INSERT INTO records (record, video_id)
--     SELECT DISTINCT record, video_id FROM transcripts
--     ON CONFLICT (record) DO NOTHING;
-- ---------------------------------------------------------------------------
