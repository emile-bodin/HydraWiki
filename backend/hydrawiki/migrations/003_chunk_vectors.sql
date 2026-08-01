CREATE TABLE IF NOT EXISTS index_versions (
    index_version TEXT PRIMARY KEY,
    embedding_model TEXT NOT NULL,
    vector_dimension INTEGER,
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
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
    index_version TEXT NOT NULL REFERENCES index_versions(index_version),
    vector_id TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repository_id, path, content_sha256, ordinal, chunker_version, embedding_model, index_version)
);

CREATE INDEX IF NOT EXISTS chunks_repository_path_idx ON chunks(repository_id, path);

ALTER TABLE manifest_runs ADD COLUMN IF NOT EXISTS phase TEXT NOT NULL DEFAULT 'Manifest';
ALTER TABLE manifest_runs ADD COLUMN IF NOT EXISTS current_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE manifest_runs ADD COLUMN IF NOT EXISTS total_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE manifest_runs ADD COLUMN IF NOT EXISTS percentage INTEGER NOT NULL DEFAULT 0 CHECK (percentage BETWEEN 0 AND 100);
