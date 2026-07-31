# HydraWiki implementation plan

Status: proposed; no implementation has started.

## Purpose

HydraWiki will be a self-hosted, Docker-based code documentation platform for local and public repositories. It combines the useful ideas from RepoWiki and deepwiki-open, but is designed around persistent lifecycle management, truthful errors, and incremental indexing.

External services are existing dependencies and are not installed or replaced by HydraWiki:

- Generation: LiteLLM at `http://192.168.86.75:4000/v1`, with configurable model alias such as `chatgpt`.
- Embeddings: Ollama on GPU host `192.168.86.74`.

## MVP scope

1. Register local repositories through an explicitly allowlisted, read-only Docker bind mount.
2. Register public Git repositories by URL and selected ref.
3. Persist repository metadata, ingestion runs, source-file inventory, chunks, wiki pages, citations and errors across restarts.
4. Incrementally process only new, changed and deleted files; reuse unchanged content through SHA-256 content hashes.
5. Show repositories, status, numeric ingestion progress and actual errors in the web UI.
6. Publish wiki pages only after successful generation, source citation and Mermaid validation. Never create placeholder wiki content on failure.
7. Show source paths and line ranges per wiki page.
8. Delete a repository through an idempotent job that removes relational data, vector data, wiki data and workspace/cache data.

Excluded from MVP: private Git credentials, multi-user authorization, automatic schedules/webhooks, cross-repository search and multi-agent documentation generation.

## Architecture

- React + TypeScript frontend
- FastAPI API and separate ingestion worker
- PostgreSQL as the source of truth
- Qdrant as the derived vector store
- External LiteLLM generation adapter
- External Ollama embedding adapter
- Docker Compose for HydraWiki services only

Compose must persist PostgreSQL, Qdrant and ingestion workspace/cache volumes. Local repository paths are accepted only below `LOCAL_REPOSITORIES_ROOT`; path traversal and arbitrary host paths are rejected.

## Persistent data model

| Entity | Purpose |
|---|---|
| `repositories` | source type, URL/path, ref, status and last successful sync |
| `ingestion_runs` | run lifecycle, phase, current, total, percentage and failure |
| `file_versions` | canonical path, SHA-256, language, size, line metadata and removal state |
| `content_cache` | reusable normalized content keyed by content hash plus parser/chunker version |
| `chunks` | chunk text, line range, hashes, embedding model version and vector ID |
| `wiki_pages` | generated page content, lifecycle status and generation version |
| `wiki_page_sources` | page-to-file/chunk source citations and line ranges |
| `generation_artifacts` | model/prompt version, Mermaid source, validation status and error |
| `ingestion_events` | durable progress, warning and error event history |

All schema changes use versioned migrations. Vector metadata always includes repository ID and chunk ID.

## Delta-indexing contract

Each successful run creates a manifest of eligible source files and their SHA-256 hashes.

| Manifest result | Required action |
|---|---|
| New path | Parse, chunk, embed and regenerate affected pages |
| Existing path with changed hash | Replace old chunks/vectors and regenerate affected pages |
| Missing former path | Remove file/chunks/vectors and stale citations |
| Same path and hash | Reuse stored content, chunks and vectors; do not re-embed |

Cache keys also include parser, chunker, embedding-model and generation-prompt versions. A source scan must complete successfully before deletions are committed; a failed scan never removes valid prior data.

## API contract

- `POST /api/repositories`
- `GET /api/repositories`
- `GET /api/repositories/{id}`
- `POST /api/repositories/{id}/sync`
- `GET /api/ingestion-runs/{id}`
- `GET /api/ingestion-runs/{id}/events` (polling or SSE)
- `GET /api/repositories/{id}/pages`
- `GET /api/repositories/{id}/pages/{path}`
- `DELETE /api/repositories/{id}`

Ingestion status always contains a durable phase, current, total and percentage, for example: `Embedding changed chunks — 19 / 56 — 34%`. Delete lifecycle is `deleting` → `deleted` or `delete_failed`; the UI must not claim success early.

## Frontend requirements

- Repository list with source, type, ref, status, last success and real error.
- Safe add-repository form for local mount or public Git URL.
- Per-run numeric progress: phase, current, total and percentage.
- Wiki navigation with available, processing and failed states.
- Clickable source citations such as `src/api/routes.py:42–78`.
- Mermaid output only when server-side validation passed; otherwise show validation failure and original diagram source.

## Adapters and safety

The LiteLLM adapter uses OpenAI-compatible requests with configurable endpoint/model, timeouts, retries and normalized errors. The Ollama adapter is embeddings-only and persists model name/vector dimension with the index version.

Missing configuration, unavailable services or unknown models fail the run visibly. A page is `published` only after generation, source citations and Mermaid validation succeed.

Untrusted code and Markdown require source path restrictions, HTML sanitization and isolated Mermaid rendering. Mermaid must be parsed/validated server-side before safe SVG publication; client rendering is not the only validation layer.

## Reference boundaries

RepoWiki is a reference for source filtering, local/Git ingestion and dependency-graph patterns. deepwiki-open is a reference for OpenAI-compatible LiteLLM handling and line-aware splitting. Both are MIT licensed; any direct code reuse retains required copyright and license notices.

Do not adopt their in-memory/simple-cache job lifecycle, file/pickle index existence checks, placeholder fallbacks or non-durable progress semantics.

## Implementation phases

1. **Foundation and contracts** — repository layout, Compose skeleton, typed configuration validation, health checks, empty frontend shell and API contract; no AI generation.
2. **Persistent repository lifecycle** — PostgreSQL migrations, local/public source adapters, repository UI and safe delete job.
3. **Manifest and delta engine** — hashing, content cache, new/changed/deleted/unchanged actions and deletion guarantees.
4. **Chunking, embeddings and vectors** — Qdrant, Ollama adapter, index versions and integration coverage.
5. **Wiki generation and provenance** — LiteLLM adapter, pages, citations, line ranges and truthful failure states.
6. **Operator experience** — repository overview, live progress, errors, wiki navigation and source viewer.
7. **Mermaid hardening** — server-side validation/rendering and regression suite.
8. **Operational readiness** — backup/restore runbook, migration checks, Docker restart tests, capacity tests and security review.

## Test strategy

- Unit: hash classification, path normalization, cache invalidation, deletion logic, source-line mapping and Mermaid validation.
- Database: migrations and cascades.
- Integration: local and Git fixtures across first ingest, change, add, delete and unchanged reuse.
- Adapter contracts: LiteLLM/Ollama success and error cases with mocks.
- Docker: restart during/after ingestion while data and index persist.
- End-to-end: add → progress → cited wiki → delete → confirm metadata/vectors/pages are absent.
- Negative: invalid Git URL, unavailable model, invalid Mermaid, corrupt source and denied local path.

## Backup and migration

Before a schema upgrade, take a PostgreSQL backup and Qdrant snapshot. PostgreSQL remains authoritative; vectors can be rebuilt from stored chunks but are backed up to avoid costly re-embedding. Restore verifies compatibility before startup. Local repositories remain host-owned source data, not HydraWiki backup data.

## Decisions required before implementation

1. Confirm Qdrant rather than pgvector.
2. Define permitted local repository root(s) and Docker permissions.
3. Specify Ollama embedding model, endpoint format and vector dimension.
4. Validate LiteLLM authentication and the `chatgpt` model alias.
5. Define repository size/concurrency limits and expected generation budget.
