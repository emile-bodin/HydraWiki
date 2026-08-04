# Wiki generation

[Index](README.md) · [Previous: Ingestion](ingestion.md) · [Next: Mermaid](mermaid.md)

## Purpose

Generate a **published** repository-specific wiki from **indexed source chunks**, with:

- A derived structure containing the fixed reader groups and a variable number of source-supported pages
- Structured page output (`group` + `path` + `title` + `content` + `citations`)
- Citation validation against selected chunk line ranges
- Mermaid validation before publication
- Durable run records and failure stages
- **No** placeholder page if any stage fails

Implementation: `wiki.py` (`generate_wiki_page`), prompt `prompts/wiki-v2.txt`, adapter `generation.py`.

## API

```http
POST /api/repositories/{repository_id}/pages
Content-Type: application/json

{"source_paths": null}
```

| Field | Rules |
|-------|--------|
| `path` / `title` | Optional legacy fields; the operator does not send them |
| `source_paths` | Optional list of source paths; `null`/omitted uses general selection order |

Response: `GenerationRunResponse` (201 on accepted/completed run persistence). Busy generation returns **409**.

Read paths:

- `GET /api/repositories/{id}/pages`
- `GET /api/repositories/{id}/pages/{path}`
- `GET /api/generation-runs/{id}`
- `GET /api/repositories/{id}/generation-runs`

## Pipeline and failure stages

`failure_stage` is recorded on failed runs (migration `007_generation_failure_stage.sql`). Stages advance roughly as:

| Stage | Work |
|-------|------|
| `start` | Insert `generation_runs` row (`status=running`) |
| `source_selection` | Load chunks; enforce character budget |
| `prompt` | Render `wiki-v2` template; store prompt artifact |
| `generation` | Call OpenAI-compatible endpoint |
| `response_validation` | Parse and validate the complete derived structure and page documents |
| `citation_validation` | Ensure citations map to indexed, selected ranges |
| `mermaid_validation` | Render and accept every Mermaid fence |
| `publication` | Atomically replace the repository's published page set and mark run succeeded |

On failure: run becomes `failed` with truncated error text; **existing published pages are not replaced** by failed content. Mermaid failure stores diagram rows with `status=failed` and blocks publication.

## Source selection

`WikiStore.select_sources`:

1. Query `chunks` for the repository (optional `path = ANY(source_paths)`)
2. Order by `path`, `ordinal`
3. Accumulate chunk text until `generation_max_source_characters` (default 100,000)
4. Error if no chunks, or if a single chunk exceeds the budget

Compact selection stored on the run:

```json
[
  {
    "chunk_id": "...",
    "path": "backend/hydrawiki/api.py",
    "line_start": 1,
    "line_end": 40
  }
]
```

## Prompt contract (`wiki-v2`)

Template resource: `hydrawiki/prompts/wiki-v2.txt`.

Placeholders:

- `__TITLE__`
- `__SOURCE_EXCERPTS__` — blocks like `--- path:start-end ---` plus chunk text

Model must return **JSON only** with exactly `structure` and `pages`. `structure` always contains the five fixed groups (`get-started`, `concepts`, `guides`, `reference`, `workflows`) and may contain zero or more source-derived pages per group. `pages` contains only the planned pages; unsupported standard pages are omitted.

Each page has this shape:

```json
{"group":"concepts","path":"concepts/example","title":"Example","content":"markdown...","citations":[{"path":"...","line_start":1,"line_end":2}]}
```

Prompt rules (product intent encoded in the template):

- Use only provided excerpts; no general knowledge
- Source-derived pages only; do not fill empty groups with generic API, configuration, or operations pages
- Mermaid node IDs are stable simple identifiers; labels and paths are quoted separately
- At most two Mermaid diagrams; standard diagram structure only (no `config` frontmatter, `%%{...}%%`, `classDef`, presentation styling, or `click`)
- Citations only in the JSON array, not inside markdown content

Default settings prompt version: `wiki-v2`. Artifacts table stores full prompt and raw response for the run.

## Generation adapter

`OpenAICompatibleGenerationAdapter`:

- Endpoint URL must end with `/chat/completions` or `/responses`
- Supports both styles; normalizes returned text
- Timeout and max output tokens from settings
- Provider error messages sanitized (API keys / bearer tokens redacted)
- Requires `generation_url` and `generation_model`; missing config fails the run visibly

Compose wires:

- `HYDRAWIKI_GENERATION_URL`
- `HYDRAWIKI_GENERATION_MODEL`
- `HYDRAWIKI_GENERATION_API_KEY` (secret; optional empty → unset)
- `HYDRAWIKI_GENERATION_TIMEOUT_SECONDS`
- `HYDRAWIKI_GENERATION_MAX_OUTPUT_TOKENS` (capped at 8000 in settings)

## Citation validation

For each citation:

1. `line_end >= line_start` and both positive
2. Path must exist as an indexed `source_files` row with `content_cache.line_count`
3. `line_end` must not exceed that line count
4. The full citation range must be covered by the **selected** chunk intervals for that path

Duplicates are deduplicated before publish. At least one citation is required by the schema (`GeneratedDocument`).

## Publication

On success, within one transaction:

1. Insert or update the variable set of `wiki_pages` for `(repository_id, path)` with `lifecycle_status = 'published'`
2. Replace `wiki_page_sources` rows for that page
3. Remove pages no longer in the derived structure
4. Mark generation run `succeeded` with `provider_model`

Only `published` pages are listed/read through the page APIs. There is no “draft” or “partial page” publish path in the MVP schema.

## Concurrency

`generation_slot` uses PostgreSQL advisory locks:

- Slots: `generation_max_concurrency` (default 1, max 2)
- Exhaustion → `GenerationBusyError` → HTTP **409**
- No unbounded queue in the API path

## Operator UI behavior

- One `Generate wiki` action derives the structure and page titles; no manual path, title, group, or section selection
- Disabled until successful ingestion evidence exists
- Polls generation runs ~1.5s while running
- Shows configured model, provider model, prompt version, failure stage, errors, and diagrams
- On success, refreshes published page list

## Truthfulness rules

| Event | Product behavior |
|-------|------------------|
| LLM down / misconfigured | Failed run; no new page content |
| Invalid JSON / missing citations | Failed at `response_validation` |
| Citation outside selection | Failed at `citation_validation` |
| Mermaid reject | Diagram `failed`; run failed; no replace of good page |
| Storage issue after generate | Error remains visible; no silent success |

## Next

- [Mermaid](mermaid.md) — diagram trust boundary detail
- [Frontend](frontend.md) — how pages are rendered
- [API reference](api.md)
