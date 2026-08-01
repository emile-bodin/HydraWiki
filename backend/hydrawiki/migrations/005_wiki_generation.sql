CREATE TABLE IF NOT EXISTS generation_runs (
    id UUID PRIMARY KEY,
    repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    page_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    source_selection JSONB NOT NULL,
    generation_url TEXT,
    configured_model TEXT,
    provider_model TEXT,
    prompt_version TEXT NOT NULL,
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS generation_runs_repository_started_idx ON generation_runs(repository_id, started_at DESC);

CREATE TABLE IF NOT EXISTS generation_artifacts (
    id UUID PRIMARY KEY,
    generation_run_id UUID NOT NULL REFERENCES generation_runs(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN ('prompt', 'response', 'validation_error')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (generation_run_id, artifact_type)
);

CREATE TABLE IF NOT EXISTS wiki_pages (
    id UUID PRIMARY KEY,
    repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK (lifecycle_status = 'published'),
    generation_run_id UUID NOT NULL UNIQUE REFERENCES generation_runs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repository_id, path)
);

CREATE TABLE IF NOT EXISTS wiki_page_sources (
    wiki_page_id UUID NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
    repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    line_start INTEGER NOT NULL CHECK (line_start > 0),
    line_end INTEGER NOT NULL CHECK (line_end >= line_start),
    PRIMARY KEY (wiki_page_id, path, line_start, line_end)
);

CREATE INDEX IF NOT EXISTS wiki_page_sources_repository_path_idx ON wiki_page_sources(repository_id, path);
