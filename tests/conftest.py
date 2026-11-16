import os

os.environ["DATABASE_URL"] = "sqlite://"  # in-memory for tests
os.environ["ADMIN_API_KEY"] = "test-key"
os.environ["REPORTS_DIR"] = "/tmp/bm_reports"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from scripts.seed_flats import seed


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed(session)
    yield session
    session.close()
