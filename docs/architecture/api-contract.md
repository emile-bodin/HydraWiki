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

No Phase-1 endpoint registers repositories, starts ingestion, indexes content,
calls an AI service, generates wiki content, processes Mermaid, or deletes data.
