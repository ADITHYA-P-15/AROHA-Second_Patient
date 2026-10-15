"""Demo care plan: built once per scenario version, relative to the app clock. See app/services/demo.py."""
from sqlalchemy.orm import Session

from app.services import demo


def seed_phase2(db: Session) -> None:
    demo.ensure(db)
