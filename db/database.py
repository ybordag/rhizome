# db/database.py
import os
from contextvars import ContextVar

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import Base

# Holds the authenticated user's ID for the current execution context.
# Set once in session_context_intake at the start of every graph run.
# Tools read this instead of hardcoding a user ID.
current_user_id: ContextVar[int] = ContextVar("current_user_id", default=1)

# DATABASE_URL drives the backend:
#   - unset / sqlite:///...  → local SQLite file (dev/test)
#   - postgresql://...       → shared Postgres instance (staging/prod)
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///rhizome.db")

_is_postgres = DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    # pool_pre_ping detects stale connections after a Postgres restart
    pool_pre_ping=_is_postgres,
)

SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Create all tables if they don't exist yet."""
    Base.metadata.create_all(engine)


def get_session():
    """Get a database session. Always close it when done."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()