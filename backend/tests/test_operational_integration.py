"""Restore-compatibility and restart persistence checks; requires PostgreSQL."""
import os
from uuid import uuid4

import pytest
from importlib.resources import files

from hydrawiki.persistence import Database, RepositoryStore

DATABASE_URL = os.getenv("HYDRAWIKI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="set HYDRAWIKI_TEST_DATABASE_URL for PostgreSQL integration tests")


def test_restore_schema_gate_and_restart_store_preserve_lifecycle_and_index_data():
    assert DATABASE_URL
    database = Database(DATABASE_URL)
    database.migrate()
    database.verify_schema_compatible()
    repository_id = uuid4()
    RepositoryStore(database).create({"id": repository_id, "source_type": "local", "source_value": "fixture", "selected_ref": None, "display_name": "Operational"})
    with database.connection() as connection:
        connection.execute("INSERT INTO index_versions (index_version, embedding_model, vector_dimension) VALUES ('operational-index', 'fake', 2) ON CONFLICT DO NOTHING")
        connection.execute("INSERT INTO chunks (id, repository_id, path, content_sha256, ordinal, chunk_text, chunk_sha256, line_start, line_end, chunker_version, embedding_model, index_version, vector_id) VALUES (%s, %s, 'a.py', 'hash', 0, 'x', 'chunk', 1, 1, 'line-v1', 'fake', 'operational-index', 'vector-operational')", (uuid4(), repository_id))
    restarted = RepositoryStore(Database(DATABASE_URL))
    assert restarted.get(repository_id)["display_name"] == "Operational"
    assert restarted.vector_ids(repository_id) == ["vector-operational"]


def test_restore_schema_gate_rejects_unknown_migration():
    assert DATABASE_URL
    database = Database(DATABASE_URL)
    database.migrate()
    with database.connection() as connection:
        connection.execute("INSERT INTO schema_migrations (version) VALUES ('999_incompatible.sql')")
    try:
        with pytest.raises(RuntimeError, match="incompatible"):
            database.verify_schema_compatible()
    finally:
        with database.connection() as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version = '999_incompatible.sql'")


def test_restore_schema_gate_rejects_missing_ingestion_runs_table():
    assert DATABASE_URL
    database = Database(DATABASE_URL)
    database.migrate()
    with database.connection() as connection:
        connection.execute("DROP TABLE ingestion_runs CASCADE")
    try:
        with pytest.raises(RuntimeError, match="ingestion_runs"):
            database.verify_schema_compatible()
    finally:
        with database.connection() as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version = '001_repository_lifecycle.sql'")
            connection.execute(files("hydrawiki.migrations").joinpath("001_repository_lifecycle.sql").read_text())
            connection.execute("INSERT INTO schema_migrations (version) VALUES ('001_repository_lifecycle.sql')")
