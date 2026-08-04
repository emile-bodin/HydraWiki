# Architecture

[Index](README.md) · [Previous: Overview](overview.md) · [Next: Repositories and sources](repositories-and-sources.md)

## Service topology

Docker Compose runs only HydraWiki-owned services. Generation and embeddings are external.

```mermaid
flowchart LR
  Browser[Browser] --> FE[frontend :8080]
  FE --> API[api :8000]
  API --> PG[(postgres)]
  API --> QD[(qdrant)]
  Worker[worker] --> PG
  Worker --> QD
  Worker --> Ollama[Ollama embeddings]
  API --> Gen[LiteLLM generation]
  API --> MMDC[mmdc Mermaid CLI]
  HostRepos/repositories ro] --> API
  Host --> Worker
  Git[Public HTTPS Git] --> Worker
```

| Service | Image / build | Role |
|---------|---------------|------|
| `frontend` | `./frontend` | Static React app + nginx reverse proxy to API |
| `api` | `./backend` | FastAPI: register, sync, generate, read, delete, health |
| `worker` | `./backend` | Long-running process; validates config; shared manifest entrypoint |
| `postgres` | `postgres:17-alpine` | Authoritative product database |
| `qdrant` | `qdrant/qdrant:v1.13.6` | Derived vector store |
| `schema` | `./backend` (profile `bootstrap`) | One-shot `hydrawiki.operational bootstrap` |

Volumes:

| Volume | Purpose |
|--------|---------|
| `postgres-data` | PostgreSQL data directory |
| `qdrant-data` | Qdrant storage |
| `workspace-data` | Per-repository workspaces under `/var/lib/hydrawiki/workspaces` |

Local repository host root is bind-mounted **read-only** to `/repositories` (default host path `./repositories` via `LOCAL_REPOSITORIES_ROOT`).

## Control and data flow

### Registration

1. Client posts registration to the API
2. Source adapters validate local path or public Git URL/ref
3. Row is inserted into `repositories` with lifecycle `registered`

### Ingestion (sync)

1. `POST .../sync` starts `run_manifest`
2. Source tree is resolved (local mount or workspace clone for public Git)
3. Eligible files are discovered, hashed, and classified against prior state
4. Delta is applied transactionally; indexing embeds changed content into Qdrant
5. Durable progress fields (`phase`, `current_count`, `total_count`, `percentage`) update on the manifest run

Ingest concurrency is gated with PostgreSQL advisory locks (global slot bound + per-repository lease). A full bound returns HTTP **409** without creating an unbounded queue of work.

### Wiki generation

1. `POST .../pages` acquires a generation advisory-lock slot
2. Indexed chunks are selected (optional path filter, character budget)
3. Prompt is built from `wiki-v2.txt` and stored as a generation artifact
4. OpenAI-compatible adapter calls the configured generation endpoint
5. Response JSON is validated; citations are checked against selected ranges
6. Mermaid fences are rendered and SVG-accepted, or the run fails
7. Only then is a `wiki_pages` row published (`lifecycle_status = published`)

### Deletion

1. Repository is marked `deleting`
2. Qdrant vectors for the repository are removed
3. Workspace directory under `WORKSPACE_ROOT/{id}` is removed (symlink roots rejected)
4. Relational rows cascade or are completed into a deletion receipt (`deleted` / `delete_failed`)

## Backend module map

| Module | Responsibility |
|--------|----------------|
| `api.py` | FastAPI routes and response models |
| `config.py` | Typed `HYDRAWIKI_*` settings |
| `health.py` | Liveness and readiness |
| `sources.py` | Local and public Git adapters |
| `manifest.py` | Scan, hash, classify, apply delta, trigger index |
| `indexing.py` | Chunk, embed, staged vector replacement |
| `chunking.py` | Line-aware size-bounded chunker |
| `embeddings.py` | Ollama `/api/embeddings` adapter |
| `vectors.py` | Qdrant vector store operations |
| `wiki.py` | Generation run lifecycle, citations, Mermaid gate, publish |
| `generation.py` | OpenAI-compatible chat/completions or responses client |
| `mermaid.py` | Extract fences, run `mmdc`, accept inert SVG |
| `persistence.py` | Database, migrations, repository store |
| `operational.py` | Bootstrap and schema verify CLI |
| `worker.py` | Worker process loop; shared `execute_manifest` boundary |
| `prompts/wiki-v2.txt` | Citation-gated architecture overview prompt |

## Frontend architecture

Single React entry (`frontend/src/main.tsx`) with two views:

- **Reader** — repository select, published page nav, markdown render, outline, citations, source drawer, safe diagrams
- **Operator** — register, delete, start ingestion, generate page, run history and errors

API base path is same-origin (`const API = ""`); nginx proxies `/api` and health to the backend.

## Persistence authority

| Store | Authority |
|-------|-----------|
| PostgreSQL | Repositories, manifests, content cache, chunks, generation, wiki pages, diagrams, deletion receipts, durable errors |
| Qdrant | Derived embeddings only; rebuildable from PG + sources in principle, but backup runbook snapshots both |
| Workspace volume | Managed clones/workspaces for public Git and processing |
| Host local repos | Operator-owned inputs; **not** HydraWiki backup data |

## Concurrency model

| Work | Default bound | Mechanism |
|------|---------------|-----------|
| Manifest / ingest runs | 1 (max 2) | Advisory locks; 409 when full |
| Embedding requests within ingest | 2 | Advisory lock slots with short wait |
| Wiki generation runs | 1 (max 2) | Advisory locks; 409 when full |
| Index replacement recovery | Per-run lease | Advisory lock on replacement run id |

These are application workload limits, not Docker CPU/memory caps.

## Design references (learning only)

RepoWiki and deepwiki-open are reference projects for ideas (filtering, line-aware splitting, LiteLLM patterns). Their lifecycle/cache semantics are **not** product requirements unless explicitly approved. HydraWiki prefers durable progress and fail-closed publication.

## Next

- [Repositories and sources](repositories-and-sources.md)
- [Ingestion](ingestion.md)
- [Data model](data-model.md)
