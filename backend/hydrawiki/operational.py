"""Fail-closed operational checks used before an application is started after restore."""

from .config import validate_settings
from .persistence import Database


def main() -> None:
    settings = validate_settings()
    Database(str(settings.database_url)).verify_schema_compatible()
    print("hydrawiki schema compatibility verified")


if __name__ == "__main__":
    main()
