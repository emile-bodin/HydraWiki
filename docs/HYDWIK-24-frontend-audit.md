# HYDWIK-24 frontend audit

This audit was completed before the HYDWIK-24 implementation.

## Existing data and contracts

The frontend already receives the data needed for the redesign through existing
contracts:

- `GET /api/repositories` returns the display name, source type/value, selected
  ref, lifecycle status, current/last error, and last successful processing
  timestamp.
- `GET /api/repositories/{id}/ingestion-runs` and
  `GET /api/repositories/{id}/generation-runs` return separate process status,
  timestamps, ingestion progress, results, and errors.
- `GET /api/repositories/{id}/pages` and
  `GET /api/repositories/{id}/pages/{path}` provide the published page list,
  page content, citations, and validated Mermaid artifacts.
- `GET /api/repositories/{id}/sources/{path}` provides traceable indexed source
  content. Registration, ingestion, generation, and deletion already have
  matching endpoints.

The existing `wiki-v2` generation prompt is the source of truth for the five
required sections: System context, Architecture overview, Main components, Key
workflows, and Constraints and failure behavior.

## Frontend-only work

Shared navigation, browser-history routes, responsive layouts, repository cards,
the documentation viewer, Markdown presentation, Mermaid failure presentation,
and the operator workflow display are frontend-only. The operator can call the
existing ingestion endpoint and, only after its returned run is successful, the
existing page-generation endpoint sequentially.

## Backend changes

No backend, API, database, deployment, indexing, or generation changes are
required for HYDWIK-24. In particular, the frontend must not manufacture the
five-section structure: it reads published pages and the backend-owned prompt
continues to define that structure.
