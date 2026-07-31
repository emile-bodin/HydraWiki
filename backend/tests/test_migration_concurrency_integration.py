"""Concurrent PostgreSQL migration coverage; run with HYDRAWIKI_TEST_DATABASE_URL."""

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from hydrawiki.persistence import Database


DATABASE_URL = os.getenv("HYDRAWIKI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="set HYDRAWIKI_TEST_DATABASE_URL for PostgreSQL integration tests")


def test_concurrent_migrators_serialize_on_advisory_lock() -> None:
    assert DATABASE_URL
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: Database(DATABASE_URL).migrate(), range(2)))
    assert results == [None, None]
