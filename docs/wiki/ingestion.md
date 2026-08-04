# Ingestion

[Index](README.md) · [Previous: Repositories and sources](repositories-and-sources.md) · [Next: Wiki generation](generation.md)

## Purpose

Ingestion turns a registered repository into a durable, hash-addressed inventory of source files and indexed chunks. Unchanged content is reused; only new, changed, and deleted paths force rework.

Entry point: `POST /api/repositories/{repository_id}/sync` → `run_manifest` in `manifest.py`, which also drives indexing via `index_manifest` in `indexing.py`.

## High-level phases

```text
Acquire ingest slot / repo lease
        │
        ▼
Resolve source root (local path or workspace)
        │
        ▼
Discover eligible files + size gates
        │
        ▼
Classify vs previous successful inventory
   new | changed | unchanged | missing
        │
        ▼
Apply delta (cache, source_files, manifest_entries)
        │
        ▼
Index new/changed (chunk → embed → Qdrant replace)
        │
        ▼
Mark run succeeded/failed with durable progress
```

Progress is exposed on manifest runs as:

- `phase` (string)
- `current_count` / `total_count`
- `percentage` (0–100)
- `status`: `running` | `succeeded` | `failed`
- `error` when failed

## Eligible sources

### File suffixes

From `ELIGIBLE_SUFFIXES` in `manifest.py`:

`.c .cc .cpp .css .go .h .hpp .html .java .js .json .jsx .md .py .rb .rs .sh .sql .toml .ts .tsx .txt .yaml .yml`

### Ignored directories

`.git`, `.hg`, `.svn`, `node_modules`, `__pycache__`, `.venv`, `venv`

### Walk safety

- Does not follow directory or file symlinks
- Rejects unsafe relative paths (`normalize_relative_path`)
- Parser version stamped on cache rows: `text-v1`

## Workload gates

Configurable settings (see [Configuration](configuration.md)):

| Gate | Default | Effect |
|------|--------:|--------|
| `max_repository_size_bytes` | 1 GiB | Total on-disk size of regular files under the source root |
| `max_total_indexable_text_bytes` | 100 MiB | Bound on eligible text content |
| `max_source_files` | 25,000 | Max eligible file count |
| `max_source_file_size_bytes` | 2 MiB | Per-file cap |

A failed scan must not commit destructive deletes of still-valid prior inventory (delta contract: complete successful scan before missing-path removal is durable).

## Delta classification

`classify` compares the discovered set to the current repository inventory:

| Classification | Meaning | Typical action |
|----------------|---------|----------------|
| `new` | Path not previously tracked | Cache, chunk, embed, store vectors |
| `changed` | Path exists but content SHA-256 differs | Replace chunks/vectors for that path |
| `unchanged` | Same path and hash | Reuse `content_cache`, chunks, vectors; do not re-embed |
| `missing` | Previously tracked path absent now | Remove file/chunk/vector data after successful scan |

Content identity is **SHA-256** of file bytes (normalized content stored with parser version in `content_cache`).

Cache uniqueness: `(content_sha256, parser_version)`.

## Chunking

Module: `chunking.py`, function `chunk_content`.

Defaults from settings:

- `chunker_version`: `line-size-v2`
- `chunk_max_lines`: 80
- `embedding_max_input_characters`: 4000 (also used as chunk character bound in indexing)

Behavior:

- Split on lines while respecting max lines and max characters
- Oversized single lines are hard-split by character window
- Each chunk records `ordinal`, `line_start`, `line_end`, and `content_hash` (SHA-256 of chunk text)

## Embeddings

Adapter: `OllamaEmbeddingAdapter` (`embeddings.py`).

- POST `{ollama_url}/api/embeddings` with `model` and `prompt`
- Failures normalized to `EmbeddingError` (timeout, unavailable, HTTP error, malformed body)
- Model and dimension are associated with `index_versions`; dimension is verified on successful embedding use and stored with the index version
- Changing embedding model or dimension requires reindexing (product rule)

Concurrency: up to `embedding_max_concurrency` (default 2, max 2) via advisory locks inside indexing.

## Vectors and atomic replacement

- Store: Qdrant (`vectors.py`), collection usage coordinated by indexing
- Chunks table holds `vector_id` and embedding/index version metadata
- `index_replacements` tracks staged vs old vector IDs for crash-safe replacement
- `recover_replacements` finishes post-commit cleanup or drops pre-commit staged vectors

## Concurrency and busy behavior

- Global ingest slots: `ingest_max_concurrency` (default 1, max 2)
- Repository-specific lease so raising the global bound cannot overlap source updates for one repository
- When no slot is available: `ManifestBusyError` → API **409 Conflict**

## Worker process

`python -m hydrawiki.worker`:

- Validates settings at startup
- Verifies schema compatibility
- Exposes `execute_manifest` as the shared worker boundary
- Current loop sleeps periodically (API path also runs `run_manifest` on sync)

Compose runs both `api` and `worker` with the same backend image and shared database/Qdrant/workspace configuration.

## Observability for operators

| Endpoint | Use |
|----------|-----|
| `GET /api/repositories/{id}/ingestion-runs` | History with phase and numeric progress |
| `GET /api/ingestion-runs/{id}` | Single run |
| `GET /api/ingestion-runs/{id}/entries` | Manifest entry classifications |
| `GET /api/repositories/{id}/sources/{path}` | Read **indexed** source content only |

The UI polls ingestion runs about every 1.5s while a run is active.

## Relation to wiki generation

Generation requires indexed chunks. The operator UI enables generate when:

- `last_successful_processing_at` is set on the repository, or
- at least one ingestion run has `status === "succeeded"`

See [Wiki generation](generation.md).

## Next

- [Wiki generation](generation.md)
- [Data model](data-model.md)
