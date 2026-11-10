-- 004_usage_ledger: per-user transcription usage, derived from jobs.
--
-- The worker records jobs.audio_seconds once a file is transcribed (whisper
-- has spent the time even if diarization later fails), so every job with a
-- value is one ledger entry. A view keeps the ledger a read-only projection
-- of jobs: there is no second table to drift out of sync. Unowned (pre-
-- accounts) jobs are not metered and are left out.

CREATE VIEW usage_ledger AS
SELECT id AS job_id, user_id, record, audio_seconds, created_at
FROM jobs
WHERE user_id IS NOT NULL AND audio_seconds IS NOT NULL;

-- Serves the monthly sum per user.
CREATE INDEX idx_jobs_usage ON jobs (user_id, created_at) WHERE audio_seconds IS NOT NULL;
