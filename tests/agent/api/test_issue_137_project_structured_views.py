"""
Tests for #137: project lifecycle and planning endpoints return structured
JSON view models instead of {"result": "<prose>"}. The underlying LangChain
tools remain string-returning for agent use.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from db.database import current_user_id
from db.models import ProjectBrief, ProjectExecutionSpec, ProjectRevision
from tests.support.factories import (
    make_project,
    make_project_brief,
    make_project_execution_spec,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_generation_run,
)

client = TestClient(app)
USER = "1"
OTHER_USER = "2"


def _uid():
    return str(uuid.uuid4())


def _planning_base(db_session, profile):
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    return project, brief, proposal


def _execution_base(db_session, profile):
    project, brief, proposal = _planning_base(db_session, profile)
    revision = make_project_revision(db_session, project, proposal)
    make_project_execution_spec(db_session, project, revision)
    run = make_task_generation_run(db_session, project, revision)
    return project, brief, proposal, revision, run


@pytest.mark.integration
def test_project_progress_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, _proposal, revision, run = _execution_base(db_session, seed_garden_profile)
    parent = make_task(db_session, project, revision, run, title="Milestone", type="section")
    make_task(db_session, project, revision, run, title="Done task", status="done", parent_task_id=parent.id)
    make_task(db_session, project, revision, run, title="Pending task", status="pending", parent_task_id=parent.id)

    resp = client.get(f"/internal/data/projects/{project.id}/progress?user_id={USER}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == project.id
    assert body["project_name"] == project.name
    assert body["tasks_total"] == 2
    assert body["tasks_done"] == 1
    assert body["percent_complete"] == 50
    assert "result" not in body


@pytest.mark.integration
def test_project_progress_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)

    resp = client.get(f"/internal/data/projects/{project.id}/progress?user_id={OTHER_USER}")

    assert resp.status_code == 404


@pytest.mark.integration
def test_project_progress_includes_timeline_budget_and_critical_tasks(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, proposal = _planning_base(db_session, seed_garden_profile)
    revision = make_project_revision(
        db_session,
        project,
        proposal,
        approved_plan={"cost_estimate": {"total_estimated_cost": 60.0}},
    )
    now = datetime.now().replace(microsecond=0)
    make_project_execution_spec(
        db_session,
        project,
        revision,
        timing_windows={
            "expected_first_action_date": (now - timedelta(days=2)).isoformat(),
            "expected_completion_date": (now + timedelta(days=8)).isoformat(),
        },
    )
    run = make_task_generation_run(db_session, project, revision)
    parent = make_task(db_session, project, revision, run, title="Milestone", type="section")
    critical = make_task(
        db_session,
        project,
        revision,
        run,
        title="Water before heat spike",
        status="pending",
        parent_task_id=parent.id,
        deadline=now,
    )

    resp = client.get(f"/internal/data/projects/{project.id}/progress?user_id={USER}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["schedule_percent_elapsed"] is not None
    assert body["days_remaining"] is not None
    assert body["budget_cap"] == 120.0
    assert body["estimated_cost"] == 60.0
    assert body["budget_percent_used"] == 50
    assert body["critical_tasks"] == [{"id": critical.id, "title": "Water before heat spike", "status": "pending"}]


@pytest.mark.integration
def test_create_project_returns_project_detail_view(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/projects?user_id={USER}", json={
        "name": "Cut flower bed",
        "goal": "Grow annual flowers for bouquets.",
        "tray_slots": 6,
        "budget_ceiling": 90.0,
        "notes": "Focus on zinnias.",
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Cut flower bed"
    assert body["goal"] == "Grow annual flowers for bouquets."
    assert body["status"] == "planning"
    assert body["tray_slots"] == 6
    assert "id" in body
    assert "result" not in body


@pytest.mark.integration
def test_create_project_validation_error_returns_400_without_result_wrapper(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/projects?user_id={USER}", json={
        "name": "Bad project",
        "goal": "Invalid numbers.",
        "tray_slots": -1,
        "budget_ceiling": 90.0,
    })

    assert resp.status_code == 400
    assert "result" not in resp.json()


@pytest.mark.integration
def test_update_project_returns_project_detail_view(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)

    resp = client.patch(f"/internal/data/projects/{project.id}?user_id={USER}", json={
        "status": "active",
        "budget_ceiling": 150.0,
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == project.id
    assert body["status"] == "active"
    assert body["budget_ceiling"] == 150.0
    assert "result" not in body


@pytest.mark.integration
def test_update_project_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)

    resp = client.patch(f"/internal/data/projects/{project.id}?user_id={OTHER_USER}", json={"status": "active"})

    assert resp.status_code == 404
    assert "result" not in resp.json()


@pytest.mark.integration
def test_update_project_invalid_status_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)

    resp = client.patch(f"/internal/data/projects/{project.id}?user_id={USER}", json={"status": "donezo"})

    assert resp.status_code == 400


@pytest.mark.integration
def test_delete_project_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)

    resp = client.delete(f"/internal/data/projects/{project.id}?user_id={OTHER_USER}")

    assert resp.status_code == 404
    assert "result" not in resp.json()


@pytest.mark.integration
def test_delete_project_returns_pre_delete_project_detail_view(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile, name="Duplicate project")
    project_id = project.id
    project_cls = type(project)

    resp = client.delete(f"/internal/data/projects/{project_id}?user_id={USER}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == project_id
    assert body["name"] == "Duplicate project"
    assert "result" not in body

    db_session.expire_all()
    assert db_session.get(project_cls, project_id) is None


@pytest.mark.integration
def test_delete_project_with_active_tasks_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, _proposal, revision, run = _execution_base(db_session, seed_garden_profile)
    make_task(db_session, project, revision, run, status="pending")

    resp = client.delete(f"/internal/data/projects/{project.id}?user_id={USER}")

    assert resp.status_code == 400


@pytest.mark.integration
def test_get_project_brief_creates_and_returns_structured_view_when_missing(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    assert db_session.query(ProjectBrief).filter(ProjectBrief.project_id == project.id).count() == 0

    resp = client.get(f"/internal/data/projects/{project.id}/brief?user_id={USER}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == project.id
    assert body["goal"] == project.goal
    assert "result" not in body
    assert db_session.query(ProjectBrief).filter(ProjectBrief.project_id == project.id).count() == 1


@pytest.mark.integration
def test_get_project_brief_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    project, brief, _proposal = _planning_base(db_session, seed_garden_profile)

    resp = client.get(f"/internal/data/projects/{project.id}/brief?user_id={USER}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == brief.id
    assert body["project_id"] == project.id
    assert body["goal"] == project.goal
    assert body["priority_preferences"] == ["cost", "yield"]
    assert "result" not in body


@pytest.mark.integration
def test_update_project_brief_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    project, brief, _proposal = _planning_base(db_session, seed_garden_profile)

    resp = client.patch(f"/internal/data/projects/{project.id}/brief?user_id={USER}", json={
        "desired_outcome": "Harvest by late August.",
        "priority_preferences": ["yield", "low_labor"],
        "status": "ready_for_proposal",
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == brief.id
    assert body["desired_outcome"] == "Harvest by late August."
    assert body["priority_preferences"] == ["yield", "low_labor"]
    assert body["status"] == "ready_for_proposal"
    assert "result" not in body


@pytest.mark.integration
def test_update_project_brief_invalid_status_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, _proposal = _planning_base(db_session, seed_garden_profile)

    resp = client.patch(f"/internal/data/projects/{project.id}/brief?user_id={USER}", json={"status": "ready-ish"})

    assert resp.status_code == 400
    assert "result" not in resp.json()


@pytest.mark.integration
def test_update_project_brief_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, _proposal = _planning_base(db_session, seed_garden_profile)

    resp = client.patch(
        f"/internal/data/projects/{project.id}/brief?user_id={OTHER_USER}",
        json={"desired_outcome": "Should not update"},
    )

    assert resp.status_code == 404
    assert "result" not in resp.json()


@pytest.mark.integration
def test_project_brief_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)

    resp = client.get(f"/internal/data/projects/{project.id}/brief?user_id={OTHER_USER}")

    assert resp.status_code == 404


@pytest.mark.integration
def test_list_project_proposals_empty_returns_empty_array(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)

    resp = client.get(f"/internal/data/projects/{project.id}/proposals?user_id={USER}")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
def test_list_project_proposals_returns_structured_summaries(patched_sessionlocal, db_session, seed_garden_profile):
    project, brief, proposal_one = _planning_base(db_session, seed_garden_profile)
    proposal_two = make_project_proposal(
        db_session, project, brief, version=2, title="Lower effort plan", summary="Buy transplants."
    )

    resp = client.get(f"/internal/data/projects/{project.id}/proposals?user_id={USER}")

    assert resp.status_code == 200
    body = resp.json()
    assert [p["id"] for p in body] == [proposal_two.id, proposal_one.id]
    assert body[0]["title"] == "Lower effort plan"
    assert body[0]["total_estimated_cost"] == 50.0
    assert "recommended_approach" not in body[0]


@pytest.mark.integration
def test_list_project_proposals_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, _proposal = _planning_base(db_session, seed_garden_profile)

    resp = client.get(f"/internal/data/projects/{project.id}/proposals?user_id={OTHER_USER}")

    assert resp.status_code == 404
    assert "result" not in resp.json()


@pytest.mark.integration
def test_get_project_proposal_returns_structured_detail(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, proposal = _planning_base(db_session, seed_garden_profile)

    resp = client.get(f"/internal/data/projects/{project.id}/proposals/{proposal.id}?user_id={USER}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == proposal.id
    assert body["recommended_approach"] == "Seed start tomatoes and direct sow basil."
    assert body["selected_plants"][0]["name"] == "Tomato"
    assert body["cost_estimate"]["total_estimated_cost"] == 50.0
    assert "result" not in body


@pytest.mark.integration
def test_get_project_proposal_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, proposal = _planning_base(db_session, seed_garden_profile)

    resp = client.get(f"/internal/data/projects/{project.id}/proposals/{proposal.id}?user_id={OTHER_USER}")

    assert resp.status_code == 404
    assert "result" not in resp.json()


@pytest.mark.integration
def test_get_project_proposal_wrong_project_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, proposal = _planning_base(db_session, seed_garden_profile)
    other_project = make_project(db_session, seed_garden_profile, name="Other project")

    resp = client.get(f"/internal/data/projects/{other_project.id}/proposals/{proposal.id}?user_id={USER}")

    assert resp.status_code == 404


@pytest.mark.integration
def test_accept_project_proposal_returns_updated_detail_view(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, proposal = _planning_base(db_session, seed_garden_profile)

    resp = client.post(f"/internal/data/projects/{project.id}/proposals/{proposal.id}/accept?user_id={USER}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == proposal.id
    assert body["status"] == "accepted"
    assert body["recommended_approach"] == proposal.recommended_approach
    assert "result" not in body
    db_session.expire_all()
    assert db_session.get(type(proposal), proposal.id).status == "accepted"
    assert db_session.query(ProjectRevision).filter(ProjectRevision.project_id == project.id).count() == 1
    assert db_session.query(ProjectExecutionSpec).filter(ProjectExecutionSpec.project_id == project.id).count() == 1


@pytest.mark.integration
def test_accept_project_proposal_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, proposal = _planning_base(db_session, seed_garden_profile)

    resp = client.post(f"/internal/data/projects/{project.id}/proposals/{proposal.id}/accept?user_id={OTHER_USER}")

    assert resp.status_code == 404
    assert "result" not in resp.json()


@pytest.mark.integration
def test_accept_project_proposal_unknown_proposal_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project, _brief, _proposal = _planning_base(db_session, seed_garden_profile)

    resp = client.post(f"/internal/data/projects/{project.id}/proposals/{_uid()}/accept?user_id={USER}")

    assert resp.status_code == 404
    assert "result" not in resp.json()


@pytest.mark.integration
def test_project_tools_still_return_strings(patched_sessionlocal, db_session, seed_garden_profile):
    from agent.tools.projects.planning import get_project_brief
    from agent.tools.projects.projects import get_project_progress

    project, _brief, _proposal = _planning_base(db_session, seed_garden_profile)
    token = current_user_id.set(USER)
    try:
        brief_result = get_project_brief.invoke({"project_id": project.id})
        progress_result = get_project_progress.invoke({"project_id": project.id})
    finally:
        current_user_id.reset(token)

    assert isinstance(brief_result, str)
    assert isinstance(progress_result, str)
