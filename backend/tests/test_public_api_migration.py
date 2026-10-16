import re
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from app import models  # noqa: F401; register all ORM tables in Base metadata
from app.core.db import Base

VERSIONS_DIR = Path(__file__).parents[1] / "alembic" / "versions"
# A later migration locks down its own new table by name, e.g. 0021: op.execute('ALTER TABLE public."activity_proof_photos" ENABLE ROW LEVEL SECURITY').
# Editing an already-applied migration would not protect a table on any environment that already ran it, so each new
# table's own creation migration (or a dedicated follow-up) is expected to lock it down, rather than extending 0020 forever.
LITERAL_RLS = re.compile(r'ALTER TABLE public\."([a-zA-Z0-9_]+)" ENABLE ROW LEVEL SECURITY')


def _load_migration(name: str):
    spec = spec_from_file_location(f"migration_{name}", VERSIONS_DIR / f"{name}.py")
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _rls_protected_tables() -> set[str]:
    protected = set(_load_migration("0020_lock_down_public_api").APP_TABLES)
    for path in VERSIONS_DIR.glob("*.py"):
        if path.stem == "0020_lock_down_public_api": continue
        protected.update(LITERAL_RLS.findall(path.read_text()))
    return protected


def test_rls_migration_covers_every_application_table():
    """Every ORM table must be locked down by *some* migration (0020's bulk list, or a later migration's own statement)."""
    assert _rls_protected_tables() == set(Base.metadata.tables)
