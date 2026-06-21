"""
Tests for #134: GET /internal/data/activity (the global activity feed) now
returns ActivityEventView[] instead of {"result": "<prose>"}. Every
per-entity activity endpoint already returned this shape as of #140 — this
was the one global endpoint left over, per docs/architecture/api-reference.md's
"Still returns {"result": "<prose>"}" note.
"""
import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from db.database import current_user_id
from tests.support.factories import make_project

client = TestClient(app)
USER = "1"


def _record_event(db_session, **overrides):
    from agent.domain.activity_log import record_activity_event

    data = {
        "actor_type": "agent",
        "actor_label": "rhizome_tool",
        "event_type": "task_created",
        "category": "task",
        "summary": "Created a task.",
    }
    data.update(overrides)
    token = current_user_id.set(overrides.get("_user_id", USER))
    try:
        event = record_activity_event(db_session, **{k: v for k, v in data.items() if k != "_user_id"})
        db_session.commit()
        return event
    finally:
        current_user_id.reset(token)


@pytest.mark.integration
def test_list_recent_activity_empty_returns_empty_array(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get(f"/internal/data/activity?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_list_recent_activity_returns_structured_events_with_subjects(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    _record_event(
        db_session,
        event_type="project_created",
        category="project",
        summary="Created project.",
        project_id=project.id,
        subjects=[{"subject_type": "project", "subject_id": project.id, "role": "primary"}],
    )

    resp = client.get(f"/internal/data/activity?user_id={USER}")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "project_created"
    assert events[0]["category"] == "project"
    assert events[0]["project_id"] == project.id
    assert events[0]["subjects"] == [{"subject_type": "project", "subject_id": project.id, "role": "primary"}]


@pytest.mark.integration
def test_list_recent_activity_filters_by_category(patched_sessionlocal, db_session, seed_garden_profile):
    _record_event(db_session, event_type="task_created", category="task", summary="Task event")
    _record_event(db_session, event_type="incident_reported", category="incident", summary="Incident event")

    resp = client.get(f"/internal/data/activity?user_id={USER}&category=incident")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["category"] == "incident"


@pytest.mark.integration
def test_list_recent_activity_filters_by_event_type(patched_sessionlocal, db_session, seed_garden_profile):
    _record_event(db_session, event_type="task_created", category="task", summary="Created")
    _record_event(db_session, event_type="task_completed", category="task", summary="Completed")

    resp = client.get(f"/internal/data/activity?user_id={USER}&event_type=task_completed")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "task_completed"


@pytest.mark.integration
def test_list_recent_activity_filters_by_project_id(patched_sessionlocal, db_session, seed_garden_profile):
    project_a = make_project(db_session, seed_garden_profile, name="Project A")
    project_b = make_project(db_session, seed_garden_profile, name="Project B")
    _record_event(db_session, event_type="task_created", category="task", summary="A", project_id=project_a.id)
    _record_event(db_session, event_type="task_created", category="task", summary="B", project_id=project_b.id)

    resp = client.get(f"/internal/data/activity?user_id={USER}&project_id={project_a.id}")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["summary"] == "A"


@pytest.mark.integration
def test_list_recent_activity_filters_by_subject_type(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    _record_event(
        db_session, event_type="task_created", category="task", summary="Has bed subject",
        subjects=[{"subject_type": "bed", "subject_id": "bed-1", "role": "primary"}],
    )
    _record_event(db_session, event_type="task_created", category="task", summary="No subjects")

    resp = client.get(f"/internal/data/activity?user_id={USER}&subject_type=bed")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["summary"] == "Has bed subject"


@pytest.mark.integration
def test_list_recent_activity_respects_limit(patched_sessionlocal, db_session, seed_garden_profile):
    for i in range(5):
        _record_event(db_session, event_type="task_created", category="task", summary=f"Event {i}")

    resp = client.get(f"/internal/data/activity?user_id={USER}&limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.integration
def test_list_recent_activity_invalid_since_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get(f"/internal/data/activity?user_id={USER}&since=not-a-date")
    assert resp.status_code == 400


@pytest.mark.integration
def test_list_recent_activity_invalid_before_timestamp_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get(f"/internal/data/activity?user_id={USER}&before_timestamp=garbage")
    assert resp.status_code == 400


@pytest.mark.integration
def test_list_recent_activity_excludes_other_users_events(patched_sessionlocal, db_session, seed_garden_profile):
    _record_event(db_session, event_type="task_created", category="task", summary="Mine", _user_id=USER)
    _record_event(db_session, event_type="task_created", category="task", summary="Theirs", _user_id="other-user")

    resp = client.get(f"/internal/data/activity?user_id={USER}")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["summary"] == "Mine"


@pytest.mark.integration
def test_list_recent_activity_via_real_tool_layer(patched_sessionlocal, db_session, seed_garden_profile):
    """Drive through the actual chat-tool layer (not direct ORM/domain calls)
    to prove the structured serializer round-trips data the tool itself
    wrote, the same way a real triage/care/incident flow would."""
    from agent.tools.operations.incidents import report_incident

    project = make_project(db_session, seed_garden_profile)
    token = current_user_id.set(USER)
    try:
        report_incident.invoke({
            "incident_type": "pest", "summary": "Aphids", "project_id": project.id,
        })
    finally:
        current_user_id.reset(token)

    resp = client.get(f"/internal/data/activity?user_id={USER}")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "incident_reported"
