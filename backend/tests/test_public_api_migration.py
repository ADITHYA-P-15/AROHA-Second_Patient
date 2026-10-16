from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from app import models  # noqa: F401; register all ORM tables in Base metadata
from app.core.db import Base


def test_rls_migration_covers_every_application_table():
    migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "0015_lock_down_public_api.py"
    spec = spec_from_file_location("migration_lock_down_public_api", migration_path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert set(migration.APP_TABLES) == set(Base.metadata.tables)
