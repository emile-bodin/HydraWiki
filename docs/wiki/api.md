# API reference

[Index](README.md) · [Previous: Mermaid](mermaid.md) · [Next: Data model](data-model.md)

This page describes the **implemented** FastAPI surface in `backend/hydrawiki/api.py`. Older “reserved only” notes in early contract sections are historical for Phase 1; the routes below are live in the current tree.

Base URL inside Compose: container port **8000** (host default **8191** via `HYDRAWIKI_API_PORT`). Frontend on **8080** proxies same-origin `/api` and health.

## Health

### `GET /health/live`

Process liveness.

Example shape:

```json
{
  "status": "ok",
  "service": "HydraWiki",
  "checks": { "process": "ok" }
}
```

### `GET /health/ready`

Configuration readiness (typed settings loaded). Exposes non-secret concurrency values. Returns **503** on readiness failure.

Includes checks such as configuration ok and effective:

- `embedding_max_concurrency`
- `ingest_max_concurrency`
- `generation_max_concurrency`

Phase-1 style readiness does not require live probes of Postgres/Qdrant/LiteLLM/Ollama for the basic configuration gate; persistence work assumes those services when handling application routes.

## Repositories

### `POST /api/repositories` → 201

Body (`RepositoryRegistration`):

| Field | Type | Notes |
|-------|------|-------|
| `source_type` | `"local"` \| `"public_git"` | Required |
| `path` | string \| null | Required pattern for local only |
| `url` | HTTP URL \| null | Required for public_git |
| `ref` | string \| null | Required for public_git |
| `display_name` | string | 1–200 chars |

Errors: **400** on source validation failure.

### `GET /api/repositories`

List repositories with lifecycle fields plus optional:

- `last_successful_processing_at`
- `current_error`

### `GET /api/repositories/{repository_id}`

Single repository or **404**.

### `DELETE /api/repositories/{repository_id}`

Idempotent delete lifecycle. May return deletion receipt shaped as a repository response with `lifecycle_status` reflecting deleted completion, or in-progress/`delete_failed` states.

## Ingestion / manifest

### `POST /api/repositories/{repository_id}/sync` → 201

Starts manifest + index for the repository.

Returns `ManifestRunResponse`:

| Field | Notes |
|-------|--------|
| `id` | Run id |
| `repository_id` | Parent |
| `status` | `running` \| `succeeded` \| `failed` |
| `parser_version` | e.g. `text-v1` |
| `file_count`, `total_bytes` | Inventory stats |
| `error` | Truncated failure text |
| `started_at`, `completed_at` | Timestamps |
| `phase` | Durable phase label |
| `current_count`, `total_count`, `percentage` | Numeric progress |

**409** when ingest concurrency/lease is busy (`ManifestBusyError`).

### `GET /api/ingestion-runs/{run_id}`

Single run or **404**.

### `GET /api/repositories/{repository_id}/ingestion-runs`

Newest-oriented history for operator UI.

### `GET /api/ingestion-runs/{run_id}/entries`

Manifest entry rows (path, classification, hashes, etc.).

## Wiki generation and pages

### `POST /api/repositories/{repository_id}/pages` → 201

Body (`WikiGenerationRequest`):

```json
{
  "source_paths": null
}
```

Returns `GenerationRunResponse`:

| Field | Notes |
|-------|--------|
| `id` | Generation run id |
| `page_path` | `wiki` for a repository-wide generation run |
| `status` | `running` \| `succeeded` \| `failed` |
| `source_selection` | Compact chunk selection JSON |
| `wiki_structure` | Five fixed groups with zero or more derived page descriptors |
| `configured_model` / `provider_model` | Requested vs provider-reported |
| `prompt_version` | e.g. `wiki-v2` |
| `error` / `failure_stage` | Present on failure |
| `diagrams` | Mermaid outcomes for the run |
| `started_at` / `completed_at` | Timestamps |

**409** when generation slots are exhausted. **500** if the run could not be persisted after generation attempt (truthful; no silent publish).

### `GET /api/generation-runs/{run_id}`

### `GET /api/repositories/{repository_id}/generation-runs`

### `GET /api/repositories/{repository_id}/pages`

List of `WikiPageSummaryResponse`: `path`, `title`, `lifecycle_status` (`published`), `generation_run_id`. Paths are source-derived and begin with one of the five reader groups.

### `GET /api/repositories/{repository_id}/pages/{page_path}`

Full page:

- `content` (markdown)
- `citations[]` (`path`, `line_start`, `line_end`)
- `diagrams[]` (`ordinal`, `source`, `status`, `svg`, `error`)

**404** if not published.

## Indexed sources

### `GET /api/repositories/{repository_id}/sources/{source_path}`

Returns indexed content only:

```json
{
  "path": "backend/hydrawiki/api.py",
  "content": "...",
  "line_count": 123
}
```

Never reads arbitrary host paths; **404** if not in the index.

## Error conventions

| HTTP | Typical cause |
|------|----------------|
| 400 | Invalid registration / source validation |
| 404 | Unknown repository, run, page, or indexed source |
| 409 | Ingest or generation concurrency limit |
| 500 | Persistence failure after generation attempt |
| 503 | Readiness failure |

Detail bodies commonly use FastAPI `{"detail": "..."}` strings consumed by the frontend error helper.

## OpenAPI

FastAPI serves interactive schema from the running API (default docs routes unless disabled). The models in `api.py` are the code-level contract.

## Next

- [Data model](data-model.md)
- [Configuration](configuration.md)
- [Frontend](frontend.md)
