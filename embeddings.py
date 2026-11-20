"""Segment embeddings and semantic search (pgvector).

The worker embeds each transcript segment when a job finishes; the API embeds
the query and ranks the viewer's segments by cosine similarity. The model is
loaded lazily, so importing this module (the API does) never pulls in torch.

Run `python embeddings.py backfill` to embed recordings transcribed before
this existed, or whose embedding step failed.
"""
import sys

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSIONS = 384  # keep in step with migrations/008_segment_embeddings.sql
BATCH_SIZE = 64

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(texts):
    """Unit-length vectors (lists of floats), one per text."""
    vectors = _get_model().encode(
        list(texts), batch_size=BATCH_SIZE, normalize_embeddings=True, show_progress_bar=False
    )
    return [[float(x) for x in v] for v in vectors]


def vector_literal(vector):
    """pgvector's text form, so no client-side adapter package is needed."""
    if len(vector) != DIMENSIONS:
        raise ValueError(f"expected {DIMENSIONS} dimensions, got {len(vector)}")
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def store(cursor, video_id, segments):
    """Insert (segment_index, text, start, end, vector) tuples for a video."""
    from psycopg2.extras import execute_values
    if not segments:
        return
    execute_values(
        cursor,
        """
        INSERT INTO segment_embeddings (video_id, segment_index, text, start_time, end_time, embedding)
        VALUES %s
        ON CONFLICT (video_id, segment_index) DO NOTHING;
        """,
        [(video_id, i, text, start, end, vector_literal(vec)) for (i, text, start, end, vec) in segments],
        template="(%s, %s, %s, %s, %s, %s::vector)",
    )


def search(cursor, video_ids, query_vector, limit):
    """The `limit` segments of `video_ids` closest to query_vector, best first.

    Returns (video_id, text, start, end, similarity) with similarity the
    cosine similarity (1 = same direction).
    """
    if not video_ids:
        return []
    literal = vector_literal(query_vector)
    cursor.execute(
        """
        SELECT video_id, text, start_time, end_time, 1 - (embedding <=> %s::vector) AS similarity
        FROM segment_embeddings
        WHERE video_id = ANY(%s)
        ORDER BY embedding <=> %s::vector, video_id, segment_index
        LIMIT %s;
        """,
        (literal, list(video_ids), literal, limit),
    )
    return cursor.fetchall()


def backfill(get_conn=None):
    """Embed every transcribed segment that has no embedding yet. Returns the count."""
    if get_conn is None:
        from db import get_conn
    done = 0
    while True:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT t.video_id, t.segment_index, min(t.segment_text),
                           min(t.start_time), max(t.end_time)
                    FROM transcripts t
                    WHERE t.segment_index IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM segment_embeddings e
                          WHERE e.video_id = t.video_id AND e.segment_index = t.segment_index)
                    GROUP BY t.video_id, t.segment_index
                    HAVING btrim(coalesce(min(t.segment_text), '')) <> ''
                    ORDER BY t.video_id, t.segment_index
                    LIMIT %s;
                    """,
                    (BATCH_SIZE,),
                )
                rows = cursor.fetchall()
                if not rows:
                    return done
                vectors = embed([r[2].strip() for r in rows])
                for (video_id, index, text, start, end), vec in zip(rows, vectors):
                    store(cursor, video_id, [(index, text.strip(), start, end, vec)])
                done += len(rows)


if __name__ == "__main__":
    if sys.argv[1:] == ["backfill"]:
        print(f"Embedded {backfill()} segment(s)")
    else:
        sys.exit("usage: python embeddings.py backfill")
