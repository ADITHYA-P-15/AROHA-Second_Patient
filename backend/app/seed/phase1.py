"""Synthetic accounts, patients and care teams introduced in Phase 1."""

from sqlalchemy.orm import Session

from app.seed import register

def seed_phase1(db: Session) -> None:
    # The fixture builder is kept with Phase 1's auth/patient API implementation.
    from app.main import seed
    seed(db)

register(10, "phase1-synthetic-foundation", seed_phase1)
