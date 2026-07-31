"""PostgreSQL lifecycle tests; run with HYDRAWIKI_TEST_DATABASE_URL."""

import os
from pathlib import Path
from uuid import uuid4

import pytest

from hydrawiki.persistence import Database, RepositoryStore


DATABASE_URL = os.getenv("HYDRAWIKI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="set HYDRAWIKI_TEST_DATABASE_URL for PostgreSQL integration tests")


def test_repository_persists_after_new_store_and_delete_is_idempotent(tmp_path: Path) -> None:
    assert DATABASE_URL
    database = Database(DATABASE_URL)
    store = RepositoryStore(database)
    repository_id = uuid4()
    store.create({"id": repository_id, "source_type": "local", "source_value": "fixture", "selected_ref": None, "display_name": "Fixture"})
    restarted_store = RepositoryStore(Database(DATABASE_URL))
    assert restarted_store.get(repository_id)["display_name"] == "Fixture"
    restarted_store.mark_deleting(repository_id)
    receipt = restarted_store.complete_delete({
        "id": repository_id,
        "source_type": "local",
        "source_value": "fixture",
        "selected_ref": None,
        "display_name": "Fixture",
    })
    assert restarted_store.get(repository_id) is None
    assert receipt["id"] == repository_id
    # A second delete attempt can return the durable receipt without claiming
    # cleanup happened before the first completion transaction.
    assert restarted_store.get_deletion_receipt(repository_id)["display_name"] == "Fixture"
