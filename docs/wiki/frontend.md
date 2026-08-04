# Frontend

[Index](README.md) · [Previous: Data model](data-model.md) · [Next: Configuration](configuration.md)

## Stack

| Piece | Location / note |
|-------|-----------------|
| React + TypeScript | `frontend/src/main.tsx` |
| Styles | `frontend/src/styles.css` |
| Build | Vite (`package.json`) |
| Serve | nginx in `frontend/Dockerfile` + `nginx.conf` |
| Tests | `frontend/src/main.test.tsx` (Vitest) |

Compose publishes the UI on host port **8080**. The browser calls same-origin paths (`const API = ""`); nginx proxies API and health to the backend.

## Views

The app toggles a single `View`: `"reader"` | `"operator"`.

### Reader

Purpose: read published documentation.

Features:

- Repository selector
- Status line (lifecycle, last successful processing time)
- Empty states for no repo / no published pages, with links to the operator dashboard
- Responsive, collapsible left nav with fixed groups: Get started, Concepts, Guides, Reference, and Workflows
- Variable source-derived pages inside each group; empty groups remain visible as “No published pages”
- Article body via `renderDocument`
- Optional “On this page” outline from `##` / `###` headings
- Citations footer: buttons labeled with path and line range
- Source drawer loads `GET .../sources/{path}` for the indexed file

### Operator dashboard

Purpose: manage lifecycle and inspect runs.

Features:

- Register local or public Git repositories
- List cards with source, status, last success, current error
- Delete repository
- Start ingestion (disabled while a run is already running / starting)
- One `Generate wiki` action once ingestion success is evident; page path, title, group, and section are derived by the backend
- Ingestion run cards: phase, counts, percentage `<progress>`, errors, link to manifest entries
- Generation run cards: models, prompt version, failure stage, errors, diagrams
- Optional raw page preview and source panel

## Client API helpers

| Helper | Call |
|--------|------|
| `startIngestion(id)` | `POST /api/repositories/{id}/sync` |
| `startGeneration(id, payload)` | `POST /api/repositories/{id}/pages` |
| `request<T>(path)` | `fetch` + JSON; throws `Error` from `detail` or status |

Polling: while ingestion or generation is active for the selection, the UI refreshes runs every **1500 ms**. After a succeeded generation, published pages are reloaded.

## Markdown rendering

`renderDocument(content, diagrams)` is a small custom renderer (not a full CommonMark engine). It supports:

- Headings h1–h6 (h2/h3 get section ids for the outline)
- Fenced code blocks (``` or ~~~)
- **Mermaid fences** replaced by `SafeDiagram` using server diagram ordinals
- Blockquotes, ordered/unordered lists, task-list checkboxes (read-only)
- Simple pipe tables
- Horizontal rules
- Paragraphs with inline tokens: links, images, code, bold, italic, strikethrough

URL safety for links/images: only `http:`, `https:`, `mailto:`, `/`, or `#` schemes/paths via `safeMarkdownUrl`.

External `http(s)` links open in a new tab with `rel="noreferrer"`.

## Diagrams

`SafeDiagram`:

- Safe server SVG → image data URL
- Otherwise → visible validation error + source `<pre>`

This matches the product rule that browsers must not be the only Mermaid validation layer.

## Citations UX

`citationLabel` formats `path:start–end` (en dash). Clicking a citation opens the indexed source drawer; it does not jump into a live workspace file on disk.

## Generate gating

Operator enablement for generation:

```text
last_successful_processing_at is set
  OR any ingestion run status === "succeeded"
```

Default form values: path `overview`, title `HydraWiki Overview`, `source_paths: null`.

## Error display

Operator view surfaces a top-of-page `role="alert"` error string from failed fetches or actions. Reader operations also set the shared error state when loads fail.

## What the frontend does not do

- Does not embed LiteLLM or Ollama credentials
- Does not render unvalidated Mermaid via a client library as the trust path
- Does not invent placeholder wiki pages when generation fails
- Does not implement multi-user auth (MVP non-goal)

## Next

- [API reference](api.md)
- [Wiki generation](generation.md)
- [Configuration](configuration.md)
