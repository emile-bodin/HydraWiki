# Phase 1 API contract

Phase 1 publishes the service health contract and reserves the application API
paths for later lifecycle phases. Repository and ingestion endpoints are documented
here as shapes only; they are not implemented until their approved phase.

## Health

`GET /health/live` confirms that the API process is running:

```json
{"status":"ok","service":"HydraWiki","checks":{"process":"ok"}}
```

`GET /health/ready` confirms that typed application configuration loaded:

```json
{"status":"ok","service":"HydraWiki","checks":{"configuration":"ok"}}
```

Phase 1 does not contact PostgreSQL, Qdrant, LiteLLM, or Ollama from these
checks. Persistence and provider connectivity checks are introduced with their
respective approved phases.

## Required deployment configuration

The API and worker require `HYDRAWIKI_DATABASE_URL` at startup. The Compose
PostgreSQL service separately requires `HYDRAWIKI_POSTGRES_PASSWORD`; it is not
stored in the repository. Compose fails before creating normal application
containers when either value is missing. Set both externally, for example by
copying `.env.example` to an ignored `.env` and replacing its placeholders.

`HYDRAWIKI_QDRANT_URL` defaults to the Compose service URL and may be overridden
for deployment. The example file contains placeholders only; never commit real
credentials or private deployment addresses.

## Reserved application endpoints

The following endpoint shapes are approved by the implementation plan. They are
intentionally not implemented in Phase 1:

| Method | Path | Later contract purpose |
|---|---|---|
| POST | `/api/repositories` | Register a repository |
| GET | `/api/repositories` | List repositories |
| GET | `/api/repositories/{id}` | Get repository details |
| POST | `/api/repositories/{id}/sync` | Start a sync |
| GET | `/api/ingestion-runs/{id}` | Read run status |
| GET | `/api/ingestion-runs/{id}/events` | Poll or stream run events |
| GET | `/api/repositories/{id}/pages` | List wiki pages |
| GET | `/api/repositories/{id}/pages/{path}` | Read a wiki page |
| DELETE | `/api/repositories/{id}` | Start repository deletion |

## Phase 6 read-only operator views

`GET /api/repositories` additionally returns `last_successful_processing_at`
and `current_error`, when those durable values exist. The former is the latest
successful manifest completion; the latter is the repository deletion error or
the latest failed manifest error. Missing values are `null`.

The following read-only endpoints expose already-persisted lifecycle and source
data for the operator UI:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/repositories/{id}/ingestion-runs` | Durable manifest runs, including phase and numeric progress |
| GET | `/api/repositories/{id}/generation-runs` | Durable generation-run status and error data |
| GET | `/api/repositories/{id}/sources/{path}` | An existing indexed source file only; it never reads a host path |

No Phase-1 endpoint registers repositories, starts ingestion, indexes content,
calls an AI service, generates wiki content, processes Mermaid, or deletes data.

## Phase 7 Mermaid trust boundary

Mermaid fences are rendered by the local pinned Mermaid CLI before publication, with bounded input and a timeout; this uses no model or network service. The renderer process drops to the dedicated `hydrawiki-renderer` account and retains Chromium's sandbox; a missing account fails rendering closed. The renderer SVG is untrusted until the backend accepts it against HydraWiki's minimal inert SVG vocabulary, which excludes CSS and `<style>`. Only a `safe` diagram with server-provided SVG is returned for display. A failed diagram stores its source and durable error on the generation run, and cannot replace an existing published page.

The only CSS exception is the pinned CLI's root `svg` `style` attribute. It is parsed as declarations, not treated as a CSS string: at most one `max-width` decimal pixel value (up to `10000px`) and one `background-color: white` declaration are accepted. Every other property, value, function, URL, escape, variable, import, or duplicate fails closed. Paint is restricted to named inert values and hex colours; presentation values have individual numeric/transform grammars. External `url(...)` references are rejected in every SVG attribute, with only local `url(#id)` markers permitted. The reproducible pinned-CLI check runs inside the backend image: `docker build -t hydrawiki-mermaid-validation:local backend && docker run --rm --entrypoint sh hydrawiki-mermaid-validation:local -lc 'python -c "from hydrawiki.mermaid import MermaidRenderer; print(MermaidRenderer(\"mmdc\", 15, 1000, 2000000).render(\"flowchart TD\\nA-->B\").svg)"'`.
