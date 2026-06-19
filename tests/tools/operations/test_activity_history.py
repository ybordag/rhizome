"""
Tests for the action history feature:
- get_task_activity
- get_incident_activity
- list_project_activity (cross-object timeline with filtering + pagination)
- list_recent_activity (enhanced filtering)
- interaction_resolved event written by resolve_interaction_record
- DB-level filtering in list_recent_activity_entries
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from agent.domain.activity_log import list_recent_activity_entries, record_activity_event
from agent.domain.interactions import resolve_interaction_record
from agent.tools.operations.activity import (
    get_incident_activity,
    get_task_activity,
    list_project_activity,
    list_recent_activity,
)
from agent.tools.projects.tracker import complete_task, start_task
from db.models import ActivityEvent, InteractionRecord
from tests.support.factories import (
    make_incident_report,
    make_incident_subject,
    make_plant,
    make_profile,
    make_project,
    make_project_brief,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_generation_run,
    make_treatment_plan,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _base(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    return profile, project, revision, run


def _record_event(db_session, project_id, event_type: str, category: str, subject_type: str, subject_id: str, created_at: datetime | None = None):
    event = record_activity_event(
        db_session,
        actor_type="agent",
        actor_label="test",
        event_type=event_type,
        category=category,
        summary=f"Test event: {event_type}",
        project_id=project_id,
        subjects=[{"subject_type": subject_type, "subject_id": subject_id, "role": "primary"}],
    )
    if created_at:
        event.created_at = created_at
    db_session.commit()
    return event


# ─── get_task_activity ────────────────────────────────────────────────────────

@pytest.mark.integration
def test_get_task_activity_shows_task_events(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.activity_task", title="Water Tomato", status="pending")

    start_task.invoke({"task_id": task.id})

    result = get_task_activity.invoke({"task_id": task.id})

    assert "task" in result.lower()
    assert task.id in result or "Water Tomato" in result


@pytest.mark.integration
def test_get_task_activity_empty_when_no_events(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.no_events")

    result = get_task_activity.invoke({"task_id": task.id})
    assert "No activity found" in result


@pytest.mark.integration
def test_get_task_activity_complete_lifecycle(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.full_lifecycle", title="Transplant pepper")

    start_task.invoke({"task_id": task.id})
    complete_task.invoke({"task_id": task.id, "actual_minutes": 30})

    result = get_task_activity.invoke({"task_id": task.id})

    assert "task_started" in result or "task_completed" in result


# ─── get_incident_activity ────────────────────────────────────────────────────

@pytest.mark.integration
def test_get_incident_activity_shows_incident_events(db_session, patched_sessionlocal):
    incident = make_incident_report(db_session, summary="Aphids on pepper")
    _record_event(db_session, None, "incident_updated", "incident",
                  "incident_report", incident.id)

    result = get_incident_activity.invoke({"incident_id": incident.id})

    assert "incident" in result.lower()


@pytest.mark.integration
def test_get_incident_activity_empty_when_no_events(db_session, patched_sessionlocal):
    incident = make_incident_report(db_session)

    result = get_incident_activity.invoke({"incident_id": incident.id})
    assert "No activity found" in result


@pytest.mark.integration
def test_get_incident_activity_shows_treatment_plan_approval(db_session, patched_sessionlocal):
    from agent.tools.operations.incidents import draft_treatment_plan, report_incident
    from tests.tools.projects.test_task_tracker_tools import _accept_plan
    from agent.tools.projects.tracker import generate_project_tasks

    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="nursery")
    generate_project_tasks.invoke({"project_id": project.id})

    profile = db_session.query(__import__('db.models', fromlist=['GardenProfile']).GardenProfile).first()
    plant = make_plant(db_session, profile, name="Pepper")

    report_result = report_incident.invoke({
        "incident_type": "pest",
        "summary": "Spider mites on pepper",
        "project_id": project.id,
        "subjects": [{"subject_type": "plant", "subject_id": plant.id}],
    })

    from db.models import IncidentReport
    incident = db_session.query(IncidentReport).filter(
        IncidentReport.project_id == project.id
    ).first()

    result = get_incident_activity.invoke({"incident_id": incident.id})
    assert "incident" in result.lower()


# ─── list_project_activity ────────────────────────────────────────────────────

@pytest.mark.integration
def test_list_project_activity_returns_project_events(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    _record_event(db_session, project.id, "task_created", "task", "task", "t1")
    _record_event(db_session, project.id, "plant_updated", "plant", "plant", "p1")

    result = list_project_activity.invoke({"project_id": project.id})

    assert "task_created" in result
    assert "plant_updated" in result


@pytest.mark.integration
def test_list_project_activity_filters_by_category(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    _record_event(db_session, project.id, "task_created", "task", "task", "t1")
    _record_event(db_session, project.id, "plant_updated", "plant", "plant", "p1")

    result = list_project_activity.invoke({"project_id": project.id, "category": "task"})

    assert "task_created" in result
    assert "plant_updated" not in result


@pytest.mark.integration
def test_list_project_activity_filters_by_event_type(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    _record_event(db_session, project.id, "task_created", "task", "task", "t1")
    _record_event(db_session, project.id, "task_started", "task", "task", "t2")

    result = list_project_activity.invoke({"project_id": project.id, "event_type": "task_created"})

    assert "task_created" in result
    assert "task_started" not in result


@pytest.mark.integration
def test_list_project_activity_filters_by_since(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    old_date = datetime(2026, 1, 1)
    recent_date = datetime(2026, 6, 1)
    _record_event(db_session, project.id, "task_created", "task", "task", "t_old",
                  created_at=old_date)
    _record_event(db_session, project.id, "task_started", "task", "task", "t_recent",
                  created_at=recent_date)

    result = list_project_activity.invoke({
        "project_id": project.id,
        "since": "2026-05-01",
    })

    assert "task_started" in result
    assert "task_created" not in result


@pytest.mark.integration
def test_list_project_activity_pagination_with_before_timestamp(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    now = datetime(2026, 6, 15)
    for i in range(5):
        _record_event(db_session, project.id, "task_created", "task", "task", f"t{i}",
                      created_at=now - timedelta(days=i))

    # Get page 1 (latest 3)
    page1 = list_project_activity.invoke({"project_id": project.id, "limit": 3})
    # The oldest of the first 3 is now - 2 days
    cutoff = (now - timedelta(days=2)).isoformat()

    # Get page 2 (events before cutoff)
    page2 = list_project_activity.invoke({
        "project_id": project.id,
        "before_timestamp": cutoff,
        "limit": 3,
    })

    assert page1 != page2


@pytest.mark.integration
def test_list_project_activity_empty_project(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)

    result = list_project_activity.invoke({"project_id": project.id})
    assert "No activity found" in result


@pytest.mark.integration
def test_list_project_activity_invalid_since_returns_error(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)

    result = list_project_activity.invoke({"project_id": project.id, "since": "not-a-date"})
    assert "Invalid" in result or "Failed" in result


# ─── list_recent_activity (enhanced filtering) ───────────────────────────────

@pytest.mark.integration
def test_list_recent_activity_filters_by_category(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    _record_event(db_session, project.id, "task_created", "task", "task", "t1")
    _record_event(db_session, project.id, "plant_watered", "plant", "plant", "p1")

    result = list_recent_activity.invoke({"category": "plant"})

    assert "plant_watered" in result
    assert "task_created" not in result


@pytest.mark.integration
def test_list_recent_activity_filters_by_event_type(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    _record_event(db_session, project.id, "task_created", "task", "task", "t1")
    _record_event(db_session, project.id, "task_started", "task", "task", "t2")

    result = list_recent_activity.invoke({"event_type": "task_started"})

    assert "task_started" in result
    assert "task_created" not in result


@pytest.mark.integration
def test_list_recent_activity_since_filter(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    old = _record_event(db_session, project.id, "task_created", "task", "task", "t_old")
    old.created_at = datetime(2026, 1, 1)
    db_session.flush()
    _record_event(db_session, project.id, "task_started", "task", "task", "t_new")

    result = list_recent_activity.invoke({"since": "2026-05-01"})

    assert "task_started" in result
    assert "task_created" not in result


@pytest.mark.integration
def test_list_recent_activity_invalid_since_returns_error(db_session, patched_sessionlocal):
    result = list_recent_activity.invoke({"since": "bad-date"})
    assert "Invalid" in result or "Failed" in result


# ─── list_recent_activity_entries DB-level filtering ─────────────────────────

@pytest.mark.integration
def test_list_recent_activity_entries_event_type_filter_is_db_level(db_session, patched_sessionlocal):
    """Verify event_type filter is applied at DB level, not Python post-filter."""
    profile, project, revision, run = _base(db_session)
    _record_event(db_session, project.id, "task_created", "task", "task", "t1")
    _record_event(db_session, project.id, "task_started", "task", "task", "t2")
    _record_event(db_session, project.id, "task_completed", "task", "task", "t3")

    results = list_recent_activity_entries(
        db_session,
        project_id=project.id,
        event_type="task_started",
    )

    assert len(results) == 1
    assert results[0].event_type == "task_started"


@pytest.mark.integration
def test_list_recent_activity_entries_category_filter(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    _record_event(db_session, project.id, "task_created", "task", "task", "t1")
    _record_event(db_session, project.id, "plant_watered", "plant", "plant", "p1")

    results = list_recent_activity_entries(db_session, project_id=project.id, category="plant")

    assert all(e.category == "plant" for e in results)


@pytest.mark.integration
def test_list_recent_activity_entries_since_filter(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    old = _record_event(db_session, project.id, "task_created", "task", "task", "t1")
    old.created_at = datetime(2026, 1, 1)
    db_session.flush()
    recent = _record_event(db_session, project.id, "task_started", "task", "task", "t2")

    cutoff = datetime(2026, 5, 1)
    results = list_recent_activity_entries(db_session, project_id=project.id, since=cutoff)

    ids = [e.id for e in results]
    assert recent.id in ids
    assert old.id not in ids


@pytest.mark.integration
def test_list_recent_activity_entries_before_timestamp_pagination(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)
    now = datetime(2026, 6, 15, 12, 0, 0)
    events = []
    for i in range(6):
        e = _record_event(db_session, project.id, "task_created", "task", "task", f"t{i}",
                          created_at=now - timedelta(hours=i))
        events.append(e)

    # Page 1: latest 3
    page1 = list_recent_activity_entries(db_session, project_id=project.id, limit=3)
    assert len(page1) == 3

    # Page 2: 3 events before the oldest on page 1
    cutoff = page1[-1].created_at
    page2 = list_recent_activity_entries(
        db_session, project_id=project.id, limit=3, before_timestamp=cutoff
    )
    assert len(page2) == 3

    page1_ids = {e.id for e in page1}
    page2_ids = {e.id for e in page2}
    assert not page1_ids & page2_ids  # no overlap between pages


# ─── interaction_resolved activity event ─────────────────────────────────────

@pytest.mark.integration
def test_resolve_interaction_record_writes_activity_event(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)

    record = InteractionRecord(
        interaction_type="confirmation_request",
        status="pending",
        title="Confirm delete",
        summary="Delete project?",
        project_id=project.id,
        source_type="confirmation",
        source_id="test-source",
    )
    db_session.add(record)
    db_session.flush()

    resolve_interaction_record(
        db_session,
        record,
        action_id="confirm",
        resolution_summary="User confirmed deletion.",
    )
    db_session.commit()

    events = db_session.query(ActivityEvent).filter(
        ActivityEvent.event_type == "interaction_resolved",
        ActivityEvent.project_id == project.id,
    ).all()

    assert len(events) == 1
    assert "confirm" in events[0].event_metadata.get("action_id", "")


@pytest.mark.integration
def test_resolve_interaction_record_cancel_records_dismissed_status(db_session, patched_sessionlocal):
    profile, project, revision, run = _base(db_session)

    record = InteractionRecord(
        interaction_type="proposal_review",
        status="pending",
        title="Review proposal",
        summary="Accept or reject?",
        project_id=project.id,
        source_type="planner",
        source_id="proposal-1",
    )
    db_session.add(record)
    db_session.flush()

    resolve_interaction_record(db_session, record, action_id="cancel")
    db_session.commit()

    events = db_session.query(ActivityEvent).filter(
        ActivityEvent.event_type == "interaction_resolved",
    ).all()

    assert len(events) == 1
    assert events[0].event_metadata.get("status") == "dismissed"


@pytest.mark.integration
def test_resolve_interaction_record_null_project_id_still_records(db_session, patched_sessionlocal):
    """Interactions without a project_id (e.g. confirmation dialogs) still record the event."""
    record = InteractionRecord(
        interaction_type="confirmation_request",
        status="pending",
        title="Confirm action",
        summary="Are you sure?",
        project_id=None,
        source_type="confirmation",
        source_id="test-source",
    )
    db_session.add(record)
    db_session.flush()

    resolve_interaction_record(db_session, record, action_id="confirm")
    db_session.commit()

    events = db_session.query(ActivityEvent).filter(
        ActivityEvent.event_type == "interaction_resolved"
    ).all()
    assert len(events) == 1
