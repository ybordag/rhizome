"""
Tests for the notification endpoints (#130):
  GET /internal/data/notifications/stream  — SSE event bus
  GET /internal/data/notifications         — sync state snapshot

The stream endpoint is tested at the async-generator level rather than
through FastAPI TestClient's HTTP transport. TestClient does not reliably
drive a long-lived/infinite async generator (the same limitation already
documented for /internal/agent/stream in tests/DEFERRED_TESTS.md) — calling
the route function directly and pulling from response.body_iterator is the
precedented approach in this codebase.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import agent.api.routers as routers
from agent.api.app import app
from agent.domain import notifications
from db.models import InteractionRecord, MonitorAlert

client = TestClient(app)
USER = "1"


@pytest.fixture(autouse=True)
def _clean_registry():
    notifications._user_queues.clear()
    notifications._active_jobs.clear()
    yield
    notifications._user_queues.clear()
    notifications._active_jobs.clear()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# GET /notifications/stream — generator-level tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_stream_creates_queue_on_connect():
    resp = await routers.notification_stream(user_id="stream-user-1")
    assert notifications.has_active_queue("stream-user-1") is True
    await resp.body_iterator.aclose()


@pytest.mark.anyio
async def test_stream_removes_queue_on_close(monkeypatch):
    # Async generators are lazy — the body (and its `finally`) only starts
    # running once advanced at least once. Mirrors a real client that reads
    # at least the first event/heartbeat before disconnecting.
    monkeypatch.setattr(routers, "NOTIFICATION_HEARTBEAT_SECONDS", 0.02)
    resp = await routers.notification_stream(user_id="stream-user-2")
    assert notifications.has_active_queue("stream-user-2") is True
    await resp.body_iterator.__anext__()
    await resp.body_iterator.aclose()
    assert notifications.has_active_queue("stream-user-2") is False


@pytest.mark.anyio
async def test_stream_emits_heartbeat_on_timeout(monkeypatch):
    monkeypatch.setattr(routers, "NOTIFICATION_HEARTBEAT_SECONDS", 0.02)
    resp = await routers.notification_stream(user_id="stream-user-3")
    chunk = await resp.body_iterator.__anext__()
    assert json.loads(chunk.removeprefix("data: ").strip()) == {"type": "heartbeat"}
    await resp.body_iterator.aclose()


@pytest.mark.anyio
async def test_stream_delivers_pushed_event_immediately():
    resp = await routers.notification_stream(user_id="stream-user-4")
    notifications.push_event("stream-user-4", {"type": "alert", "payload": {"id": "a1"}})
    chunk = await resp.body_iterator.__anext__()
    assert json.loads(chunk.removeprefix("data: ").strip()) == {"type": "alert", "payload": {"id": "a1"}}
    await resp.body_iterator.aclose()


@pytest.mark.anyio
async def test_stream_response_media_type():
    resp = await routers.notification_stream(user_id="stream-user-5")
    assert resp.media_type == "text/event-stream"
    await resp.body_iterator.aclose()


# ---------------------------------------------------------------------------
# GET /notifications — sync snapshot
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_notifications_includes_pending_alert(patched_sessionlocal, db_session, seed_garden_profile):
    alert = MonitorAlert(
        expires_at=_now() + timedelta(hours=24),
        user_id=USER,
        alert_type="triage",
        severity="high",
        title="Urgent tasks",
        body="3 urgent tasks today",
        status="pending",
    )
    db_session.add(alert)
    db_session.commit()

    resp = client.get(f"/internal/data/notifications?user_id={USER}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["alerts"]) == 1
    assert data["alerts"][0]["title"] == "Urgent tasks"


@pytest.mark.integration
def test_get_notifications_excludes_dismissed_alert(patched_sessionlocal, db_session, seed_garden_profile):
    alert = MonitorAlert(
        expires_at=_now() + timedelta(hours=24),
        user_id=USER,
        alert_type="triage",
        severity="high",
        title="Old alert",
        body="...",
        status="dismissed",
    )
    db_session.add(alert)
    db_session.commit()

    resp = client.get(f"/internal/data/notifications?user_id={USER}")
    assert resp.json()["alerts"] == []


@pytest.mark.integration
def test_get_notifications_excludes_other_user_alert(patched_sessionlocal, db_session, seed_garden_profile):
    alert = MonitorAlert(
        expires_at=_now() + timedelta(hours=24),
        user_id="other-user",
        alert_type="triage",
        severity="high",
        title="Not yours",
        body="...",
        status="pending",
    )
    db_session.add(alert)
    db_session.commit()

    resp = client.get(f"/internal/data/notifications?user_id={USER}")
    assert resp.json()["alerts"] == []


@pytest.mark.integration
def test_get_notifications_excludes_expired_alert(patched_sessionlocal, db_session, seed_garden_profile):
    alert = MonitorAlert(
        expires_at=_now() - timedelta(hours=1),
        user_id=USER,
        alert_type="triage",
        severity="high",
        title="Expired",
        body="...",
        status="pending",
    )
    db_session.add(alert)
    db_session.commit()

    resp = client.get(f"/internal/data/notifications?user_id={USER}")
    assert resp.json()["alerts"] == []


@pytest.mark.integration
def test_get_notifications_since_filters_alerts(patched_sessionlocal, db_session, seed_garden_profile):
    cutoff = _now()
    old_alert = MonitorAlert(
        expires_at=_now() + timedelta(hours=24),
        user_id=USER,
        alert_type="triage",
        severity="high",
        title="Old",
        body="...",
        status="pending",
        created_at=cutoff - timedelta(hours=2),
    )
    new_alert = MonitorAlert(
        expires_at=_now() + timedelta(hours=24),
        user_id=USER,
        alert_type="triage",
        severity="high",
        title="New",
        body="...",
        status="pending",
        created_at=cutoff + timedelta(hours=1),
    )
    db_session.add_all([old_alert, new_alert])
    db_session.commit()

    resp = client.get(f"/internal/data/notifications?user_id={USER}&since={cutoff.isoformat()}")
    titles = [a["title"] for a in resp.json()["alerts"]]
    assert titles == ["New"]


@pytest.mark.integration
def test_get_notifications_includes_pending_interaction(patched_sessionlocal, db_session, seed_garden_profile):
    record = InteractionRecord(
        interaction_type="confirmation",
        status="pending",
        title="Confirm deletion",
        summary="Delete bed X?",
        source_type="tool_call",
    )
    db_session.add(record)
    db_session.commit()

    resp = client.get(f"/internal/data/notifications?user_id={USER}")
    interactions = resp.json()["pending_interactions"]
    assert len(interactions) == 1
    assert interactions[0]["title"] == "Confirm deletion"


@pytest.mark.integration
def test_get_notifications_excludes_resolved_interaction(patched_sessionlocal, db_session, seed_garden_profile):
    record = InteractionRecord(
        interaction_type="confirmation",
        status="resolved",
        title="Already handled",
        summary="...",
        source_type="tool_call",
    )
    db_session.add(record)
    db_session.commit()

    resp = client.get(f"/internal/data/notifications?user_id={USER}")
    assert resp.json()["pending_interactions"] == []


@pytest.mark.integration
def test_get_notifications_includes_active_jobs(patched_sessionlocal, db_session, seed_garden_profile):
    notifications.push_event(USER, {"type": "job_started", "job_id": "job-1", "title": "Daily triage"})
    notifications.push_event(USER, {"type": "job_step", "job_id": "job-1", "step": "Scoring tasks", "status": "running"})

    resp = client.get(f"/internal/data/notifications?user_id={USER}")
    jobs = resp.json()["active_jobs"]
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "job-1"
    assert jobs[0]["steps"] == [{"step": "Scoring tasks", "status": "running"}]


@pytest.mark.integration
def test_get_notifications_empty_state(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get(f"/internal/data/notifications?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json() == {"alerts": [], "pending_interactions": [], "active_jobs": []}
