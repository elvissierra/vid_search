-- 003_ownership: records and jobs belong to a user.
--
-- user_id is nullable: rows that existed before accounts have no owner and
-- stay reachable only without a login (the pre-accounts behavior). A record
-- label is now unique per owner instead of globally, so two users can both
-- have an "episode-1" and a label can never reveal another user's data.
-- COALESCE maps "no owner" to 0 so unowned labels stay unique among
-- themselves (a plain UNIQUE treats NULLs as distinct). Deleting a user
-- removes their records and jobs.

ALTER TABLE records ADD COLUMN user_id BIGINT REFERENCES users (id) ON DELETE CASCADE;
ALTER TABLE jobs    ADD COLUMN user_id BIGINT REFERENCES users (id) ON DELETE CASCADE;

ALTER TABLE records DROP CONSTRAINT records_pkey;
CREATE UNIQUE INDEX idx_records_owner_label ON records ((COALESCE(user_id, 0)), record);
CREATE INDEX idx_jobs_user ON jobs (user_id);
