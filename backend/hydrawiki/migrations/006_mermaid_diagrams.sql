CREATE TABLE IF NOT EXISTS generation_diagrams (
    id UUID PRIMARY KEY,
    generation_run_id UUID NOT NULL REFERENCES generation_runs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0), source TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('safe', 'failed')), svg TEXT, error TEXT,
    CHECK ((status = 'safe' AND svg IS NOT NULL AND error IS NULL) OR (status = 'failed' AND svg IS NULL AND error IS NOT NULL)),
    UNIQUE (generation_run_id, ordinal)
);
CREATE INDEX IF NOT EXISTS generation_diagrams_run_idx ON generation_diagrams(generation_run_id, ordinal);
