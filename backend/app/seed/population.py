"""Practical-size fictional population: more families, caretakers and hospital staff, with 30 days of history."""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.seed import register

log = logging.getLogger("second_patient")


def seed_population(db: Session) -> None:
    if not settings.demo_population: return
    from app.services import population
    try:
        counts = population.ensure(db)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("demo population failed; the core demo story is unaffected")
        return
    if counts: log.info("demo population built: %s", counts)


register(20, "demo-population", seed_population)
