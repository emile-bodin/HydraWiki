"""Phase-1 worker process: validate startup configuration and remain available."""

import time

from .config import validate_settings


def run() -> None:
    validate_settings()
    while True:
        time.sleep(60)


if __name__ == "__main__":
    run()
