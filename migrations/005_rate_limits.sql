-- 005_rate_limits: fixed-window request counters for rate limiting.
--
-- One row per (bucket, key, window): bucket names the limited action
-- ("search", "ingest"), key identifies the caller ("user:<id>" or
-- "ip:<addr>"), window_start is the start of the one-minute window. Counting
-- in Postgres keeps the limit correct across several api processes. Old
-- windows are pruned opportunistically by ratelimit.py.

CREATE TABLE rate_limits (
    bucket       TEXT        NOT NULL,
    key          TEXT        NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    hits         INTEGER     NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket, key, window_start)
);

-- Serves the pruning of expired windows.
CREATE INDEX idx_rate_limits_window ON rate_limits (window_start);
