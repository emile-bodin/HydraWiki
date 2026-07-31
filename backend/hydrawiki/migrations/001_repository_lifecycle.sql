CREATE TABLE IF NOT EXISTS repositories (
    id UUID PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (source_type IN ('local', 'public_git')),
    source_value TEXT NOT NULL,
    selected_ref TEXT,
    display_name TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK (lifecycle_status IN ('registered', 'deleting', 'delete_failed')),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id UUID PRIMARY KEY,
    repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    lifecycle_status TEXT NOT NULL CHECK (lifecycle_status IN ('queued', 'running', 'succeeded', 'failed')),
    phase TEXT NOT NULL,
    current_count INTEGER NOT NULL DEFAULT 0,
    total_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ingestion_runs_repository_id_idx ON ingestion_runs(repository_id);
