from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
# A larger pool: many users hit the API at once and each request holds a connection while it works.
pool_args = {} if settings.database_url.startswith("sqlite") else {"pool_size": 10, "max_overflow": 30, "pool_timeout": 20}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True, **pool_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
