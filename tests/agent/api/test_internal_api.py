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
