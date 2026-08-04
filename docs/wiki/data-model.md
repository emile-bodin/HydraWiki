# Data model

[Index](README.md) · [Previous: API reference](api.md) · [Next: Frontend](frontend.md)

PostgreSQL is the **authoritative** store. Schema changes ship as ordered SQL migrations under `backend/hydrawiki/migrations/`. `Database.migrate()` applies them; `verify_schema_compatible()` guards process startup.

## Migration map

| File | Introduces |
|------|------------|
| `001_repository_lifecycle.sql` | `repositories`, early `ingestion_runs`, `repository_deletion_receipts` |
| `002_manifest_delta.sql` | `manifest_runs`, `content_cache`, `source_files`, `manifest_entries` |
| `003_chunk_vectors.sql` | `index_versions`, `chunks`, progress columns on `manifest_runs` |
| `004_atomic_replacements.sql` | Staged index replacement bookkeeping |
| `005_wiki_generation.sql` | `generation_runs`, `generation_artifacts`, `wiki_pages`, `wiki_page_sources` |
| `006_mermaid_diagrams.sql` | `generation_diagrams` |
| `007_generation_failure_stage.sql` | `failure_stage` on generation runs |

Qdrant holds **derived** vectors keyed with repository/chunk identity metadata; vector IDs are referenced from `chunks.vector_id`.

## Core entities

### `repositories`

| Column | Notes |
|--------|--------|
| `id` | UUID PK |
| `source_type` | `local` \| `public_git` |
| `source_value` | Relative path or Git URL |
| `selected_ref` | Git ref or null |
| `display_name` | Operator label |
| `lifecycle_status` | `registered` \| `deleting` \| `delete_failed` |
| `last_error` | Last repository-level error |
| timestamps | `created_at`, `updated_at` |

### `repository_deletion_receipts`

Idempotent proof of completed deletion (identity fields + `deleted_at`).

### Manifest and sources

**`manifest_runs`** — per sync attempt: status, parser version, file counts/bytes, phase/progress, error, timestamps.

**`content_cache`** — reusable normalized text keyed by `(content_sha256, parser_version)` with `line_count` and `byte_size`.

**`source_files`** — current inventory per `(repository_id, path)` pointing at cache + last manifest run.

**`manifest_entries`** — per-run classification rows: `new` \| `changed` \| `unchanged` \| `missing`.

### Indexing

**`index_versions`** — embedding model name, optional verified `vector_dimension`, timestamps.

**`chunks`** — chunk text, line range, hashes, chunker/embedding/index versions, unique `vector_id`.

Uniqueness includes repository, path, content hash, ordinal, chunker, embedding model, and index version so version bumps do not silently collide.

**Index replacement tables** (migration 004) track staged and old vector IDs for crash-safe swaps and recovery.

### Wiki generation

**`generation_runs`**

- `page_path`, `status` (`running` \| `succeeded` \| `failed`)
- `source_selection` JSONB
- `generation_url`, `configured_model`, `provider_model`
- `prompt_version`, `error`, `failure_stage`
- timestamps

**`generation_artifacts`** — `prompt` \| `response` \| `validation_error` content (unique per run + type).

**`wiki_pages`**

- Unique `(repository_id, path)`
- `lifecycle_status` must be `published`
- `generation_run_id` unique FK to the producing run
- `content`, `title`

**`wiki_page_sources`** — citation rows: path + inclusive line range; PK includes those fields.

**`generation_diagrams`** — ordinal Mermaid outcomes with XOR constraint on safe SVG vs failed error.

## Cascades and delete

Repository delete is intended to remove:

- Relational children via `ON DELETE CASCADE` from `repositories`
- Qdrant vectors listed for the repository
- Workspace directory for the repository id
- Deletion receipt written on successful completion

Partial failure surfaces as `delete_failed` with error text rather than a silent success.

## Early `ingestion_runs` vs `manifest_runs`

Migration 001 created an `ingestion_runs` lifecycle table used in early phase design. The implemented sync path centers on **`manifest_runs`** (with phase/progress columns from migration 003) exposed through API models named `ManifestRunResponse` and routes under `/ingestion-runs` for operator familiarity. When reading schema or tests, treat manifest runs as the durable sync progress source of truth for current behavior.

## Relationship sketch

```text
repositories
 ├── manifest_runs
 │     └── manifest_entries
 ├── source_files ──► content_cache
 ├── chunks ──► index_versions (+ qdrant via vector_id)
 ├── generation_runs
 │     ├── generation_artifacts
 │     └── generation_diagrams
 └── wiki_pages
       └── wiki_page_sources
```

## Next

- [Ingestion](ingestion.md) — how rows are written
- [Wiki generation](generation.md) — publish rules
- [Operations](operations.md) — backup of PG + Qdrant + workspace
