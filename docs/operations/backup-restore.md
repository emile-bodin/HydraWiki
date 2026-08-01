# Backup, restore, restart, and MVP evidence

## Scope and persistent data

PostgreSQL is authoritative for repositories, lifecycle/deletion receipts, manifest runs and entries, indexed source content/cache, chunks, index metadata, generation runs/artifacts/diagrams, wiki pages, citations, and durable errors. Qdrant is derived but persistent and stores the chunk vectors. The Compose `workspace-data` volume holds managed public-checkout and manifest workspace data. Local repositories are host-owned read-only inputs and are not HydraWiki backup data. LiteLLM and Ollama are external services and are neither backed up nor called by these checks.

The named `postgres-data`, `qdrant-data`, and `workspace-data` volumes are the durable Compose state. Their capacity, host filesystem ownership, Docker-volume driver, and backup retention are deployment decisions; this repository does not claim or impose CPU/memory limits or a host backup policy.

## Backup

Stop writers first so the PostgreSQL dump and Qdrant snapshot describe the same application point. Record the image/tag, Compose file revision, `docker compose config`, and the migration list with the backup.

```bash
mkdir -p backups/$(date +%F)
docker compose exec -T postgres pg_dump -U hydrawiki -d hydrawiki --format=custom > backups/$(date +%F)/hydrawiki.pg.dump
docker compose run --rm --no-deps api python -c 'import httpx; print(httpx.post("http://qdrant:6333/collections/hydrawiki/snapshots").text)' > backups/$(date +%F)/qdrant-snapshot.json
# Copy the snapshot named in qdrant-snapshot.json from /qdrant/snapshots/hydrawiki/.
docker compose cp qdrant:/qdrant/snapshots/hydrawiki/SNAPSHOT_NAME backups/$(date +%F)/qdrant.snapshot
docker run --rm -v hydrawiki_workspace-data:/source:ro -v "$PWD/backups/$(date +%F):/backup alpine tar -C /source -czf /backup/workspace-data.tar.gz .
```

Stop if any command fails; a PostgreSQL dump alone is not a complete backup when vectors or managed workspaces are required.

## Restore and compatibility gate

Restore into an isolated Compose project with empty named volumes. Do not point this at production volumes.

```bash
docker compose up -d postgres qdrant
cat backups/DATE/hydrawiki.pg.dump | docker compose exec -T postgres pg_restore -U hydrawiki -d hydrawiki --clean --if-exists
docker compose run --rm --no-deps -T api sh -c 'cat >/tmp/hydrawiki.snapshot && python -c "import httpx; print(httpx.post(\"http://qdrant:6333/collections/hydrawiki/snapshots/upload\", files={\"snapshot\": open(\"/tmp/hydrawiki.snapshot\", \"rb\")}).text)"' < backups/DATE/qdrant.snapshot
docker run --rm -v hydrawiki_workspace-data:/target -v "$PWD/backups/DATE:/backup:ro alpine sh -c 'rm -rf /target/* && tar -C /target -xzf /backup/workspace-data.tar.gz'
docker compose run --rm api python -m hydrawiki.operational verify
```

The final command is mandatory before starting API/worker normally. It verifies before any migration that the migration history is exactly the release migration set and that every lifecycle/index/wiki/deletion table exists. Missing, incompatible, or incomplete restores fail non-zero and must be repaired or restored again; do not run migrations as a substitute for restore verification. Fresh deployment or intentional upgrades use the separate Compose `schema` bootstrap service.

## Restart and end-to-end evidence

Run the PostgreSQL integration suite with an isolated test database and test doubles only:

```bash
export HYDRAWIKI_TEST_DATABASE_URL=postgresql://hydrawiki:password@localhost:5432/hydrawiki_test
backend/.venv/bin/python -m pytest backend/tests/test_operational_integration.py backend/tests/test_api_lifecycle_integration.py backend/tests/test_wiki_generation_integration.py
```

Expected evidence is: repository registration, durable manifest progress and indexed source, cited published page, a new application/store instance reading the same data, and deletion leaving no repository metadata, chunks, pages, or vector IDs. The API deletion path removes Qdrant IDs before its relational cascade; a vector-delete failure yields `delete_failed`, not a false success.

For an actual Compose restart, use an isolated project and run the same flow, then:

```bash
docker compose restart api worker postgres qdrant
docker compose ps
```

Expect healthy PostgreSQL/Qdrant and the operator API to return the pre-restart repository/source/page state. Stop and investigate if a container restarts without its named volume, a healthcheck fails, or ownership prevents API/worker access to `workspace-data`.
