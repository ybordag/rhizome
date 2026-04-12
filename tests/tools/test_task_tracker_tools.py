from __future__ import annotations

from agent.tools.activity import get_project_activity
from agent.tools.planning import accept_project_proposal, save_project_proposal, update_project_brief
from agent.tools.tracker import (
    complete_task,
    defer_task,
    explain_task_blockers,
    generate_project_tasks,
    get_task,
    list_blocked_tasks,
    list_due_tasks,
    list_project_tasks,
    list_task_series,
    materialize_recurring_tasks,
    regenerate_project_tasks,
    skip_task,
    start_task,
    update_task,
    update_task_series,
)
from db.models import ActivityEvent, ProjectProposal, Task, TaskGenerationRun, TaskSeries
from tests.support.factories import make_project, make_profile


def _accept_plan(
    db_session,
    patched_sessionlocal,
    *,
    propagation_method: str = "seed",
    target_completion: str = "2026-07-01",
    budget_cap: float = 120.0,
):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "A reliable summer tomato crop.",
            "target_start": "2026-04-01",
            "target_completion": target_completion,
            "budget_cap": budget_cap,
        }
    )
    save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Execution plan",
            "summary": "Plan for tomatoes in containers.",
            "recommended_approach": "Use containers and follow a staged establishment plan.",
            "selected_locations": [
                {"location_type": "container", "location_id": "c1", "name": "Growbag 1", "estimated_setup_cost": 20}
            ],
            "selected_plants": [
                {"name": "Tomato", "quantity": 2, "propagation_method": propagation_method},
            ],
        }
    )
    proposal_id = (
        db_session.query(ProjectProposal.id)
        .filter(ProjectProposal.project_id == project.id)
        .order_by(ProjectProposal.version.desc())
        .first()[0]
    )
    accept_project_proposal.invoke({"project_id": project.id, "proposal_id": proposal_id})
    return project


