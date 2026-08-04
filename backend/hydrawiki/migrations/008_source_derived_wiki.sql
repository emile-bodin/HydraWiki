ALTER TABLE generation_runs
    ADD COLUMN IF NOT EXISTS wiki_structure JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE wiki_pages
    DROP CONSTRAINT IF EXISTS wiki_pages_generation_run_id_key;

ALTER TABLE wiki_pages
    ADD COLUMN IF NOT EXISTS navigation_group TEXT NOT NULL DEFAULT 'get-started',
    ADD COLUMN IF NOT EXISTS navigation_order INTEGER NOT NULL DEFAULT 0;

ALTER TABLE generation_diagrams
    ADD COLUMN IF NOT EXISTS page_path TEXT;
