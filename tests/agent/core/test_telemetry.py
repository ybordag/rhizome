import pytest

from agent.core import telemetry
from db.database import current_user_id
from db.models import Thread


class RecordingObserver:
    def __init__(self):
        self.calls = []

    def record_message(self, role, text, *, payload=None, metadata=None):
        self.calls.append(("message", role, text, payload, metadata))

    def record_tool_call_started(self, tool_name, *, payload=None):
        self.calls.append(("tool_started", tool_name, payload))

    def record_tool_call_completed(self, tool_name, *, success, payload=None, error=""):
        self.calls.append(("tool_completed", tool_name, success, payload, error))

    def record_state_snapshot(self, snapshot_name, *, payload=None, tags=None, metadata=None):
        self.calls.append(("snapshot", snapshot_name, payload, tags, metadata))


@pytest.fixture(autouse=True)
def reset_telemetry_state():
    telemetry.set_observer(None)
    telemetry._state.configured_from_env = False
    telemetry._state.tracer_name = "rhizome"
    yield
    telemetry.set_observer(None)
    telemetry._state.configured_from_env = False
    telemetry._state.tracer_name = "rhizome"


@pytest.mark.telemetry
def test_noop_observer_methods_do_not_raise():
    observer = telemetry.NoOpObserver()

    observer.record_message("user", "hi")
    observer.record_tool_call_started("list_projects")
    observer.record_tool_call_completed("list_projects", success=True)
    observer.record_state_snapshot("snapshot")


@pytest.mark.telemetry
def test_set_and_get_observer_work():
    observer = RecordingObserver()

    telemetry.set_observer(observer)

    assert telemetry.get_observer() is observer


@pytest.mark.telemetry
def test_configure_from_env_safe_when_disabled(monkeypatch):
    monkeypatch.delenv("RHIZOME_OTEL_ENABLED", raising=False)

    result = telemetry.configure_from_env()

    assert result in {True, False}


@pytest.mark.telemetry
def test_configure_from_env_safe_when_enabled_without_sdk(monkeypatch):
    monkeypatch.setenv("RHIZOME_OTEL_ENABLED", "1")

    result = telemetry.configure_from_env()

    assert result in {True, False}


@pytest.mark.telemetry
def test_start_span_is_safe_noop_when_tracing_disabled():
    with telemetry.start_span("rhizome.test", {"a": 1}) as span:
        assert span is None


@pytest.mark.telemetry
def test_emit_helpers_forward_to_observer():
    observer = RecordingObserver()
    telemetry.set_observer(observer)

    telemetry.emit_message("assistant", "hello", payload={"turn": 1})
    telemetry.emit_tool_started("list_projects", payload={"status": "active"})
    telemetry.emit_tool_completed("list_projects", success=True, payload={"status": "active"})
    telemetry.emit_state_snapshot("confirmation_requested", payload={"interrupt": "Confirm?"}, tags=["confirmation"])
    telemetry.emit_database_change("update", table="thread", record_id="thread-1", payload={"field": "pinned_context"})

    assert observer.calls[0][0] == "message"
    assert observer.calls[1][0] == "tool_started"
    assert observer.calls[2][0] == "tool_completed"
    assert observer.calls[3][0] == "snapshot"
    assert observer.calls[4] == (
        "snapshot",
        "database_change",
        {
            "operation": "update",
            "table": "thread",
            "record_id": "thread-1",
            "field": "pinned_context",
        },
        ["database", "mutation", "thread"],
        None,
    )


@pytest.mark.telemetry
def test_database_session_commits_emit_sanitized_mutation_snapshots(db_session):
    observer = RecordingObserver()
    telemetry.set_observer(observer)
    token = current_user_id.set("tenant-a")
    thread = Thread(id="thread-telemetry", user_id="tenant-a", title="Initial")

    try:
        db_session.add(thread)
        db_session.commit()
        thread.title = "Updated"
        db_session.commit()
    finally:
        current_user_id.reset(token)

    database_changes = [call for call in observer.calls if call[0] == "snapshot" and call[1] == "database_change"]
    assert (
        "snapshot",
        "database_change",
        {
            "operation": "insert",
            "table": "thread",
            "record_id": "thread-telemetry",
            "model": "Thread",
            "tenant_user_id": "tenant-a",
        },
        ["database", "mutation", "thread"],
        None,
    ) in database_changes
    assert (
        "snapshot",
        "database_change",
        {
            "operation": "update",
            "table": "thread",
            "record_id": "thread-telemetry",
            "model": "Thread",
            "tenant_user_id": "tenant-a",
            "changed_fields": ["title"],
        },
        ["database", "mutation", "thread"],
        None,
    ) in database_changes


@pytest.mark.telemetry
def test_database_session_rollbacks_do_not_emit_mutation_snapshots(db_session):
    observer = RecordingObserver()
    telemetry.set_observer(observer)

    db_session.add(Thread(id="rolled-back-thread", user_id="1", title="Transient"))
    db_session.flush()
    db_session.rollback()

    assert [call for call in observer.calls if call[0] == "snapshot" and call[1] == "database_change"] == []
