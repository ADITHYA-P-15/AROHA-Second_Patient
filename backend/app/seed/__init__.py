"""Ordered, idempotent seed registry. Each phase registers its own data module."""

from collections.abc import Callable
from sqlalchemy.orm import Session

SeedFunction = Callable[[Session], None]
_registry: list[tuple[int, str, SeedFunction]] = []

def register(order: int, name: str, fn: SeedFunction) -> None:
    if any(existing == name for _, existing, _ in _registry):
        return
    _registry.append((order, name, fn))

def run_seed(db: Session | None = None) -> None:
    from app.seed import phase1  # noqa: F401
    own_session = db is None
    if own_session:
        from app.core.db import SessionLocal
        db = SessionLocal()
    try:
        for _, _, seed_fn in sorted(_registry, key=lambda item: item[0]):
            seed_fn(db)
    finally:
        if own_session:
            db.close()
