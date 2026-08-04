# Repositories and sources

[Index](README.md) · [Previous: Architecture](architecture.md) · [Next: Ingestion](ingestion.md)

## Source types

HydraWiki accepts exactly two registration kinds:

| `source_type` | Required fields | Stored as |
|---------------|-----------------|-----------|
| `local` | `path`, `display_name` | `source_value` = relative path under local root; `selected_ref` = null |
| `public_git` | `url`, `ref`, `display_name` | `source_value` = URL; `selected_ref` = validated ref |

Registration endpoint: `POST /api/repositories` (`RepositoryRegistration` in `api.py`).

## Local repositories

Adapter: `LocalRepositoryAdapter` in `sources.py`.

Rules:

1. `path` must be a **non-empty relative** path (no absolute paths)
2. Path segments must not include `""`, `"."`, or `".."` (no traversal)
3. Resolved path must stay under `LOCAL_REPOSITORIES_ROOT` (default `/repositories` in containers)
4. Target must be an existing **directory** on the mounted tree
5. Registration does **not** copy or modify the host tree; adapters are read-only toward local mounts

Compose mounts:

```text
${LOCAL_REPOSITORIES_ROOT:-./repositories}:/repositories:ro
```

Operator UI label: “Path below LOCAL_REPOSITORIES_ROOT”.

## Public Git repositories

Adapter: `PublicGitRepositoryAdapter` in `sources.py`.

Rules:

1. URL scheme must be **https**
2. Hostname required; **no** username/password in the URL
3. Hostname must not resolve as a private, loopback, link-local, or reserved IP address when the host is an IP literal
4. Path must identify a repository (not empty `/`)
5. Ref must be non-empty, must not start with `-`, must not contain `..`, and must not match forbidden ref characters (whitespace and Git ref specials)

MVP **excludes** private Git credentials. Only public HTTPS sources are accepted by this adapter.

During sync, public sources are materialized into the managed workspace under `WORKSPACE_ROOT` (Compose default `/var/lib/hydrawiki/workspaces`). Workspace roots that are symlinks are rejected during deletion safety checks.

## Repository lifecycle status

From migrations and API models:

| Status | Meaning |
|--------|---------|
| `registered` | Active repository record |
| `deleting` | Delete job in progress |
| `deleted` | Represented via deletion receipt responses after completion |
| `delete_failed` | Delete attempted and failed; error retained |

API list/detail also expose operator fields when present:

- `last_successful_processing_at` — latest successful manifest completion
- `current_error` — deletion error or latest failed manifest error (null when absent)

## Registration request examples

### Local

```json
{
  "source_type": "local",
  "path": "my-project",
  "display_name": "My Project"
}
```

Invalid if `url` or `ref` is also supplied.

### Public Git

```json
{
  "source_type": "public_git",
  "url": "https://github.com/org/repo.git",
  "ref": "main",
  "display_name": "Org Repo"
}
```

Invalid if `path` is also supplied, or if URL/ref rules fail.

## What registration does *not* do

- It does not scan or index files
- It does not call LiteLLM or Ollama
- It does not create wiki pages
- It does not clone until a later sync path needs a workspace materialization

Next step after registration is always **ingestion** (`POST /api/repositories/{id}/sync`). See [Ingestion](ingestion.md).

## Delete semantics (source side)

`DELETE /api/repositories/{id}`:

1. Returns existing deletion receipt if already deleted (idempotent read of completed delete)
2. Otherwise marks `deleting` and removes vectors, workspace, and relational data
3. Local host repositories under the bind mount are **not** deleted as operator source trees; only HydraWiki-managed workspace data for that id is removed

See [Operations](operations.md) for the full delete and backup picture.

## Next

- [Ingestion](ingestion.md)
- [API reference](api.md)
