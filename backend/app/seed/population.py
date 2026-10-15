"""Practical-size fictional population: more families, caretakers and hospital staff, with 30 days of history.

It is built in the background after the server is already listening (see `build_in_background`), not before it, so a
small or throttled host does not hold the whole site back while about two thousand records are written.
"""
import logging

from app.core.config import settings

log = logging.getLogger("second_patient")


def build_in_background() -> None:
    """Runs in a worker thread at start-up. Idempotent: it does nothing once this version of the population exists."""
    if not (settings.seed_demo and settings.demo_population): return
    from app.core.db import SessionLocal
    from app.services import population
    db = SessionLocal()
    try:
        counts = population.ensure(db)
        db.commit()
        if counts: log.info("demo population built: %s", counts)
        # The directory lists the population caretakers once they exist (idempotent).
        from app.seed.directory import attach_population
        if attach_population(db): db.commit()
        from app.seed import checkins as checkins_seed, reputation as reputation_seed
        if checkins_seed.ensure(db): db.commit()
        if reputation_seed.ensure(db): db.commit()
    except Exception:
        db.rollback()
        log.exception("demo population failed; the core demo story is unaffected")
    finally:
        db.close()
