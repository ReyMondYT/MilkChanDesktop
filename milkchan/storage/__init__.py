"""Storage abstraction layer"""

from .database import init_db, migrate_from_json

__all__ = ["init_db", "migrate_from_json"]