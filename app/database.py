from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings

is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}
# In-memory SQLite (used by tests) needs one shared connection or each connection sees an empty DB.
extra = {"poolclass": StaticPool} if settings.database_url in ("sqlite://", "sqlite:///:memory:") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, **extra)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
