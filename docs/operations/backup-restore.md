# Backup, restore, restart, and MVP evidence

## Scope and persistent data

PostgreSQL is authoritative for repositories, lifecycle/deletion receipts, manifests, chunks, index metadata, generation artifacts, wiki pages, citations, and durable errors. Qdrant stores derived vectors. The Compose `workspace-data` volume holds managed workspaces. Local repositories are host-owned inputs and are not HydraWiki backup data. LiteLLM and Ollama are external services and are not called by these checks.

## Consistent backup

Run this only for the explicitly selected Compose project. It stops the only writers (`api` and `worker`) before taking the PostgreSQL dump and Qdrant snapshot, and starts them again only after all artifacts and provenance files have been written. The project name is required rather than inferred.

```bash
set -euo pipefail
project="${HYDRAWIKI_COMPOSE_PROJECT:?set the selected Compose project}"
backup_dir="backups/$(date -u +%Y%m%dT%H%M%SZ)"
compose=(docker compose -p "$project")
mkdir -p "$backup_dir"
"${compose[@]}" stop api worker
trap '"${compose[@]}" up -d api worker' EXIT
date -u +%FT%TZ > "$backup_dir/backup-timestamp.txt"
sha256sum docker-compose.yml > "$backup_dir/compose.sha256"
"${compose[@]}" config --images | sort > "$backup_dir/images.txt"
"${compose[@]}" exec -T postgres psql -U hydrawiki -d hydrawiki -At -c 'SELECT version FROM schema_migrations ORDER BY version' > "$backup_dir/schema-migrations.txt"
"${compose[@]}" exec -T postgres pg_dump -U hydrawiki -d hydrawiki --format=custom > "$backup_dir/hydrawiki.pg.dump"
"${compose[@]}" run --rm --no-deps api python -c 'import httpx; r=httpx.post("http://qdrant:6333/collections/hydrawiki/snapshots"); r.raise_for_status(); print(r.json()["result"]["name"])' > "$backup_dir/qdrant-snapshot-name.txt"
snapshot_name="$(cat "$backup_dir/qdrant-snapshot-name.txt")"
"${compose[@]}" run --rm --no-deps api python -c 'import httpx,sys; r=httpx.get(f"http://qdrant:6333/collections/hydrawiki/snapshots/{sys.argv[1]}"); r.raise_for_status(); sys.stdout.buffer.write(r.content)' "$snapshot_name" > "$backup_dir/qdrant.snapshot"
test -s "$backup_dir/qdrant.snapshot"
"${compose[@]}" run --rm --no-deps -T api sh -ec 'tar -C /var/lib/hydrawiki/workspaces -czf /tmp/workspace-data.tar.gz . && cat /tmp/workspace-data.tar.gz' > "$backup_dir/workspace-data.tar.gz"
test -s "$backup_dir/workspace-data.tar.gz"
```

The provenance files contain no environment values or credentials: the Compose-file digest, resolved image identities, migration list, and UTC backup timestamp identify the input without copying secrets.

## Isolated restore and compatibility gate

Restore only into a newly created disposable project. This command refuses any project name not beginning with `hydrawiki-restore-`, derives the volume names from that project, and refuses to unpack into a non-empty workspace volume. It never references a production or unqualified Docker volume.

```bash
set -euo pipefail
project="hydrawiki-restore-$(date -u +%Y%m%d%H%M%S)"
case "$project" in hydrawiki-restore-*) ;; *) exit 64 ;; esac
export HYDRAWIKI_API_PORT=0
backup_dir="${1:?pass the backup directory}"
compose=(docker compose -p "$project")
workspace_volume="${project}_workspace-data"
cleanup() { "${compose[@]}" down --volumes --remove-orphans; }
trap cleanup EXIT
test -s "$backup_dir/hydrawiki.pg.dump"
test -s "$backup_dir/qdrant.snapshot"
test -s "$backup_dir/workspace-data.tar.gz"
test -s "$backup_dir/schema-migrations.txt"
test -s "$backup_dir/compose.sha256"
sha256sum -c "$backup_dir/compose.sha256"
"${compose[@]}" up -d --wait postgres qdrant
cat "$backup_dir/hydrawiki.pg.dump" | "${compose[@]}" exec -T postgres pg_restore -U hydrawiki -d hydrawiki --clean --if-exists
"${compose[@]}" run --rm --no-deps -T api sh -ec 'cat >/tmp/hydrawiki.snapshot && python -c "import httpx,sys; r=httpx.post(\"http://qdrant:6333/collections/hydrawiki/snapshots/upload\", files={\"snapshot\": open(\"/tmp/hydrawiki.snapshot\", \"rb\")}); r.raise_for_status(); body=r.json(); sys.exit(0 if body.get(\"status\") == \"ok\" and body.get(\"result\") else 1)"' < "$backup_dir/qdrant.snapshot"
"${compose[@]}" exec -T postgres psql -U hydrawiki -d hydrawiki -At -c 'SELECT version FROM schema_migrations ORDER BY version' | diff -u "$backup_dir/schema-migrations.txt" -
"${compose[@]}" run --rm api python -m hydrawiki.operational verify
docker volume inspect "$workspace_volume" >/dev/null
docker run --rm -v "$workspace_volume:/target" -v "$backup_dir:/backup:ro" alpine sh -ec 'test -z "$(find /target -mindepth 1 -maxdepth 1 -print -quit)"; tar -C /target -xzf /backup/workspace-data.tar.gz'
"${compose[@]}" up -d api worker
"${compose[@]}" ps
```

The Qdrant upload raises on transport or HTTP failure and exits non-zero unless its JSON response explicitly reports a successful result. The migration-list comparison and `hydrawiki.operational verify` run before API or worker startup; an incompatible or incomplete restore therefore fails closed.

## Required local evidence

Run PostgreSQL integration tests in the disposable Compose project, not with an unset environment variable (which would skip them):

```bash
HYDRAWIKI_TEST_DATABASE_URL=postgresql://hydrawiki:password@postgres:5432/hydrawiki \
  docker compose -p "$project" run --rm --no-deps -v "$PWD/backend:/work:ro" api \
  sh -ec 'pip install --quiet pytest && cd /work && python -m pytest tests/test_operational_integration.py tests/test_api_lifecycle_integration.py tests/test_wiki_generation_integration.py'
```

The tests cover persisted lifecycle/index data across a new store instance, cited wiki publication, and deletion of metadata, chunks, pages, and vector IDs. Run the isolated backup/restore procedure above and retain its terminal output with the change review; do not record secrets or an `.env` file.

Capacity and security review are required before this issue can be completed. Capacity is measured with the chosen fixture and limits recorded by the operator; this repository has no approved fixture size or capacity threshold, so it cannot truthfully define a passing capacity result. The focused security review checks that the project-name guard is present, volumes are derived from the disposable project, no destructive remove command is used, archives are read-only when unpacked, provenance contains no environment values, and Qdrant upload requires both HTTP and result validation.

## Capacity decision record

HYDWIK-9 and the approved implementation plan (reviewed 2026-08-01) require capacity testing but do not define an approved fixture or dataset, workload, metric, or pass/fail threshold. Without all four inputs, a local run would not be a meaningful capacity result and must not be reported as passing. HYDWIK-9 remains In Progress pending an owner decision that supplies those inputs.
