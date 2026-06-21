"""
Tests for #134: GET /internal/data/activity (the global activity feed) now
returns ActivityEventView[] instead of {"result": "<prose>"}. Every
per-entity activity endpoint already returned this shape as of #140 — this
was the one global endpoint left over, per docs/architecture/api-reference.md's
"Still returns {"result": "<prose>"}" note.
"""
from datetime import datetime, timedelta

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
    created_at = overrides.pop("created_at", None)
    user_id = overrides.pop("_user_id", USER)
    data.update(overrides)
    token = current_user_id.set(user_id)
    try:
        event = record_activity_event(db_session, **data)
        if created_at is not None:
            # record_activity_event always stamps "now" — set an explicit
            # created_at afterward so ordering/date-filter tests aren't at
            # the mercy of how fast the test runs or whether two events land
            # in the same microsecond.
            event.created_at = created_at
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


# ---------------------------------------------------------------------------
# Critical-review follow-ups: the first pass only tested that bad date
# strings 400, never that valid since/before_timestamp actually filter, that
# results come back newest-first, that the documented before_timestamp
# pagination cursor works, or that the default limit is enforced. All of
# these use explicit created_at overrides — record_activity_event always
# stamps "now", which makes ordering/date-range assertions nondeterministic
# without it.
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_list_recent_activity_since_excludes_older_events(patched_sessionlocal, db_session, seed_garden_profile):
    cutoff = datetime(2026, 6, 15)
    _record_event(db_session, summary="Old", created_at=cutoff - timedelta(days=1))
    _record_event(db_session, summary="New", created_at=cutoff + timedelta(days=1))

    resp = client.get(f"/internal/data/activity?user_id={USER}&since={cutoff.isoformat()}")
    assert resp.status_code == 200
    summaries = [e["summary"] for e in resp.json()]
    assert summaries == ["New"]


@pytest.mark.integration
def test_list_recent_activity_before_timestamp_excludes_newer_events(patched_sessionlocal, db_session, seed_garden_profile):
    cutoff = datetime(2026, 6, 15)
    _record_event(db_session, summary="Old", created_at=cutoff - timedelta(days=1))
    _record_event(db_session, summary="New", created_at=cutoff + timedelta(days=1))

    resp = client.get(f"/internal/data/activity?user_id={USER}&before_timestamp={cutoff.isoformat()}")
    assert resp.status_code == 200
    summaries = [e["summary"] for e in resp.json()]
    assert summaries == ["Old"]


@pytest.mark.integration
def test_list_recent_activity_since_and_before_timestamp_together(patched_sessionlocal, db_session, seed_garden_profile):
    base = datetime(2026, 6, 15)
    _record_event(db_session, summary="Too old", created_at=base - timedelta(days=10))
    _record_event(db_session, summary="In range", created_at=base)
    _record_event(db_session, summary="Too new", created_at=base + timedelta(days=10))

    resp = client.get(
        f"/internal/data/activity?user_id={USER}"
        f"&since={(base - timedelta(days=1)).isoformat()}"
        f"&before_timestamp={(base + timedelta(days=1)).isoformat()}"
    )
    assert resp.status_code == 200
    summaries = [e["summary"] for e in resp.json()]
    assert summaries == ["In range"]


@pytest.mark.integration
def test_list_recent_activity_returns_newest_first(patched_sessionlocal, db_session, seed_garden_profile):
    base = datetime(2026, 6, 15)
    _record_event(db_session, summary="Oldest", created_at=base)
    _record_event(db_session, summary="Middle", created_at=base + timedelta(hours=1))
    _record_event(db_session, summary="Newest", created_at=base + timedelta(hours=2))

    resp = client.get(f"/internal/data/activity?user_id={USER}")
    assert resp.status_code == 200
    summaries = [e["summary"] for e in resp.json()]
    assert summaries == ["Newest", "Middle", "Oldest"]


@pytest.mark.integration
def test_list_recent_activity_before_timestamp_cursor_paginates_without_overlap(patched_sessionlocal, db_session, seed_garden_profile):
    """Exercises the exact pagination pattern the docstring on the
    underlying tool recommends: take the oldest event's created_at from a
    page and pass it as before_timestamp to fetch the next page."""
    base = datetime(2026, 6, 15)
    for i in range(5):
        _record_event(db_session, summary=f"Event {i}", created_at=base + timedelta(hours=i))

    page1 = client.get(f"/internal/data/activity?user_id={USER}&limit=2").json()
    assert [e["summary"] for e in page1] == ["Event 4", "Event 3"]

    cursor = page1[-1]["created_at"]
    page2 = client.get(f"/internal/data/activity?user_id={USER}&before_timestamp={cursor}&limit=2").json()
    assert [e["summary"] for e in page2] == ["Event 2", "Event 1"]

    page1_ids = {e["id"] for e in page1}
    page2_ids = {e["id"] for e in page2}
    assert not page1_ids & page2_ids, "pages overlapped — cursor pagination would skip or repeat events"