def test_generate_project_tasks_creates_run_tasks_dependencies_and_series(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")

    result = generate_project_tasks.invoke({"project_id": project.id})
    listed = list_project_tasks.invoke({"project_id": project.id})

    milestone_titles = {task.title for task in db_session.query(Task).filter(Task.parent_task_id.is_not(None)).all()}
    series_titles = {series.title for series in db_session.query(TaskSeries).all()}

    assert "Generated project tasks" in result
    assert "Propagation:" in listed
    assert db_session.query(TaskGenerationRun).count() == 1
    assert "Sow Tomato" in milestone_titles
    assert "Pot up Tomato to red cups" in milestone_titles
    assert "Transplant Tomato to final location" in milestone_titles
    assert "Water Tomato" in series_titles
    assert "Inspect Tomato for pests" in series_titles


def test_starts_based_generation_omits_seed_start_milestones(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="start")

    generate_project_tasks.invoke({"project_id": project.id})

    titles = {task.title for task in db_session.query(Task).all()}

    assert "Acquire Tomato starts" in titles
    assert "Sow Tomato" not in titles
    assert "Pot up Tomato to red cups" not in titles


def test_regeneration_supersedes_future_tasks_and_preserves_completed_history(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    generate_project_tasks.invoke({"project_id": project.id})

    sow_task = (
        db_session.query(Task)
        .filter(Task.project_id == project.id, Task.title == "Sow Tomato")
        .order_by(Task.created_at.asc())
        .first()
    )
    complete_task.invoke({"task_id": sow_task.id, "actual_minutes": 22})

    result = regenerate_project_tasks.invoke({"project_id": project.id, "reason": "Adjusted timeline assumptions"})

    db_session.expire_all()
    refreshed_sow = db_session.query(Task).filter(Task.id == sow_task.id).one()
    superseded_count = db_session.query(Task).filter(Task.project_id == project.id, Task.status == "superseded").count()

    assert "Regenerated project tasks" in result
    assert refreshed_sow.status == "done"
    assert superseded_count > 0
    assert db_session.query(TaskGenerationRun).filter(TaskGenerationRun.project_id == project.id).count() == 2


def test_due_and_blocked_queries_reflect_runtime_state_and_lifecycle_updates(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    generate_project_tasks.invoke({"project_id": project.id})

    blocked_before = list_blocked_tasks.invoke({"project_id": project.id})
    sow_task = (
        db_session.query(Task)
        .filter(Task.project_id == project.id, Task.title == "Sow Tomato")
        .order_by(Task.created_at.asc())
        .first()
    )
    transplant_task = (
        db_session.query(Task)
        .filter(Task.project_id == project.id, Task.title == "Transplant Tomato to final location")
        .order_by(Task.created_at.asc())
        .first()
    )

    start_task.invoke({"task_id": sow_task.id, "notes": "Starting tray work."})
    complete_task.invoke({"task_id": sow_task.id, "actual_minutes": 25})
    defer_task.invoke({"task_id": transplant_task.id, "deferred_until": "2026-06-10", "reason": "Waiting for weather."})
    due_after_defer = list_due_tasks.invoke({"project_id": project.id, "days_ahead": 7})
    explain = explain_task_blockers.invoke({"task_id": transplant_task.id})
    task_detail = get_task.invoke({"task_id": transplant_task.id})

    assert "Blocked tasks:" in blocked_before
    assert "Transplant Tomato to final location" not in due_after_defer
    assert "Blockers for task" in explain
    assert "[Task] Transplant Tomato to final location" in task_detail


def test_task_update_skip_series_and_materialization_tools_work(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="start")
    generate_project_tasks.invoke({"project_id": project.id})

    acquire_task = (
        db_session.query(Task)
        .filter(Task.project_id == project.id, Task.title == "Acquire Tomato starts")
        .first()
    )
    watering_series = (
        db_session.query(TaskSeries)
        .filter(TaskSeries.project_id == project.id, TaskSeries.title == "Water Tomato")
        .first()
    )

    update_result = update_task.invoke(
        {
            "task_id": acquire_task.id,
            "estimated_minutes": 40,
            "notes": "Updated after nursery visit.",
        }
    )
    skip_result = skip_task.invoke({"task_id": acquire_task.id, "reason": "User already bought starts."})
    update_series_result = update_task_series.invoke(
        {
            "series_id": watering_series.id,
            "cadence": "every 3 days",
            "cadence_days": 3,
            "default_estimated_minutes": 12,
        }
    )
    list_result = list_task_series.invoke({"project_id": project.id})
    materialize_result = materialize_recurring_tasks.invoke({"project_id": project.id, "days_ahead": 14})

    db_session.expire_all()
    refreshed_task = db_session.query(Task).filter(Task.id == acquire_task.id).one()
    refreshed_series = db_session.query(TaskSeries).filter(TaskSeries.id == watering_series.id).one()

    assert "Updated task" in update_result
    assert "Skipped task" in skip_result
    assert refreshed_task.status == "skipped"
    assert refreshed_task.is_user_modified is True
    assert "Updated recurring task series" in update_series_result
    assert refreshed_series.cadence_days == 3
    assert "Recurring task series:" in list_result
    assert "Materialized" in materialize_result or "No recurring task instances" in materialize_result


def test_task_activity_events_are_queryable_and_generation_rolls_back_on_failure(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")

    generated = generate_project_tasks.invoke({"project_id": project.id})
    project_history = get_project_activity.invoke({"project_id": project.id})
    failed = generate_project_tasks.invoke({"project_id": "missing-project"})

    assert "Generated project tasks" in generated
    assert "task_generation_run_created" in project_history
    assert "task_created" in project_history
    assert "Failed to generate project tasks" in failed
    assert db_session.query(ActivityEvent).filter(ActivityEvent.event_type == "task_generation_run_created").count() == 1
