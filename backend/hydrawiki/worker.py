"""Phase-1 worker process: validate startup configuration and remain available."""

import time

from .config import validate_settings
from .persistence import Database


def run() -> None:
    settings = validate_settings()
    Database(str(settings.database_url)).migrate()
    while True:
        time.sleep(60)


if __name__ == "__main__":
    run()
