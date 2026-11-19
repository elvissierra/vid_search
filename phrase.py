"""Keyword and phrase lookup over transcripts.word_norm.

A keyword is split on whitespace and each piece is normalized in the database
with normalize_word(), the same function that fills transcripts.word_norm, so
both sides cannot drift. Pieces that normalize to nothing (a lone dash) are
dropped. One piece is the plain indexed word lookup; several pieces must
match consecutive words of the video, ordered by (start_time, id). Words with
an empty word_norm are skipped when walking forward, so punctuation tokens
never break a phrase. A phrase may span segment boundaries. The walk never
leaves a video, so one query can search several videos at once (search_many).
"""

MAX_PHRASE_WORDS = 10

_SQL = """
WITH RECURSIVE terms AS (
    SELECT w, row_number() OVER (ORDER BY n) AS pos
    FROM (
        SELECT normalize_word(t) AS w, n
        FROM unnest(%(pieces)s::text[]) WITH ORDINALITY AS u(t, n)
    ) normalized
    WHERE w <> ''
),
term_count AS (SELECT count(*) AS c FROM terms),
walk AS (
    SELECT t.video_id, t.id, t.start_time, t.end_time, t.speaker, t.word AS text,
           t.start_time AS first_start, t.speaker AS first_speaker, 1 AS pos
    FROM transcripts t
    JOIN terms ON terms.pos = 1 AND t.word_norm = terms.w
    WHERE t.video_id = ANY(%(video_ids)s::text[]) AND t.word_norm <> ''
  UNION ALL
    SELECT walk.video_id, nxt.id, nxt.start_time, nxt.end_time, nxt.speaker, walk.text || nxt.word,
           walk.first_start, walk.first_speaker, walk.pos + 1
    FROM walk
    JOIN terms ON terms.pos = walk.pos + 1
    JOIN LATERAL (
        SELECT id, start_time, end_time, speaker, word, word_norm
        FROM transcripts
        WHERE video_id = walk.video_id AND word_norm <> ''
          AND (start_time, id) > (walk.start_time, walk.id)
        ORDER BY start_time, id
        LIMIT 1
    ) nxt ON nxt.word_norm = terms.w
)
SELECT video_id, text, first_start, end_time, first_speaker
FROM walk, term_count
WHERE walk.pos = term_count.c
ORDER BY array_position(%(video_ids)s::text[], video_id), first_start, id
LIMIT %(limit)s
"""


def split_keyword(keyword):
    """Whitespace-separated pieces of a keyword."""
    return keyword.split()


def search_many(cursor, video_ids, keyword, limit=None):
    """Rows `(video_id, word, start, end, speaker)` for each occurrence of
    `keyword` across `video_ids`.

    Rows come in the order of `video_ids`, then by position in the video, and
    at most `limit` are returned (None = no cap). For a phrase, `word` is the
    matched words joined as spoken (whisper keeps the leading space of each
    word, so the pieces concatenate), trimmed; `start` and `speaker` come from
    its first word and `end` from its last. A single word is returned exactly
    as stored.
    """
    pieces = split_keyword(keyword)
    cursor.execute(_SQL, {"pieces": pieces, "video_ids": list(video_ids), "limit": limit})
    rows = cursor.fetchall()
    if len(pieces) > 1:
        rows = [(vid, text.strip(), start, end, speaker) for (vid, text, start, end, speaker) in rows]
    return rows


def search_words(cursor, video_id, keyword):
    """Rows `(word, start, end, speaker)` for each occurrence of `keyword` in
    one video; see search_many for the row shape."""
    return [row[1:] for row in search_many(cursor, [video_id], keyword)]
