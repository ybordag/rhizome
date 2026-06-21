"""
Tests for the Rhizome internal FastAPI layer.

Uses FastAPI's TestClient — no real HTTP server needed.
The patched_sessionlocal fixture from conftest wires an in-memory SQLite DB
into all tool modules, so these tests run without Postgres.
"""

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from agent.api.app import app
from db.models import MonitorAlert, MonitorRun, GardenProfile


client = TestClient(app)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Alerts — data router
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_list_alerts_empty(patched_sessionlocal):
    resp = client.get("/internal/data/alerts?user_id=1")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_list_alerts_returns_pending_non_expired(patched_sessionlocal, db_session):
    future = _now() + timedelta(hours=24)
    db_session.add(MonitorAlert(
        expires_at=future, user_id=1, alert_type="triage",
        severity="high", title="Urgent tasks pending", body="3 tasks overdue.",
    ))
    db_session.commit()

    resp = client.get("/internal/data/alerts?user_id=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Urgent tasks pending"
    assert data[0]["severity"] == "high"


@pytest.mark.integration
def test_list_alerts_excludes_expired(patched_sessionlocal, db_session):
    past = _now() - timedelta(hours=1)
    db_session.add(MonitorAlert(
        expires_at=past, user_id=1, alert_type="triage",
        severity="high", title="Old alert", body=".",
    ))
    db_session.commit()

    resp = client.get("/internal/data/alerts?user_id=1")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_list_alerts_excludes_other_users(patched_sessionlocal, db_session):
    future = _now() + timedelta(hours=24)
    db_session.add(MonitorAlert(
        expires_at=future, user_id=99, alert_type="triage",
        severity="high", title="Other user alert", body=".",
    ))
    db_session.commit()

    resp = client.get("/internal/data/alerts?user_id=1")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_dismiss_alert(patched_sessionlocal, db_session):
    future = _now() + timedelta(hours=24)
    alert = MonitorAlert(
        expires_at=future, user_id=1, alert_type="weather_critical",
        severity="critical", title="Frost warning", body="Tasks deferred.",
    )
    db_session.add(alert)
    db_session.commit()

    resp = client.post(f"/internal/data/alerts/{alert.id}/dismiss?user_id=1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"

    # Should no longer appear in list
    resp2 = client.get("/internal/data/alerts?user_id=1")
    assert resp2.json() == []


@pytest.mark.integration
def test_dismiss_alert_wrong_user(patched_sessionlocal, db_session):
    future = _now() + timedelta(hours=24)
    alert = MonitorAlert(
        expires_at=future, user_id=2, alert_type="triage",
        severity="high", title="Other user", body=".",
    )
    db_session.add(alert)
    db_session.commit()

    resp = client.post(f"/internal/data/alerts/{alert.id}/dismiss?user_id=1")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Monitor runs — data router
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_list_monitor_runs_empty(patched_sessionlocal):
    resp = client.get("/internal/data/monitor/runs?user_id=1")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_list_monitor_runs(patched_sessionlocal, db_session):
    db_session.add(MonitorRun(run_type="weather", user_id=1, status="completed", summary="Done."))
    db_session.add(MonitorRun(run_type="triage", user_id=1, status="failed", error="Timeout"))
    db_session.commit()

    resp = client.get("/internal/data/monitor/runs?user_id=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    run_types = {r["run_type"] for r in data}
    assert run_types == {"weather", "triage"}


@pytest.mark.integration
def test_get_monitor_run(patched_sessionlocal, db_session):
    run = MonitorRun(run_type="series_materialization", user_id=1, status="completed", summary="3 tasks created.")
    db_session.add(run)
    db_session.commit()

    resp = client.get(f"/internal/data/monitor/runs/{run.id}?user_id=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_type"] == "series_materialization"
    assert data["status"] == "completed"
    assert "3 tasks" in data["summary"]


@pytest.mark.integration
def test_get_monitor_run_not_found(patched_sessionlocal):
    resp = client.get("/internal/data/monitor/runs/nonexistent-id?user_id=1")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Projects — data router (smoke tests)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_list_projects_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/projects?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_list_tasks_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/tasks?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_daily_tasks_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/tasks/daily?user_id=1")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Garden domain smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_garden_profile(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/garden/profile?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_list_beds_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/garden/beds?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_list_containers_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/garden/containers?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_list_plants_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/garden/plants?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_list_batches_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/garden/batches?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_search_garden_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/garden/search?user_id=1&query=tomato")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Operations smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_list_incidents_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/incidents?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_get_pending_interaction_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/interactions/pending?user_id=1")
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.integration
def test_list_recent_interactions_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/interactions/recent?user_id=1")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Interactions — structured JSON (#136)
# ---------------------------------------------------------------------------

def _make_confirmation_record(db_session, project):
    from agent.domain.interactions import build_confirmation_interaction, record_interaction_summary

    envelope = build_confirmation_interaction(
        [{"name": "delete_project", "args": {"project_id": project.id}}]
    )
    record = record_interaction_summary(
        db_session, envelope, source_type="confirmation", source_id=project.id, project_id=project.id,
    )
    db_session.commit()
    return record


@pytest.mark.integration
def test_get_pending_interaction_returns_envelope(patched_sessionlocal, db_session, seed_garden_profile):
    from tests.support.factories import make_project

    project = make_project(db_session, seed_garden_profile)
    record = _make_confirmation_record(db_session, project)

    resp = client.get("/internal/data/interactions/pending?user_id=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == record.id
    assert body["interaction_type"] == "confirmation_request"
    assert body["status"] == "pending"
    assert body["actions"][0]["id"] == "confirm"
    assert body["sections"][0]["title"] == "Operations"


@pytest.mark.integration
def test_list_recent_interactions_returns_envelope_array(patched_sessionlocal, db_session, seed_garden_profile):
    from tests.support.factories import make_project

    project = make_project(db_session, seed_garden_profile)
    record = _make_confirmation_record(db_session, project)

    resp = client.get("/internal/data/interactions/recent?user_id=1")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == record.id


@pytest.mark.integration
def test_get_interaction_by_id_returns_envelope(patched_sessionlocal, db_session, seed_garden_profile):
    from tests.support.factories import make_project

    project = make_project(db_session, seed_garden_profile)
    record = _make_confirmation_record(db_session, project)

    resp = client.get(f"/internal/data/interactions/{record.id}?user_id=1")
    assert resp.status_code == 200
    assert resp.json()["id"] == record.id


@pytest.mark.integration
def test_get_interaction_by_id_404_when_missing(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/interactions/nonexistent?user_id=1")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_interaction_by_id_404_for_other_users_record(patched_sessionlocal, db_session, seed_garden_profile):
    from db.database import current_user_id
    from tests.support.factories import make_project

    project = make_project(db_session, seed_garden_profile)
    current_user_id.set("owner-a")
    try:
        record = _make_confirmation_record(db_session, project)
    finally:
        current_user_id.set("1")

    resp = client.get(f"/internal/data/interactions/{record.id}?user_id=1")
    assert resp.status_code == 404


@pytest.mark.integration
def test_resolve_interaction_confirm_returns_updated_envelope(patched_sessionlocal, db_session, seed_garden_profile):
    from tests.support.factories import make_project

    project = make_project(db_session, seed_garden_profile)
    record = _make_confirmation_record(db_session, project)

    resp = client.post(
        f"/internal/data/interactions/{record.id}/resolve?user_id=1",
        json={"action": "cancel"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == record.id
    assert body["status"] == "dismissed"
    assert body["resolution_action"] == "cancel"
    assert body["resolved_at"] is not None


@pytest.mark.integration
def test_resolve_interaction_404_when_missing(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(
        "/internal/data/interactions/nonexistent/resolve?user_id=1",
        json={"action": "cancel"},
    )
    assert resp.status_code == 404


@pytest.mark.integration
def test_list_recent_activity_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/activity?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_activity_with_filters(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/activity?user_id=1&category=task&limit=5")
    assert resp.status_code == 200


@pytest.mark.integration
def test_task_activity_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/tasks/nonexistent-id/activity?user_id=1")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Task additions smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_list_due_tasks_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/tasks/due?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_list_blocked_tasks_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/tasks/blocked?user_id=1")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Weather smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_weather_snapshot_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/weather/latest?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_weather_impacted_tasks_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/weather/tasks/impacted?user_id=1")
    assert resp.status_code == 200
