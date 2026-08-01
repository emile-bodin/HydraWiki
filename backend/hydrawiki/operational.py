"""Explicit schema bootstrap and fail-closed restore checks."""

import argparse

from .config import validate_settings
from .persistence import Database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("bootstrap", "verify"), default="verify", nargs="?")
    args = parser.parse_args()
    settings = validate_settings()
    database = Database(str(settings.database_url))
    if args.command == "bootstrap":
        database.migrate()
    database.verify_schema_compatible()
    print(f"hydrawiki schema {args.command} verified")


if __name__ == "__main__":
    main()
