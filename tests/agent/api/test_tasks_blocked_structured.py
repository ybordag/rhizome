"""Regression coverage for structured GET /tasks/blocked."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from tests.support.factories import (
    make_profile,
    make_project,
    make_project_brief,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_dependency,
    make_task_generation_run,
)

client = TestClient(app)
USER = "1"


def _base(db_session, profile=None, user_id=USER, project_name="Blocked tasks project"):
    profile = profile or make_profile(db_session, user_id=user_id)
    project = make_project(db_session, profile, user_id=user_id, name=project_name)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    return project, revision, run


def _dependent_pair(db_session, project, revision, run, *, title="Blocked task", blocker_status="pending"):
    blocker = make_task(
        db_session,
        project,
        revision,
        run,
        title=f"Prerequisite for {title}",
        status=blocker_status,
        generator_key=f"{title}.blocker",
    )
    blocked = make_task(
        db_session,
        project,
        revision,
        run,
        title=title,
        status="pending",
        parent_task_id=None,
        deadline=datetime(2026, 4, 20),
        scheduled_date=datetime(2026, 4, 18),
        generator_key=f"{title}.blocked",
    )
    make_task_dependency(db_session, blocker, blocked)
    return blocker, blocked


@pytest.mark.integration
def test_list_blocked_tasks_empty_returns_structured_array(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get(f"/internal/data/tasks/blocked?user_id={USER}")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_list_blocked_tasks_returns_task_summary_views(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    _, blocked = _dependent_pair(db_session, project, revision, run, title="Transplant tomato")

    resp = client.get(f"/internal/data/tasks/blocked?user_id={USER}")

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert "result" not in body[0]
    assert body[0]["id"] == blocked.id
    assert body[0]["project_id"] == project.id
    assert body[0]["title"] == "Transplant tomato"
    assert body[0]["blocked"] is True
    assert body[0]["due_date"] == "2026-04-20T00:00:00"
    assert body[0]["urgency"] == "blocker"
    assert "created_at" in body[0]


@pytest.mark.integration
def test_list_blocked_tasks_includes_event_anchor_blockers(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    anchored = make_task(
        db_session,
        project,
        revision,
        run,
        title="Wait for germination",
        status="blocked",
        event_anchor_type="after_event",
        event_anchor_subject_type="plant",
        event_anchor_subject_id="seedling-1",
        scheduled_date=None,
        deadline=None,
        window_end=None,
    )

    resp = client.get(f"/internal/data/tasks/blocked?user_id={USER}")

    assert resp.status_code == 200
    body = resp.json()
    assert [task["id"] for task in body] == [anchored.id]
    assert body[0]["blocked"] is True
    assert body[0]["due_date"] is None


@pytest.mark.integration
def test_list_blocked_tasks_excludes_unblocked_dependencies(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    _dependent_pair(
        db_session,
        project,
        revision,
        run,
        title="Already unblocked task",
        blocker_status="done",
    )

    resp = client.get(f"/internal/data/tasks/blocked?user_id={USER}")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_list_blocked_tasks_includes_deferred_blocked_tasks(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    _, blocked = _dependent_pair(db_session, project, revision, run, title="Deferred blocked task")
    blocked.status = "deferred"
    blocked.deferred_until = datetime.now() + timedelta(days=14)
    db_session.commit()

    resp = client.get(f"/internal/data/tasks/blocked?user_id={USER}")

    assert resp.status_code == 200
    body = resp.json()
    assert [task["id"] for task in body] == [blocked.id]
    assert body[0]["status"] == "deferred"
    assert body[0]["blocked"] is True


@pytest.mark.integration
@pytest.mark.parametrize("terminal_status", ["done", "skipped", "superseded"])
def test_list_blocked_tasks_excludes_terminal_statuses(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
    terminal_status,
):
    project, revision, run = _base(db_session, seed_garden_profile)
    _, blocked = _dependent_pair(db_session, project, revision, run, title=f"{terminal_status} blocked task")
    blocked.status = terminal_status
    db_session.commit()

    resp = client.get(f"/internal/data/tasks/blocked?user_id={USER}")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_list_blocked_tasks_excludes_section_tasks(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    _, section = _dependent_pair(db_session, project, revision, run, title="Section milestone")
    section.generator_key = "section.setup"
    db_session.commit()

    resp = client.get(f"/internal/data/tasks/blocked?user_id={USER}")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_list_blocked_tasks_sorted_by_due_fields(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    _, third = _dependent_pair(db_session, project, revision, run, title="Third")
    third.deadline = datetime(2026, 5, 3)
    third.window_end = datetime(2026, 5, 4)
    third.scheduled_date = datetime(2026, 5, 5)
    _, first = _dependent_pair(db_session, project, revision, run, title="First")
    first.deadline = datetime(2026, 5, 1)
    first.window_end = datetime(2026, 5, 2)
    first.scheduled_date = datetime(2026, 5, 3)
    _, second = _dependent_pair(db_session, project, revision, run, title="Second")
    second.deadline = datetime(2026, 5, 2)
    second.window_end = datetime(2026, 5, 3)
    second.scheduled_date = datetime(2026, 5, 4)
    db_session.commit()

    resp = client.get(f"/internal/data/tasks/blocked?user_id={USER}")

    assert resp.status_code == 200
    assert [task["id"] for task in resp.json()] == [first.id, second.id, third.id]


@pytest.mark.integration
def test_list_blocked_tasks_filters_by_project_id(patched_sessionlocal, db_session, seed_garden_profile):
    project_a, revision_a, run_a = _base(db_session, seed_garden_profile, project_name="Project A")
    project_b, revision_b, run_b = _base(db_session, seed_garden_profile, project_name="Project B")
    _, blocked_a = _dependent_pair(db_session, project_a, revision_a, run_a, title="Project A blocked")
    _dependent_pair(db_session, project_b, revision_b, run_b, title="Project B blocked")

    resp = client.get(f"/internal/data/tasks/blocked?user_id={USER}&project_id={project_a.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert [task["id"] for task in body] == [blocked_a.id]
    assert body[0]["project_id"] == project_a.id


@pytest.mark.integration
def test_list_blocked_tasks_other_user_project_filter_returns_empty(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    other_profile = make_profile(db_session, user_id="2")
    other_project, other_revision, other_run = _base(
        db_session,
        other_profile,
        user_id="2",
        project_name="Other user project",
    )
    _dependent_pair(db_session, other_project, other_revision, other_run, title="Their blocked task")

    resp = client.get(f"/internal/data/tasks/blocked?user_id={USER}&project_id={other_project.id}")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_list_blocked_tasks_scoped_to_current_user(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    _, my_blocked = _dependent_pair(db_session, project, revision, run, title="My blocked task")
    other_profile = make_profile(db_session, user_id="2")
    other_project, other_revision, other_run = _base(
        db_session,
        other_profile,
        user_id="2",
        project_name="Other user project",
    )
    _dependent_pair(db_session, other_project, other_revision, other_run, title="Their blocked task")

    resp = client.get(f"/internal/data/tasks/blocked?user_id={USER}")

    assert resp.status_code == 200
    assert [task["id"] for task in resp.json()] == [my_blocked.id]
