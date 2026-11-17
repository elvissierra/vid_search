-- 006_word_norm_index: indexed word lookup.
--
-- Search used to run `word ~* '\mkeyword\M'` against every row of a video,
-- which no index can serve. Whisper stores tokens as spoken text (" Hello,"),
-- so the lookup is made indexable by comparing a normalized form instead:
-- lowercased, curly apostrophes folded to ASCII, edge whitespace and
-- punctuation stripped. The same function normalizes the stored word (a
-- generated column) and the search keyword, so the two cannot drift apart.

CREATE FUNCTION normalize_word(w TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
AS $$
    SELECT lower(regexp_replace(
        translate(w, '’‘', ''''''),
        '^[[:space:][:punct:]¿¡“”«»…—–]+|[[:space:][:punct:]¿¡“”«»…—–]+$',
        '',
        'g'
    ))
$$;

ALTER TABLE transcripts
    ADD COLUMN word_norm TEXT GENERATED ALWAYS AS (normalize_word(word)) STORED;

-- Serves WHERE video_id = ? AND word_norm = ? ORDER BY start_time. It also
-- covers the video_id prefix, and replaces the (video_id, word) index, which
-- the regex search could never use.
CREATE INDEX idx_transcripts_video_word_norm ON transcripts (video_id, word_norm, start_time);
DROP INDEX IF EXISTS idx_transcripts_video_word;
