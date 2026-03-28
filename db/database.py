# db/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import Base

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