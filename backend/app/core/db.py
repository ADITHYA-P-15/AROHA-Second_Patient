import time

from sqlalchemy import create_engine, event, exc
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
# A larger pool: many users hit the API at once and each request holds a connection while it works.
pool_args = {} if settings.database_url.startswith("sqlite") else {"pool_size": 10, "max_overflow": 30, "pool_timeout": 20}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=False, pool_recycle=300, **pool_args)
# pool_pre_ping would spend one network round trip on every checkout (about 0.17 s when the database is in another region).
# Only a connection that sat idle long enough to have been dropped is tested, and a dead one is replaced transparently.
IDLE_PING_SECONDS = 30


@event.listens_for(engine, "checkin")
def _stamp_idle(dbapi_connection, record):
    record.info["idle_since"] = time.monotonic()


@event.listens_for(engine, "checkout")
def _ping_if_idle(dbapi_connection, record, proxy):
    idle_since = record.info.get("idle_since")
    if idle_since is None or time.monotonic() - idle_since < IDLE_PING_SECONDS:
        return
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
    except Exception as error:
        raise exc.DisconnectionError() from error


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# A counter that moves whenever any transaction that wrote something commits. Read-heavy endpoints key short-lived caches on it,
# so a cached answer can never outlive a change made by this process. (One instance only: see docs/DEPLOYMENT.md.)
_data_version = 0


def data_version() -> int:
    return _data_version


@event.listens_for(Session, "after_flush")
def _note_write(session, flush_context):
    session.info["wrote"] = True


@event.listens_for(Session, "after_commit")
def _bump_version(session):
    global _data_version
    if session.info.pop("wrote", False):
        _data_version += 1


@event.listens_for(Session, "after_rollback")
def _forget_write(session):
    session.info.pop("wrote", None)
