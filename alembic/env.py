"""Alembic environment — Rhizome schema migrations.

- Targets the `rhizome` schema in Postgres.
- DATABASE_URL is read from the environment (same as db/database.py).
- search_path=rhizome is set on every connection so autogenerate and
  upgrade operate on the correct schema.
- Tests use SQLite via init_db() and never run Alembic.
"""

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# Ensure the project root is on sys.path so db.models is importable.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from db.models import Base  # noqa: E402

target_metadata = Base.metadata

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Alembic tracks applied migrations in rhizome.alembic_version.
SCHEMA = "rhizome"


def get_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Alembic requires a Postgres connection. "
            "Export DATABASE_URL before running alembic commands."
        )
    return DATABASE_URL


def run_migrations_offline() -> None:
    """Generate SQL without a live DB connection."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        version_table="alembic_version",
        version_table_schema=SCHEMA,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live DB connection."""
    engine = create_engine(
        get_url(),
        poolclass=pool.NullPool,
        connect_args={"options": f"-csearch_path={SCHEMA}"},
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table="alembic_version",
            version_table_schema=SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
