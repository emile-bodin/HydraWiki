"""Phase-1 worker process: validate startup configuration and remain available."""

import time

from .config import validate_settings
from .manifest import ManifestResult, run_manifest
from .persistence import Database


def execute_manifest(database: Database, settings, repository: dict) -> ManifestResult:
    """Worker boundary shared by the API-triggered and background execution paths."""

    return run_manifest(database, settings, repository)


def run() -> None:
    settings = validate_settings()
    database = Database(str(settings.database_url))
    database.verify_schema_compatible()
    while True:
        time.sleep(60)


if __name__ == "__main__":
    run()
