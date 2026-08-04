# Overview

[Index](README.md) · [Next: Architecture](architecture.md)

## System context

HydraWiki is an open-source, self-hosted platform that creates **traceable documentation** for **explicitly registered** local and public code repositories.

It is designed to be:

- **Simple and practical** — implement approved scope only
- **Truthful about failure** — visible ingest and generation errors; no fabricated wiki content after a failed generation
- **Lifecycle-aware** — repositories, manifests, chunks, vectors, wiki pages, and workspaces are durable and deletable together
- **Evidence-backed** — published pages carry source paths and line ranges

## Who it is for

| Audience | Need |
|----------|------|
| Operators | Register repos, run ingestion and generation, inspect progress and errors |
| Readers | Browse published pages, open citations, view server-validated diagrams |
| Deployers | Run Compose-owned services against existing LiteLLM and Ollama installs |

## Product boundary

HydraWiki **owns**:

- Docker deployment for its own services (API, worker, frontend, PostgreSQL, Qdrant, workspace volume)
- Repository registration, ingestion, indexing, wiki generation, Mermaid validation, and safe deletion
- Persistent relational data and derived vectors for registered repositories

HydraWiki **does not own** (and must not install/replace/containerize unless an approved issue requires it):

- External **LiteLLM** (or other OpenAI-compatible) generation service
- External **Ollama** embedding service

## MVP capabilities (implemented direction)

From the approved product constraints and current code:

1. Register **local** repositories under an allowlisted read-only mount
2. Register **public Git** repositories by HTTPS URL and ref
3. Persist repository, ingestion, index, wiki, and error lifecycle data
4. Hash-based reuse of unchanged content; delta handling for new, changed, and deleted files
5. Generate wiki pages only after successful generation, citation validation, and Mermaid validation
6. Show source attribution with file paths and line ranges
7. Delete a repository and related metadata, chunks, vectors, wiki data, and workspace data
8. Server-side Mermaid validation and safe rendering

## Explicit non-goals (MVP)

- Private Git credentials
- Multi-user authorization
- Automatic schedules or webhooks
- Cross-repository search
- Multi-agent documentation generation
- Placeholder or fallback wiki content after generation failure

## High-level lifecycle

```text
Register repository
        │
        ▼
   Sync / ingest  ──►  manifest + delta + chunk + embed + vectors
        │
        ▼
 Generate page    ──►  select chunks → prompt → LLM → cite + Mermaid → publish
        │
        ▼
  Read / cite / diagram
        │
        ▼
 Delete repository (relational + vectors + workspace)
```

## Repository layout (top level)

```text
HydraWiki/
├── backend/hydrawiki/   # FastAPI API, worker, domain logic, migrations, prompts
├── backend/tests/       # Unit and integration tests
├── frontend/            # React operator + reader UI
├── docs/                # Architecture, operations, this wiki
├── docker-compose.yml   # HydraWiki-owned services only
└── AGENTS.md            # Agent and product discipline
```

## Version and identity notes

- Application title defaults to `HydraWiki`; API app version is `0.1.0` in `create_app`
- Parser version used by manifests: `text-v1`
- Default chunker version: `line-size-v2`
- Default generation prompt package resource: `wiki-v2.txt` (settings default `generation_prompt_version` is `wiki-v2`; Compose example env may still show `wiki-v1` as a deployment override string)

## Next

- [Architecture](architecture.md) — services and module map
- [Repositories and sources](repositories-and-sources.md) — how sources are accepted
