CREATE TABLE IF NOT EXISTS index_replacements (
    run_id UUID PRIMARY KEY REFERENCES manifest_runs(id) ON DELETE CASCADE,
    repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('staging', 'activating', 'retiring', 'succeeded', 'failed', 'recoverable')),
    staged_vector_ids TEXT[] NOT NULL DEFAULT '{}',
    old_vector_ids TEXT[] NOT NULL DEFAULT '{}',
    promotion_complete BOOLEAN NOT NULL DEFAULT FALSE,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staged_chunks (
    replacement_run_id UUID NOT NULL REFERENCES index_replacements(run_id) ON DELETE CASCADE,
    id UUID PRIMARY KEY,
    repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    chunk_sha256 TEXT NOT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    chunker_version TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    index_version TEXT NOT NULL,
    vector_id TEXT NOT NULL UNIQUE
);

ALTER TABLE manifest_entries ADD COLUMN IF NOT EXISTS content_cache_id UUID REFERENCES content_cache(id);
ALTER TABLE index_replacements ADD COLUMN IF NOT EXISTS promotion_complete BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS index_replacements_repository_status_idx ON index_replacements(repository_id, status);
