# Configuration

[Index](README.md) · [Previous: Frontend](frontend.md) · [Next: Operations](operations.md)

## Loading rules

Backend settings use Pydantic Settings (`config.py`):

- Environment prefix: `HYDRAWIKI_`
- Optional `.env` file (not committed with secrets)
- `extra = "ignore"` for unknown keys
- Empty strings for generation URL/model/API key are treated as **unset** (`None`)

`validate_settings()` / `get_settings()` fail fast on invalid configuration so API and worker do not run half-configured.

Compose requires externally:

- `HYDRAWIKI_DATABASE_URL`
- `HYDRAWIKI_POSTGRES_PASSWORD`

Copy from `.env.example` patterns when present; never commit real credentials or private host addresses.

## Core service settings

| Variable | Default / notes |
|----------|-----------------|
| `HYDRAWIKI_DATABASE_URL` | **Required** Postgres URL |
| `HYDRAWIKI_QDRANT_URL` | Compose default `http://qdrant:6333` |
| `HYDRAWIKI_OLLAMA_URL` | Default `http://ollama:11434` |
| `HYDRAWIKI_EMBEDDING_MODEL` | `nomic-embed-text:latest` |
| `HYDRAWIKI_EMBEDDING_INDEX_VERSION` | `embedding-v1` |
| `HYDRAWIKI_EMBEDDING_MAX_INPUT_CHARACTERS` | `4000` |
| `HYDRAWIKI_LOCAL_REPOSITORIES_ROOT` | `/repositories` in containers |
| `HYDRAWIKI_WORKSPACE_ROOT` | `/var/lib/hydrawiki/workspaces` |
| `HYDRAWIKI_API_PORT` | Host publish port for API (default `8191`) |
| `LOCAL_REPOSITORIES_ROOT` | **Host** path mounted read-only (Compose, default `./repositories`) |

Application process bind defaults inside the container: `api_host=0.0.0.0`, `api_port=8000`.

## Workload limits

| Variable | Default | Valid range / notes |
|----------|--------:|---------------------|
| `HYDRAWIKI_MAX_REPOSITORY_SIZE_BYTES` | 1073741824 (1 GiB) | Positive |
| `HYDRAWIKI_MAX_SOURCE_FILES` | 25000 | Positive |
| max indexable text bytes | 100 MiB | Settings field `max_total_indexable_text_bytes` |
| max source file size | 2 MiB | Settings field `max_source_file_size_bytes` |
| `HYDRAWIKI_EMBEDDING_MAX_CONCURRENCY` | 2 | 1–2 |
| `HYDRAWIKI_INGEST_MAX_CONCURRENCY` | 1 | 1–2 |
| `HYDRAWIKI_GENERATION_MAX_CONCURRENCY` | 1 | 1–2 |

Readiness responses expose the effective concurrency values.

These are **application** limits, not Docker CPU/memory limits.

## Chunking and embeddings

| Setting | Default |
|---------|---------|
| `chunker_version` | `line-size-v2` |
| `chunk_max_lines` | 80 |
| `embedding_timeout_seconds` | 30 (max 300) |

## Generation (LiteLLM / OpenAI-compatible)

| Variable | Default | Notes |
|----------|---------|-------|
| `HYDRAWIKI_GENERATION_URL` | unset | Must end with `/chat/completions` or `/responses` when used |
| `HYDRAWIKI_GENERATION_MODEL` | unset | Required together with URL to generate |
| `HYDRAWIKI_GENERATION_API_KEY` | unset | SecretStr; redacted in provider error sanitization |
| `HYDRAWIKI_GENERATION_TIMEOUT_SECONDS` | 60 | Max 300 |
| `HYDRAWIKI_GENERATION_PROMPT_VERSION` | settings default `wiki-v2` | Compose file may still pass `wiki-v1` as an override string—align deploy env with the packaged prompt you intend |
| `HYDRAWIKI_GENERATION_MAX_OUTPUT_TOKENS` | 8000 | Settings cap at 8000 |
| `HYDRAWIKI_GENERATION_MAX_SOURCE_CHARACTERS` | 100000 | Max 2_000_000 |

If URL or model is missing, generation fails at the generation stage with a clear configuration error.

## Mermaid

| Variable | Default |
|----------|---------|
| `HYDRAWIKI_MERMAID_RENDERER_COMMAND` | `mmdc` |
| `HYDRAWIKI_MERMAID_TIMEOUT_SECONDS` | 15 |
| `HYDRAWIKI_MERMAID_RENDERER_USER` | `hydrawiki-renderer` |
| max source characters / max SVG bytes | 50_000 / 2_000_000 in settings |

## Security configuration practices

- Keep secrets in deployment environment or ignored `.env`, never in git
- Do not put private LiteLLM/Ollama addresses into committed docs as requirements
- Local root must be an explicit allowlisted mount; path traversal is rejected in adapters
- Generation API keys are optional depending on the external gateway; when present they stay server-side only

## Frontend configuration

The SPA does not load a separate public config file for model endpoints. It talks only to HydraWiki’s API. nginx config selects upstream API routing inside the frontend container network.

## Next

- [Operations](operations.md)
- [Architecture](architecture.md)
