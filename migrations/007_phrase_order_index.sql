-- 007_phrase_order_index: ordered word walk for phrase search.
--
-- Phrase search finds the rows that match the first word, then repeatedly
-- asks "what is the next word after this one?": the first row of the same
-- video, past (start_time, id), whose normalized form is not empty. This
-- index serves that lookup in order with no sort, one index probe per step.
-- Rows with an empty word_norm (stand-alone dashes, ellipses) are left out;
-- phrase search skips over them, the same way it ignores punctuation inside
-- a keyword.

CREATE INDEX idx_transcripts_video_order ON transcripts (video_id, start_time, id)
    WHERE word_norm <> '';
