from __future__ import annotations

from datetime import datetime

from agent.tracker import (
    build_due_task_view,
    compute_task_blocked_state,
    compute_task_urgency,
    generate_tasks_for_revision,
    materialize_task_series,
)
from db.models import ActivityEvent, ActivitySubject, Task, TaskDependency, TaskGenerationRun, TaskSeries
from tests.support.factories import (
    make_profile,
    make_project,
    make_project_brief,
    make_project_execution_spec,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_dependency,
    make_task_generation_run,
    make_task_series,
)


def test_task_tracker_models_can_be_created_and_linked(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    generation_run = make_task_generation_run(db_session, project, revision)
    parent = make_task(db_session, project, revision, generation_run, title="Parent task", generator_key="parent.task")
    child = make_task(
        db_session,
        project,
        revision,
        generation_run,
        title="Child task",
        generator_key="child.task",
        parent_task_id=parent.id,
    )
    series = make_task_series(db_session, project, revision, generation_run, parent_task_id=parent.id)
    dependency = make_task_dependency(db_session, parent, child)

    assert db_session.query(TaskGenerationRun).count() == 1
    assert db_session.query(Task).count() == 2
    assert db_session.query(TaskSeries).count() == 1
    assert db_session.query(TaskDependency).count() == 1
    assert child.parent_task_id == parent.id
    assert series.parent_task_id == parent.id
    assert dependency.blocking_task_id == parent.id


def test_task_urgency_boundaries_and_defer_logic(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    generation_run = make_task_generation_run(db_session, project, revision)
    now = datetime(2026, 4, 12)

    backlog = make_task(
        db_session,
        project,
        revision,
        generation_run,
        title="Backlog task",
        generator_key="backlog.task",
        window_end=datetime(2026, 5, 10),
        deadline=None,
    )
    scheduled = make_task(
        db_session,
        project,
        revision,
        generation_run,
        title="Scheduled task",
        generator_key="scheduled.task",
        window_end=datetime(2026, 4, 20),
        deadline=None,
    )
    time_sensitive = make_task(
        db_session,
        project,
        revision,
        generation_run,
        title="Time-sensitive task",
        generator_key="time_sensitive.task",
        window_end=datetime(2026, 4, 14),
        deadline=None,
    )
    blocker = make_task(
        db_session,
        project,
        revision,
        generation_run,
        title="Blocker task",
        generator_key="blocker.task",
        window_end=datetime(2026, 4, 13),
        deadline=None,
    )
    deferred = make_task(
        db_session,
        project,
        revision,
        generation_run,
        title="Deferred task",
        generator_key="deferred.task",
        scheduled_date=datetime(2026, 4, 13),
        deadline=None,
        window_end=None,
        status="deferred",
        deferred_until=datetime(2026, 4, 20),
    )

    assert compute_task_urgency(backlog, now) == "backlog"
    assert compute_task_urgency(scheduled, now) == "scheduled"
    assert compute_task_urgency(time_sensitive, now) == "time_sensitive"
    assert compute_task_urgency(blocker, now) == "blocker"

    due_now = build_due_task_view(db_session, project_id=project.id, days_ahead=7, now=now)
    due_later = build_due_task_view(db_session, project_id=project.id, days_ahead=14, now=datetime(2026, 4, 21))

    due_now_titles = {row["task"].title for row in due_now}
    due_later_titles = {row["task"].title for row in due_later}

    assert "Deferred task" not in due_now_titles
    assert "Deferred task" in due_later_titles


def test_dependency_blocking_and_series_materialization_behave_as_expected(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    generation_run = make_task_generation_run(db_session, project, revision)
    blocker = make_task(db_session, project, revision, generation_run, title="Prepare bed", generator_key="prepare.bed")
    blocked = make_task(db_session, project, revision, generation_run, title="Transplant tomatoes", generator_key="transplant.tomatoes")
    make_task_dependency(db_session, blocker, blocked)
    series = make_task_series(
        db_session,
        project,
        revision,
        generation_run,
        title="Water tomatoes",
        generator_key="tomato.watering",
        cadence_days=2,
        next_generation_date=datetime(2026, 4, 12),
    )

    assert compute_task_blocked_state(db_session, blocked) is True

    created_once = materialize_task_series(db_session, project_id=project.id, now=datetime(2026, 4, 12), days_ahead=5)
    db_session.commit()
    created_twice = materialize_task_series(db_session, project_id=project.id, now=datetime(2026, 4, 12), days_ahead=5)
    db_session.commit()

    created_dates = {task.scheduled_date.date().isoformat() for task in created_once if task.series_id == series.id}

    assert created_dates == {"2026-04-12", "2026-04-14", "2026-04-16"}
    assert len([task for task in created_twice if task.series_id == series.id]) == 0


def test_event_anchor_generation_creates_follow_up_task_when_anchor_event_exists(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    spec = make_project_execution_spec(
        db_session,
        project,
        revision,
        selected_plants=[
            {
                "name": "Tomato",
                "quantity": 2,
                "propagation_method": "seed",
                "task_profile": "fruiting_vine",
                "event_triggers": [
                    {
                        "event_type": "plant_germinated",
                        "offset_days": 14,
                        "subject_type": "plant",
                        "subject_id": "plant-1",
                    }
                ],
            }
        ],
    )
    event = ActivityEvent(
        actor_type="agent",
        actor_label="rhizome_tool",
        event_type="plant_germinated",
        category="plant",
        summary="Tomato seedlings germinated.",
        project_id=project.id,
        created_at=datetime(2026, 4, 10),
        event_metadata={},
    )
    db_session.add(event)
    db_session.flush()
    db_session.add(
        ActivitySubject(event_id=event.id, subject_type="plant", subject_id="plant-1", role="primary")
    )
    db_session.commit()

    generated = generate_tasks_for_revision(db_session, project_id=project.id, revision_id=revision.id)
    db_session.commit()

    anchored = (
        db_session.query(Task)
        .filter(Task.project_id == project.id, Task.event_anchor_type == "plant_germinated")
        .one()
    )

    assert generated["generation_run"].revision_id == revision.id
    assert anchored.title == "Transplant Tomato to final location"
    assert anchored.event_anchor_type == "plant_germinated"
    assert anchored.scheduled_date.date().isoformat() == "2026-04-24"
