# db/database.py
import os
from contextvars import ContextVar

from sqlalchemy import create_engine
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker
from db.models import Base

# Holds the authenticated user's ID for the current execution context.
# Set once in session_context_intake at the start of every graph run.
# Tools read this instead of hardcoding a user ID.
current_user_id: ContextVar[str] = ContextVar("current_user_id", default="1")

# DATABASE_URL drives the backend:
#   - unset / sqlite:///...  → local SQLite file (dev/test)
#   - postgresql://...       → shared Postgres instance (staging/prod)
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///rhizome.db")

_is_postgres = DATABASE_URL.startswith("postgresql") or DATABASE_URL.startswith("postgres")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=_is_postgres,
    # Route all queries to the rhizome schema in Postgres.
    # SQLite (dev/test) ignores connect_args.
    connect_args={"options": "-csearch_path=rhizome"} if _is_postgres else {},
)

SessionLocal = sessionmaker(bind=engine)


def _object_identity(obj) -> str | None:
    state = inspect(obj)
    if state.identity:
        return ":".join(str(part) for part in state.identity)
    values = []
    for column in state.mapper.primary_key:
        value = getattr(obj, column.key, None)
        if value is None:
            return None
        values.append(str(value))
    return ":".join(values)


def _changed_column_names(obj) -> list[str]:
    state = inspect(obj)
    changed = []
    for attr in state.mapper.column_attrs:
        if state.attrs[attr.key].history.has_changes():
            changed.append(attr.key)
    return sorted(changed)


def _record_session_change(session, operation: str, obj, *, changed_fields: list[str] | None = None) -> None:
    state = inspect(obj)
    changes = session.info.setdefault("_rhizome_database_changes", [])
    changes.append(
        {
            "operation": operation,
            "table": state.mapper.local_table.name,
            "model": obj.__class__.__name__,
            "record_id": _object_identity(obj),
            "tenant_user_id": str(current_user_id.get()),
            **({"changed_fields": changed_fields} if changed_fields else {}),
        }
    )


@event.listens_for(OrmSession, "after_flush")
def _capture_database_changes(session, flush_context):
    for obj in session.new:
        if inspect(obj).mapper is not None:
            _record_session_change(session, "insert", obj)
    for obj in session.dirty:
        if not session.is_modified(obj, include_collections=False):
            continue
        changed_fields = _changed_column_names(obj)
        if changed_fields:
            _record_session_change(session, "update", obj, changed_fields=changed_fields)
    for obj in session.deleted:
        if inspect(obj).mapper is not None:
            _record_session_change(session, "delete", obj)


@event.listens_for(OrmSession, "after_commit")
def _emit_database_changes(session):
    changes = session.info.pop("_rhizome_database_changes", [])
    if not changes:
        return
    from agent.core.telemetry import emit_database_change

    for change in changes:
        emit_database_change(
            change.pop("operation"),
            table=change.pop("table"),
            record_id=change.pop("record_id"),
            payload=change,
        )


@event.listens_for(OrmSession, "after_rollback")
def _clear_database_changes(session):
    session.info.pop("_rhizome_database_changes", None)


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
