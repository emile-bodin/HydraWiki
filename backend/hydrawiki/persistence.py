"""Small PostgreSQL persistence boundary for the repository lifecycle."""

from __future__ import annotations

from contextlib import contextmanager
from importlib.resources import files
from typing import Iterator
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, url: str):
        self.url = url

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            yield connection

    def migrate(self) -> None:
        with self.connection() as connection:
            # The transaction-scoped lock serializes every API/worker migrator,
            # including the first creation of schema_migrations itself.
            connection.execute("SELECT pg_advisory_xact_lock(hashtext('hydrawiki.schema_migrations'))")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            applied = {row["version"] for row in connection.execute("SELECT version FROM schema_migrations")}
            migration_files = sorted(files("hydrawiki.migrations").iterdir(), key=lambda item: item.name)
            for migration in migration_files:
                if not migration.name.endswith(".sql") or migration.name in applied:
                    continue
                connection.execute(migration.read_text())
                connection.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (migration.name,))


class RepositoryStore:
    def __init__(self, database: Database):
        self.database = database

    def list(self) -> list[dict]:
        self.database.migrate()
        with self.database.connection() as connection:
            return list(connection.execute("SELECT * FROM repositories ORDER BY created_at DESC"))

    def get(self, repository_id: UUID) -> dict | None:
        self.database.migrate()
        with self.database.connection() as connection:
            return connection.execute("SELECT * FROM repositories WHERE id = %s", (repository_id,)).fetchone()

    def create(self, repository: dict) -> dict:
        self.database.migrate()
        with self.database.connection() as connection:
            return connection.execute(
                """INSERT INTO repositories
                (id, source_type, source_value, selected_ref, display_name, lifecycle_status)
                VALUES (%(id)s, %(source_type)s, %(source_value)s, %(selected_ref)s, %(display_name)s, 'registered')
                RETURNING *""",
                repository,
            ).fetchone()

    def mark_deleting(self, repository_id: UUID) -> dict | None:
        self.database.migrate()
        with self.database.connection() as connection:
            return connection.execute(
                "UPDATE repositories SET lifecycle_status = 'deleting', last_error = NULL, updated_at = now() WHERE id = %s RETURNING *",
                (repository_id,),
            ).fetchone()

    def mark_delete_failed(self, repository_id: UUID, error: str) -> dict | None:
        with self.database.connection() as connection:
            return connection.execute(
                "UPDATE repositories SET lifecycle_status = 'delete_failed', last_error = %s, updated_at = now() WHERE id = %s RETURNING *",
                (error[:2000], repository_id),
            ).fetchone()

    def get_deletion_receipt(self, repository_id: UUID) -> dict | None:
        self.database.migrate()
        with self.database.connection() as connection:
            return connection.execute("SELECT * FROM repository_deletion_receipts WHERE id = %s", (repository_id,)).fetchone()

    def complete_delete(self, repository: dict) -> dict:
        with self.database.connection() as connection:
            receipt = connection.execute(
                """INSERT INTO repository_deletion_receipts
                (id, source_type, source_value, selected_ref, display_name, deleted_at)
                VALUES (%(id)s, %(source_type)s, %(source_value)s, %(selected_ref)s, %(display_name)s, now())
                ON CONFLICT (id) DO UPDATE SET id = EXCLUDED.id
                RETURNING *""",
                repository,
            ).fetchone()
            connection.execute("DELETE FROM repositories WHERE id = %s", (repository["id"],))
            # Cache entries are shared across repositories; only remove entries
            # that became unreferenced with this repository deletion.
            connection.execute(
                "DELETE FROM content_cache WHERE id NOT IN (SELECT content_cache_id FROM source_files) AND id NOT IN (SELECT content_cache_id FROM manifest_entries WHERE content_cache_id IS NOT NULL)"
            )
            return receipt