@pytest.mark.integration
def test_list_recent_activity_default_limit_is_20(patched_sessionlocal, db_session, seed_garden_profile):
    base = datetime(2026, 6, 15)
    for i in range(25):
        _record_event(db_session, summary=f"Event {i}", created_at=base + timedelta(minutes=i))

    resp = client.get(f"/internal/data/activity?user_id={USER}")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 20
    # Newest-first: the 20 most recent of 25 means events 5..24 survive.
    assert events[0]["summary"] == "Event 24"
    assert events[-1]["summary"] == "Event 5"


@pytest.mark.integration
def test_list_recent_activity_combines_filters_with_and(patched_sessionlocal, db_session, seed_garden_profile):
    project_a = make_project(db_session, seed_garden_profile, name="Project A")
    project_b = make_project(db_session, seed_garden_profile, name="Project B")
    _record_event(db_session, summary="Match", category="task", event_type="task_created", project_id=project_a.id)
    _record_event(db_session, summary="Wrong category", category="incident", event_type="task_created", project_id=project_a.id)
    _record_event(db_session, summary="Wrong project", category="task", event_type="task_created", project_id=project_b.id)

    resp = client.get(
        f"/internal/data/activity?user_id={USER}&category=task&project_id={project_a.id}"
    )
    assert resp.status_code == 200
    summaries = [e["summary"] for e in resp.json()]
    assert summaries == ["Match"]


@pytest.mark.integration
def test_list_recent_activity_serializes_multiple_subjects(patched_sessionlocal, db_session, seed_garden_profile):
    event = _record_event(
        db_session,
        summary="Multi-subject event",
        subjects=[
            {"subject_type": "bed", "subject_id": "bed-1", "role": "primary"},
            {"subject_type": "plant", "subject_id": "plant-1", "role": "affected"},
        ],
    )

    resp = client.get(f"/internal/data/activity?user_id={USER}")
    assert resp.status_code == 200
    subjects = resp.json()[0]["subjects"]
    assert len(subjects) == 2
    assert {"bed", "plant"} == {s["subject_type"] for s in subjects}


@pytest.mark.integration
def test_list_recent_activity_serializes_notes_when_present(patched_sessionlocal, db_session, seed_garden_profile):
    _record_event(db_session, summary="Has notes", notes="Some extra context")

    resp = client.get(f"/internal/data/activity?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json()[0]["notes"] == "Some extra context"


@pytest.mark.integration
def test_list_recent_activity_since_is_inclusive_of_exact_boundary(patched_sessionlocal, db_session, seed_garden_profile):
    """An event created exactly at the since timestamp must be included
    (filter is created_at >= since, not strictly >) — distinct from the
    excludes_older_events test above, which only checks a value safely past
    the boundary and wouldn't catch an off-by-one on the comparison operator."""
    cutoff = datetime(2026, 6, 15, 12, 0, 0)
    _record_event(db_session, summary="Exactly at cutoff", created_at=cutoff)

    resp = client.get(f"/internal/data/activity?user_id={USER}&since={cutoff.isoformat()}")
    assert resp.status_code == 200
    assert [e["summary"] for e in resp.json()] == ["Exactly at cutoff"]


@pytest.mark.integration
def test_list_recent_activity_before_timestamp_is_exclusive_of_exact_boundary(patched_sessionlocal, db_session, seed_garden_profile):
    """An event created exactly at the before_timestamp cutoff must be
    excluded (filter is created_at < before_timestamp, strictly) — this is
    what makes the cursor-pagination pattern safe: passing the last page's
    oldest created_at as the next page's before_timestamp must not
    re-include that same event."""
    cutoff = datetime(2026, 6, 15, 12, 0, 0)
    _record_event(db_session, summary="Exactly at cutoff", created_at=cutoff)

    resp = client.get(f"/internal/data/activity?user_id={USER}&before_timestamp={cutoff.isoformat()}")
    assert resp.status_code == 200
    assert resp.json() == []
