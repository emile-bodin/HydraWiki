# Operations

[Index](README.md) · [Previous: Configuration](configuration.md)

## Compose deployment

Primary file: `docker-compose.yml`.

### Services checklist

| Service | Depends on | Notes |
|---------|------------|-------|
| `postgres` | — | Health: `pg_isready` |
| `qdrant` | — | Health: TCP 6333 |
| `api` | postgres, qdrant healthy | Health: `GET /health/ready` |
| `worker` | postgres, qdrant healthy | Same image; `python -m hydrawiki.worker` |
| `frontend` | api healthy | Port 8080→80 |
| `schema` | postgres | Profile `bootstrap` only |

### Required external env

```bash
HYDRAWIKI_DATABASE_URL=...
HYDRAWIKI_POSTGRES_PASSWORD=...
```

Optional but required for real wiki generation: generation URL/model (and API key if the gateway needs it), plus reachable Ollama for embeddings during sync.

### Typical ports

| Port | Service |
|------|---------|
| 8080 | Frontend |
| 8191 | API (configurable via `HYDRAWIKI_API_PORT`) |

### Security options

API and worker set `security_opt: [seccomp=unconfined]` in Compose for the current Mermaid/Chromium rendering needs in this deployment shape. Treat that as an operational tradeoff to review for hardened installs.

## Schema bootstrap and verify

- Bootstrap profile: `python -m hydrawiki.operational bootstrap`
- Verify: `python -m hydrawiki.operational verify` (used in restore gates)

API lifespan also runs `migrate()` and `verify_schema_compatible()` on startup.

## Health checks

| Check | Meaning |
|-------|---------|
| `GET /health/live` | Process is up |
| `GET /health/ready` | Typed configuration valid; exposes concurrency snapshot |

Use ready for Compose health on the API container.

## Repository deletion

Operational expectations:

1. Call `DELETE /api/repositories/{id}`
2. Observe lifecycle `deleting` → deleted receipt or `delete_failed`
3. Confirm related PG rows, Qdrant vectors, and workspace directory are gone on success
4. Do **not** claim success early in automation if status is still `deleting` or `delete_failed`

Local bind-mounted source trees remain host-owned; only managed workspace data is removed.

## Backup and restore

Authoritative runbook: [`docs/operations/backup-restore.md`](../operations/backup-restore.md).

Summary:

**Persistent sets**

| Data | Store |
|------|--------|
| Lifecycle, wiki, chunks, errors | PostgreSQL dump |
| Vectors | Qdrant snapshot |
| Managed workspaces | `workspace-data` tarball |
| Provenance | Compose digest, images list, migration versions, UTC timestamp |

**Not backup targets**

- Host local repositories under `LOCAL_REPOSITORIES_ROOT`
- LiteLLM / Ollama service state
- Secrets in environment files

**Consistent backup pattern**

1. Select an explicit Compose **project** name
2. Stop writers (`api`, `worker`)
3. `pg_dump` custom format
4. Qdrant snapshot download
5. Tar workspace volume
6. Write provenance files **without** credentials
7. Start writers again

**Restore pattern**

1. Only into a new disposable project named `hydrawiki-restore-*`
2. Restore PG, upload Qdrant snapshot, unpack workspace into empty volume
3. Diff migration list; run `hydrawiki.operational verify`
4. Tear down disposable project when done

## Capacity and concurrency

Defaults favor safety on shared hosts:

- One ingest run globally (configurable to 2)
- Two embedding requests
- One generation run

Raising bounds still cannot overlap two ingests on the **same** repository (per-repo lease). See [Configuration](configuration.md).

## Failure handling expectations

| Area | Operator should see |
|------|---------------------|
| Ingest | Run `failed` + `error`; prior good inventory retained on failed scans |
| Generation | Run `failed` + `failure_stage` + `error`; no fake page |
| Mermaid | Diagram `failed` + source; page not replaced |
| Delete | `delete_failed` + error if incomplete |
| Busy system | HTTP 409 on sync or generate |

## Logs and debugging entry points

| Symptom | Start here |
|---------|------------|
| Cannot register local path | Mount + relative path rules ([Repositories](repositories-and-sources.md)) |
| Sync 409 | Ingest concurrency / existing run |
| Sync failed mid-index | Manifest run error; Ollama reachability; size gates |
| Generate failed | Generation run `failure_stage`; LiteLLM URL/model; citations; Mermaid |
| Page missing after “success” | Confirm run `succeeded` and `GET .../pages/{path}` |
| Diagram blank/error in UI | `generation_diagrams` status; renderer user/CLI in API container |

## Related docs

- [Architecture](architecture.md)
- [Configuration](configuration.md)
- [API reference](api.md)
- [Backup runbook](../operations/backup-restore.md)

## Manual wiki note

These operations pages document **implemented and runbooked** behavior. They do not replace product-generated wiki pages with line-level citations. For generation of those, run a registered repository through ingest + `POST .../pages` against a live stack.
