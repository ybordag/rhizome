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
from tests.db.test_monitor_jobs import fake_open_meteo


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
def test_resolve_interaction_404_for_other_users_record(patched_sessionlocal, db_session, seed_garden_profile):
    from db.database import current_user_id
    from tests.support.factories import make_project

    project = make_project(db_session, seed_garden_profile)
    current_user_id.set("owner-a")
    try:
        record = _make_confirmation_record(db_session, project)
    finally:
        current_user_id.set("1")

    resp = client.post(
        f"/internal/data/interactions/{record.id}/resolve?user_id=1",
        json={"action": "cancel"},
    )
    assert resp.status_code == 404


@pytest.mark.integration
def test_resolve_interaction_already_resolved_returns_current_state(patched_sessionlocal, db_session, seed_garden_profile):
    from tests.support.factories import make_project

    project = make_project(db_session, seed_garden_profile)
    record = _make_confirmation_record(db_session, project)

    first = client.post(
        f"/internal/data/interactions/{record.id}/resolve?user_id=1",
        json={"action": "cancel"},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "dismissed"

    second = client.post(
        f"/internal/data/interactions/{record.id}/resolve?user_id=1",
        json={"action": "confirm"},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "dismissed"
    assert body["resolution_action"] == "cancel"


@pytest.mark.integration
def test_resolve_interaction_request_revision_threads_notes_into_inputs(patched_sessionlocal, db_session, seed_garden_profile):
    from agent.domain.interactions import build_proposal_review_interaction, record_interaction_summary
    from tests.support.factories import make_project, make_project_brief, make_project_proposal

    project = make_project(db_session, seed_garden_profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    db_session.commit()

    envelope = build_proposal_review_interaction(db_session, project.id, proposal.id)
    record = record_interaction_summary(
        db_session, envelope, source_type="proposal_review", source_id=proposal.id, project_id=project.id,
    )
    db_session.commit()

    resp = client.post(
        f"/internal/data/interactions/{record.id}/resolve?user_id=1",
        json={"action": "request_revision", "notes": "Please use raised beds instead."},
    )
    assert resp.status_code == 200
    body = resp.json()
    # "request_revision" is in DISMISSED_ACTIONS (infer_resolution_status) — it's a
    # rejection-with-feedback, not an approval, even though it carries useful notes.
    assert body["status"] == "dismissed"
    assert "Please use raised beds instead." in body["resolution_summary"]


@pytest.mark.integration
def test_list_recent_interactions_filters_by_project_id(patched_sessionlocal, db_session, seed_garden_profile):
    from tests.support.factories import make_project

    project_a = make_project(db_session, seed_garden_profile, name="Project A")
    project_b = make_project(db_session, seed_garden_profile, name="Project B")
    record_a = _make_confirmation_record(db_session, project_a)
    _make_confirmation_record(db_session, project_b)

    resp = client.get(f"/internal/data/interactions/recent?user_id=1&project_id={project_a.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == record_a.id


@pytest.mark.integration
def test_get_pending_interaction_returns_most_recent(patched_sessionlocal, db_session, seed_garden_profile):
    from tests.support.factories import make_project

    project = make_project(db_session, seed_garden_profile)
    _make_confirmation_record(db_session, project)
    newest = _make_confirmation_record(db_session, project)

    resp = client.get("/internal/data/interactions/pending?user_id=1")
    assert resp.status_code == 200
    assert resp.json()["id"] == newest.id


@pytest.mark.integration
def test_get_pending_interaction_excludes_other_users_records(patched_sessionlocal, db_session, seed_garden_profile):
    from db.database import current_user_id
    from tests.support.factories import make_project

    project = make_project(db_session, seed_garden_profile)
    current_user_id.set("owner-a")
    try:
        _make_confirmation_record(db_session, project)
    finally:
        current_user_id.set("1")

    resp = client.get("/internal/data/interactions/pending?user_id=1")
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.integration
def test_get_pending_interaction_skips_stale_empty_triage_view(patched_sessionlocal, db_session, seed_garden_profile):
    from agent.domain.interactions import build_triage_view_interaction, record_interaction_summary
    from db.database import current_user_id
    from tests.support.factories import make_triage_snapshot

    current_user_id.set("1")
    triage = make_triage_snapshot(
        db_session,
        garden_profile_id=seed_garden_profile.id,
        recommended_task_ids=[],
        routine_task_ids=[],
        project_task_ids=[],
    )
    record_interaction_summary(
        db_session,
        build_triage_view_interaction(db_session, triage),
        source_type="triage",
        source_id=triage.id,
    )
    db_session.commit()

    resp = client.get("/internal/data/interactions/pending?user_id=1")

    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.integration
def test_list_recent_activity_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/activity?user_id=1")
    assert resp.status_code == 200


@pytest.mark.integration
def test_activity_with_filters(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/activity?user_id=1&category=task&limit=5")
    assert resp.status_code == 200


@pytest.mark.integration
def test_task_activity_404_for_nonexistent_task(patched_sessionlocal, db_session, seed_garden_profile):
    """#140: activity endpoints now verify the subject exists before
    returning a structured view, so a bogus task id is a 404 — not an
    empty array masquerading as a valid (if uneventful) task."""
    resp = client.get("/internal/data/tasks/nonexistent-id/activity?user_id=1")
    assert resp.status_code == 404


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
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Weather smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_weather_snapshot_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/weather/latest?user_id=1")
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.integration
def test_weather_impacted_tasks_empty(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get("/internal/data/weather/tasks/impacted?user_id=1")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Triage + Weather — structured JSON (#133)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_triage_snapshot_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    """The whole point of #133 for triage: urgent/routine/project task IDs must
    resolve into full TaskSummaryView objects, not bare IDs."""
    from db.models import GardeningProject, Task
    from tests.support.factories import make_triage_snapshot

    project = GardeningProject(
        garden_profile_id=seed_garden_profile.id, user_id="1", name="Test Project", goal="grow", status="active",
    )
    db_session.add(project)
    db_session.commit()

    urgent_task = Task(
        project_id=project.id, title="Water tomatoes", type="maintenance",
        status="pending", generator_key="water.tomato",
    )
    routine_task = Task(
        project_id=project.id, title="Check soil moisture", type="maintenance",
        status="pending", generator_key="soil.check",
    )
    db_session.add_all([urgent_task, routine_task])
    db_session.commit()

    snapshot = make_triage_snapshot(
        db_session,
        garden_profile_id=seed_garden_profile.id,
        urgent_task_ids=[urgent_task.id],
        routine_task_ids=[routine_task.id],
        project_task_ids=[],
        reasoning_summary="Prioritize urgent watering.",
    )

    resp = client.get("/internal/data/triage/latest?user_id=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == snapshot.id
    assert body["reasoning_summary"] == "Prioritize urgent watering."
    assert len(body["urgent_tasks"]) == 1
    assert body["urgent_tasks"][0]["id"] == urgent_task.id
    assert body["urgent_tasks"][0]["title"] == "Water tomatoes"
    assert len(body["routine_tasks"]) == 1
    assert body["routine_tasks"][0]["title"] == "Check soil moisture"
    assert body["project_tasks"] == []


@pytest.mark.integration
def test_get_triage_latest_after_graph_triage_run(patched_sessionlocal, db_session, seed_garden_profile):
    from agent.core import nodes
    from langchain.messages import HumanMessage
    from tests.support.factories import (
        make_project,
        make_project_brief,
        make_project_proposal,
        make_project_revision,
        make_task,
        make_task_generation_run,
    )

    project = make_project(db_session, seed_garden_profile, name="Courtyard Tomatoes")
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project, revision)
    task = make_task(
        db_session,
        project=project,
        revision=revision,
        generation_run=run,
        title="Prepare growbag_1",
    )

    result = nodes.triage_reasoner(
        {
            "messages": [HumanMessage(content="What should I do first?")],
            "session_context": {
                "time_text": "35 minutes",
                "energy_text": "low but focused",
                "focus_text": "Courtyard Tomatoes March 2026",
                "focus_context": [{"subject_type": "project", "subject_id": project.id}],
                "source": "user",
            },
            "user_id": "1",
        }
    )
    assert result["triage_snapshot"]["id"]

    resp = client.get("/internal/data/triage/latest?user_id=1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == result["triage_snapshot"]["id"]
    all_tasks = body["urgent_tasks"] + body["routine_tasks"] + body["project_tasks"]
    assert any(item["id"] == task.id and item["title"] == "Prepare growbag_1" for item in all_tasks)


@pytest.mark.integration
def test_triage_recommendations_route_not_registered(patched_sessionlocal):
    resp = client.get("/internal/data/triage/recommendations?user_id=1")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_weather_snapshot_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    from tests.support.factories import make_weather_snapshot

    snapshot = make_weather_snapshot(db_session, garden_profile_id=seed_garden_profile.id, location_label="Test Garden")

    resp = client.get("/internal/data/weather/latest?user_id=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == snapshot.id
    assert body["location_label"] == "Test Garden"
    assert body["derived_impacts"][0]["impact_type"] == "heat"
    assert body["recommended_actions"][0]["action"] == "Prioritize watering and shade protection."


@pytest.mark.integration
def test_refresh_weather_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile, fake_open_meteo):
    resp = client.post("/internal/data/weather/refresh?user_id=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"]
    assert body["location_label"]
    assert "conditions_summary" in body


@pytest.mark.integration
def test_refresh_weather_400_when_no_location(patched_sessionlocal, db_session):
    from tests.support.factories import make_profile

    make_profile(db_session, latitude=None, longitude=None)
    db_session.commit()

    resp = client.post("/internal/data/weather/refresh?user_id=1")
    assert resp.status_code == 400


@pytest.mark.integration
def test_weather_impacted_tasks_returns_structured_array(patched_sessionlocal, db_session, seed_garden_profile):
    from tests.support.factories import (
        make_project, make_project_brief, make_project_proposal, make_project_revision,
        make_task, make_task_generation_run,
    )

    from tests.support.factories import make_weather_snapshot

    project = make_project(db_session, seed_garden_profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project, revision)
    task = make_task(
        db_session, project, revision, run,
        title="Water tomatoes", generator_key="water.tomato",
        status="pending",
    )
    # default derived_impacts includes a "heat" impact; task title contains "water"
    # -> _task_intents() tags it "water" -> heat+water is a matching combination.
    make_weather_snapshot(db_session, garden_profile_id=seed_garden_profile.id)

    resp = client.get(f"/internal/data/weather/tasks/impacted?user_id=1&project_id={project.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["task_id"] == task.id
    assert body[0]["impact_type"] == "heat"


@pytest.mark.integration
def test_approve_weather_changes_404_when_missing(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch("/internal/data/weather/changesets/nonexistent/approve?user_id=1")
    assert resp.status_code == 404


@pytest.mark.integration
def test_approve_weather_changes_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    from agent.domain.weather import draft_weather_task_changes
    from agent.tools.projects.tracker import generate_project_tasks
    from db.models import WeatherTaskChangeSet
    from tests.support.factories import make_weather_snapshot
    from tests.tools.projects.test_task_tracker_tools import _accept_plan

    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    generate_project_tasks.invoke({"project_id": project.id})
    make_weather_snapshot(
        db_session,
        derived_impacts=[{"date": "2026-04-14", "impact_type": "frost", "severity": "high", "summary": "Frost risk."}],
    )
    draft_weather_task_changes(db_session, project_id=project.id)
    db_session.commit()
    change_set = db_session.query(WeatherTaskChangeSet).order_by(WeatherTaskChangeSet.created_at.desc()).first()

    resp = client.patch(f"/internal/data/weather/changesets/{change_set.id}/approve?user_id=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == change_set.id
    assert body["status"] == "approved"
    assert body["approved_at"] is not None


@pytest.mark.integration
def test_approve_weather_changes_400_when_already_approved(patched_sessionlocal, db_session, seed_garden_profile):
    from agent.domain.weather import draft_weather_task_changes
    from agent.tools.projects.tracker import generate_project_tasks
    from db.models import WeatherTaskChangeSet
    from tests.support.factories import make_weather_snapshot
    from tests.tools.projects.test_task_tracker_tools import _accept_plan

    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    generate_project_tasks.invoke({"project_id": project.id})
    make_weather_snapshot(
        db_session,
        derived_impacts=[{"date": "2026-04-14", "impact_type": "frost", "severity": "high", "summary": "Frost risk."}],
    )
    draft_weather_task_changes(db_session, project_id=project.id)
    db_session.commit()
    change_set = db_session.query(WeatherTaskChangeSet).order_by(WeatherTaskChangeSet.created_at.desc()).first()

    first = client.patch(f"/internal/data/weather/changesets/{change_set.id}/approve?user_id=1")
    assert first.status_code == 200

    second = client.patch(f"/internal/data/weather/changesets/{change_set.id}/approve?user_id=1")
    assert second.status_code == 400
