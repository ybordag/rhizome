# db/database.py
from contextvars import ContextVar

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import Base

# Holds the authenticated user's ID for the current execution context.
# Set once in session_context_intake at the start of every graph run.
# Tools read this instead of hardcoding a user ID.
current_user_id: ContextVar[int] = ContextVar("current_user_id", default=1)

# this is the connection string — for SQLite it's just a file path
# the /// means relative path, so this creates rhizome.db in your project root
DATABASE_URL = "sqlite:///rhizome.db"

# the engine is the actual connection to the database
engine = create_engine(DATABASE_URL, echo=False)
# echo=True would print every SQL statement SQLAlchemy runs — useful for debugging

# sessionmaker creates a factory for database sessions
# a session is like a "unit of work" — you make changes, then commit them all at once
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