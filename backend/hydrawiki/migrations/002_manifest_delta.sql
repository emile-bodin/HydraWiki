CREATE TABLE IF NOT EXISTS manifest_runs (
    id UUID PRIMARY KEY,
    repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    parser_version TEXT NOT NULL,
    file_count INTEGER NOT NULL DEFAULT 0,
    total_bytes BIGINT NOT NULL DEFAULT 0,
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS manifest_runs_repository_id_idx ON manifest_runs(repository_id, started_at DESC);

CREATE TABLE IF NOT EXISTS content_cache (
    id UUID PRIMARY KEY,
    content_sha256 TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    normalized_content TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    line_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (content_sha256, parser_version)
);

CREATE TABLE IF NOT EXISTS source_files (
    repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    content_cache_id UUID NOT NULL REFERENCES content_cache(id),
    parser_version TEXT NOT NULL,
    last_manifest_run_id UUID NOT NULL REFERENCES manifest_runs(id),
    PRIMARY KEY (repository_id, path)
);

CREATE INDEX IF NOT EXISTS source_files_cache_id_idx ON source_files(content_cache_id);

CREATE TABLE IF NOT EXISTS manifest_entries (
    manifest_run_id UUID NOT NULL REFERENCES manifest_runs(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    content_sha256 TEXT,
    byte_size INTEGER,
    classification TEXT NOT NULL CHECK (classification IN ('new', 'changed', 'unchanged', 'missing')),
    PRIMARY KEY (manifest_run_id, path)
);

CREATE INDEX IF NOT EXISTS manifest_entries_run_classification_idx ON manifest_entries(manifest_run_id, classification);
