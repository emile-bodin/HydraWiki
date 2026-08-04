# HydraWiki manual wiki

This directory is a **multi-page markdown wiki** of the HydraWiki codebase itself.

It is hand-written from the repository tree and durable docs. It is **not** output from the product generation pipeline (`POST /api/repositories/{id}/pages`): there are no persisted generation runs, validated line-range citations, or server-approved Mermaid SVGs attached to these pages.

## Pages

| Page | Topic |
|------|--------|
| [Overview](overview.md) | Product purpose, boundaries, and what this wiki covers |
| [Architecture](architecture.md) | Services, data flow, and module map |
| [Repositories and sources](repositories-and-sources.md) | Local and public Git registration, path safety |
| [Ingestion](ingestion.md) | Manifest, delta classification, chunking, embeddings, vectors |
| [Wiki generation](generation.md) | Prompt, LiteLLM adapter, citations, publish rules |
| [Mermaid](mermaid.md) | Server-side render and inert SVG trust boundary |
| [API reference](api.md) | HTTP endpoints and request/response shapes |
| [Data model](data-model.md) | PostgreSQL entities and migrations |
| [Frontend](frontend.md) | Reader and operator UI behavior |
| [Configuration](configuration.md) | Environment variables and workload limits |
| [Operations](operations.md) | Compose, backup/restore, health, deletion |

## Suggested reading order

1. [Overview](overview.md)
2. [Architecture](architecture.md)
3. [Repositories and sources](repositories-and-sources.md)
4. [Ingestion](ingestion.md)
5. [Wiki generation](generation.md)
6. [Mermaid](mermaid.md)
7. [API reference](api.md) and [Data model](data-model.md)
8. [Frontend](frontend.md), [Configuration](configuration.md), [Operations](operations.md)

## Related durable docs

- [`docs/PROJECT_OUTLINE.md`](../PROJECT_OUTLINE.md) — vision and phase roadmap
- [`docs/architecture/implementation-plan.md`](../architecture/implementation-plan.md) — MVP scope and design decisions
- [`docs/architecture/api-contract.md`](../architecture/api-contract.md) — health, config, operator, Mermaid contract notes
- [`docs/operations/backup-restore.md`](../operations/backup-restore.md) — backup and restore runbook
- [`AGENTS.md`](../../AGENTS.md) — product boundary and change discipline

## How this differs from product wiki pages

| | Manual wiki (`docs/wiki/`) | Product generation |
|--|---------------------------|--------------------|
| Author | Human / coding agent from source | LiteLLM via `wiki-v2` prompt |
| Storage | Git markdown | `wiki_pages` + `generation_runs` |
| Citations | Informal file references | Validated path + line ranges |
| Mermaid | Illustrative in markdown | `mmdc` + inert SVG gate |
| Failure policy | N/A | Fail closed; no placeholder publish |
