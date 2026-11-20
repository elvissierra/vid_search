-- 008_segment_embeddings: one embedding per transcript segment, for semantic search.
--
-- 384 dimensions matches the sentence-transformers model in embeddings.py
-- (all-MiniLM-L6-v2); changing the model means a new migration that rebuilds
-- this table, since vectors from different models are not comparable.
--
-- There is deliberately no ANN (hnsw/ivfflat) index. Searches are always
-- restricted to the viewer's own recordings, and an ANN index applies that
-- filter after the nearest-neighbour scan, so a busy library elsewhere could
-- starve a user's results. The primary key (video_id first) lets the exact
-- cosine scan touch only the viewer's rows instead.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE segment_embeddings (
    video_id      TEXT NOT NULL,
    segment_index INT  NOT NULL,
    text          TEXT NOT NULL,
    start_time    DOUBLE PRECISION NOT NULL,
    end_time      DOUBLE PRECISION NOT NULL,
    embedding     vector(384) NOT NULL,
    PRIMARY KEY (video_id, segment_index)
);
