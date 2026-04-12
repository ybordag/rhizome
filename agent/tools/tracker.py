"""
Persistent task-tracker tools for generated project work, recurring care, and lifecycle updates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from langchain.tools import tool

from agent.activity_log import record_update_event, snapshot_model
from agent.tracker import (
    VALID_TASK_STATUSES,
    build_due_task_view,
    compute_task_blocked_state,
    compute_task_urgency,
    format_due_tasks,
    format_task_detail,
    format_task_series,
    generate_tasks_for_revision,
    materialize_task_series,
)
from db.database import SessionLocal
from db.models import Task, TaskDependency, TaskGenerationRun, TaskSeries


def _parse_date(value: Optional[str], field_name: str) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name} '{value}'. Use ISO format YYYY-MM-DD.") from exc


def _task_or_error(session, task_id: str) -> Task:
    task = session.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError(f"No task found with id {task_id}.")
    return task


def _series_or_error(session, series_id: str) -> TaskSeries:
    series = session.query(TaskSeries).filter(TaskSeries.id == series_id).first()
    if not series:
        raise ValueError(f"No task series found with id {series_id}.")
    return series


def _validate_minutes(value: Optional[int], field_name: str) -> Optional[str]:
    if value is not None and value < 0:
        return f"{field_name} must be 0 or greater."
    return None


@tool
def generate_project_tasks(project_id: str, revision_id: Optional[str] = None) -> str:
    """Generate the first persistent task graph for an accepted project revision."""
    session = SessionLocal()
    try:
        generated = generate_tasks_for_revision(
            session,
            project_id=project_id,
            revision_id=revision_id,
            run_type="initial",
        )
        session.commit()
        run = generated["generation_run"]
        milestone_count = len(generated["milestone_tasks"])
        series_count = len(generated["task_series"])
        materialized_count = len(generated["materialized_tasks"])
        return (
            f"Generated project tasks for revision {generated['revision'].revision_number}.\n"
            f"- Generation run: {run.id}\n"
            f"- Milestone tasks: {milestone_count}\n"
            f"- Recurring series: {series_count}\n"
            f"- Materialized recurring tasks: {materialized_count}"
        )
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to generate project tasks: {e}")
        return f"Failed to generate project tasks: {str(e)}"
    finally:
        session.close()


@tool
def regenerate_project_tasks(
    project_id: str,
    revision_id: Optional[str] = None,
    reason: Optional[str] = None,
) -> str:
    """Regenerate project tasks, superseding replaceable future work from prior runs."""
    session = SessionLocal()
    try:
        generated = generate_tasks_for_revision(
            session,
            project_id=project_id,
            revision_id=revision_id,
            run_type="regeneration",
            reason=reason,
        )
        session.commit()
        run = generated["generation_run"]
        return (
            f"Regenerated project tasks for revision {generated['revision'].revision_number}.\n"
            f"- Generation run: {run.id}\n"
            f"- Milestone tasks: {len(generated['milestone_tasks'])}\n"
            f"- Recurring series: {len(generated['task_series'])}\n"
            f"- Materialized recurring tasks: {len(generated['materialized_tasks'])}"
        )
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to regenerate project tasks: {e}")
        return f"Failed to regenerate project tasks: {str(e)}"
    finally:
        session.close()


@tool
def materialize_recurring_tasks(project_id: Optional[str] = None, days_ahead: int = 14) -> str:
    """Materialize near-term recurring task instances from active task series."""
    session = SessionLocal()
    try:
        if days_ahead < 1:
            return "days_ahead must be at least 1."
        created = materialize_task_series(session, project_id=project_id, days_ahead=days_ahead)
        session.commit()
        if not created:
            return "No recurring task instances needed to be materialized."
        return (
            f"Materialized {len(created)} recurring task instances.\n"
            f"- Projects affected: {len({task.project_id for task in created})}\n"
            f"- Horizon: {days_ahead} days"
        )
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to materialize recurring tasks: {e}")
        return f"Failed to materialize recurring tasks: {str(e)}"
    finally:
        session.close()


@tool
def list_project_tasks(project_id: str, status: Optional[str] = None, include_superseded: bool = False) -> str:
    """List generated and manual tasks for a project, grouped by section."""
    session = SessionLocal()
    try:
        query = session.query(Task).filter(Task.project_id == project_id)
        if status:
            if status not in VALID_TASK_STATUSES:
                return f"Invalid task status '{status}'. Must be one of: {', '.join(sorted(VALID_TASK_STATUSES))}."
            query = query.filter(Task.status == status)
        elif not include_superseded:
            query = query.filter(Task.status != "superseded")

        tasks = query.order_by(Task.parent_task_id.asc(), Task.deadline.asc(), Task.scheduled_date.asc()).all()
        if not tasks:
            return "No tasks found."

        section_tasks = {task.id: task for task in tasks if task.parent_task_id is None}
        child_tasks: dict[str, list[Task]] = {task.id: [] for task in section_tasks.values()}
        loose_tasks: list[Task] = []
        for task in tasks:
            if task.parent_task_id is None:
                continue
            if task.parent_task_id in child_tasks:
                child_tasks[task.parent_task_id].append(task)
            else:
                loose_tasks.append(task)

        lines = [f"Tasks for project {project_id}:", ""]
        ordered_sections = sorted(section_tasks.values(), key=lambda item: item.generator_key)
        for section in ordered_sections:
            lines.append(f"{section.title}:")
            entries = [task for task in child_tasks[section.id] if task.status != "superseded" or include_superseded]
            if not entries:
                lines.append("  - none")
            else:
                for task in entries:
                    when = task.deadline or task.window_end or task.scheduled_date
                    lines.append(
                        f"  - [{task.status}] {task.title} | {when.date().isoformat() if when else 'not set'}"
                    )
            lines.append("")

        if loose_tasks:
            lines.append("Ungrouped:")
            for task in loose_tasks:
                when = task.deadline or task.window_end or task.scheduled_date
                lines.append(
                    f"  - [{task.status}] {task.title} | {when.date().isoformat() if when else 'not set'}"
                )
        return "\n".join(lines).rstrip()
    except Exception as e:
        print(f"[DEBUG] Failed to list project tasks: {e}")
        return f"Failed to list project tasks: {str(e)}"
    finally:
        session.close()


@tool
def get_task(task_id: str) -> str:
    """Show detailed information for a specific task."""
    session = SessionLocal()
    try:
        task = _task_or_error(session, task_id)
        detail = format_task_detail(session, task)
        blocked = compute_task_blocked_state(session, task)
        urgency = compute_task_urgency(task, datetime.utcnow())
        return detail + f"\n  Computed urgency: {urgency}\n  Blocked: {blocked}"
    except Exception as e:
        print(f"[DEBUG] Failed to get task: {e}")
        return f"Failed to get task: {str(e)}"
    finally:
        session.close()


@tool
def list_due_tasks(project_id: Optional[str] = None, days_ahead: int = 7) -> str:
    """List due tasks with runtime-computed urgency instead of stored urgency state."""
    session = SessionLocal()
    try:
        if days_ahead < 1:
            return "days_ahead must be at least 1."
        rows = build_due_task_view(session, project_id=project_id, days_ahead=days_ahead)
        return format_due_tasks(rows)
    except Exception as e:
        print(f"[DEBUG] Failed to list due tasks: {e}")
        return f"Failed to list due tasks: {str(e)}"
    finally:
        session.close()


@tool
def list_blocked_tasks(project_id: Optional[str] = None) -> str:
    """List tasks currently blocked by dependencies or unresolved event anchors."""
    session = SessionLocal()
    try:
        query = session.query(Task).filter(Task.status.notin_(["done", "skipped", "superseded"]))
        if project_id:
            query = query.filter(Task.project_id == project_id)
        blocked = [
            task
            for task in query.order_by(Task.deadline.asc(), Task.scheduled_date.asc()).all()
            if task.parent_task_id and compute_task_blocked_state(session, task)
        ]
        if not blocked:
            return "No blocked tasks found."
        return "Blocked tasks:\n" + "\n".join(f"- {task.title} [{task.status}]" for task in blocked)
    except Exception as e:
        print(f"[DEBUG] Failed to list blocked tasks: {e}")
        return f"Failed to list blocked tasks: {str(e)}"
    finally:
        session.close()


@tool
def list_task_series(project_id: str) -> str:
    """List recurring task rules for a project."""
    session = SessionLocal()
    try:
        series_list = (
            session.query(TaskSeries)
            .filter(TaskSeries.project_id == project_id)
            .order_by(TaskSeries.next_generation_date.asc())
            .all()
        )
        return format_task_series(series_list)
    except Exception as e:
        print(f"[DEBUG] Failed to list task series: {e}")
        return f"Failed to list task series: {str(e)}"
    finally:
        session.close()


@tool
def explain_task_blockers(task_id: str) -> str:
    """Explain the current blockers preventing a task from moving forward."""
    session = SessionLocal()
    try:
        task = _task_or_error(session, task_id)
        blockers = (
            session.query(Task)
            .join(TaskDependency, Task.id == TaskDependency.blocking_task_id)
            .filter(TaskDependency.blocked_task_id == task.id)
            .all()
        )
        lines = [f"Blockers for task '{task.title}':", ""]
        if task.event_anchor_type and task.scheduled_date is None:
            lines.append(
                f"- Waiting for event '{task.event_anchor_type}'"
                + (
                    f" on {task.event_anchor_subject_type}:{task.event_anchor_subject_id}"
                    if task.event_anchor_subject_type and task.event_anchor_subject_id
                    else ""
                )
            )
        if blockers:
            for blocker in blockers:
                lines.append(f"- {blocker.title} [{blocker.status}]")
        if len(lines) == 2:
            lines.append("- none")
        return "\n".join(lines)
    except Exception as e:
        print(f"[DEBUG] Failed to explain task blockers: {e}")
        return f"Failed to explain task blockers: {str(e)}"
    finally:
        session.close()


@tool
def start_task(task_id: str, notes: Optional[str] = None) -> str:
    """Mark a task as in progress if it is ready to start."""
    session = SessionLocal()
    try:
        task = _task_or_error(session, task_id)
        if compute_task_blocked_state(session, task):
            return f"Task '{task.title}' is blocked and cannot be started yet."
        if task.status in {"done", "skipped", "superseded"}:
            return f"Task '{task.title}' cannot be started from status {task.status}."

        before = snapshot_model(task)
        task.status = "in_progress"
        if notes:
            task.notes = f"{task.notes}\n{notes}".strip() if task.notes else notes
        record_update_event(
            session,
            event_type="task_started",
            category="task",
            summary=f"Started task '{task.title}'.",
            before=before,
            obj=task,
            project_id=task.project_id,
            revision_id=task.revision_id,
            subjects=[{"subject_type": "project", "subject_id": task.project_id, "role": "affected"}, {"subject_type": "task", "subject_id": task.id, "role": "primary"}],
        )
        session.commit()
        return f"Task '{task.title}' started."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to start task: {e}")
        return f"Failed to start task: {str(e)}"
    finally:
        session.close()


@tool
def complete_task(task_id: str, actual_minutes: Optional[int] = None, notes: Optional[str] = None) -> str:
    """Complete a task and unblock dependent work when possible."""
    session = SessionLocal()
    try:
        error = _validate_minutes(actual_minutes, "actual_minutes")
        if error:
            return error
        task = _task_or_error(session, task_id)
        before = snapshot_model(task)
        task.status = "done"
        task.completed_at = datetime.utcnow()
        if actual_minutes is not None:
            task.actual_minutes = actual_minutes
        if notes:
            task.notes = f"{task.notes}\n{notes}".strip() if task.notes else notes

        record_update_event(
            session,
            event_type="task_completed",
            category="task",
            summary=f"Completed task '{task.title}'.",
            before=before,
            obj=task,
            project_id=task.project_id,
            revision_id=task.revision_id,
            subjects=[{"subject_type": "project", "subject_id": task.project_id, "role": "affected"}, {"subject_type": "task", "subject_id": task.id, "role": "primary"}],
        )

        dependents = (
            session.query(Task)
            .join(TaskDependency, Task.id == TaskDependency.blocked_task_id)
            .filter(TaskDependency.blocking_task_id == task.id)
            .all()
        )
        unblocked_titles = []
        for dependent in dependents:
            dependent_before = snapshot_model(dependent)
            if dependent.status == "blocked" and not compute_task_blocked_state(session, dependent):
                dependent.status = "pending"
                record_update_event(
                    session,
                    event_type="task_updated",
                    category="task",
                    summary=f"Unblocked task '{dependent.title}' after completing '{task.title}'.",
                    before=dependent_before,
                    obj=dependent,
                    project_id=dependent.project_id,
                    revision_id=dependent.revision_id,
                    subjects=[{"subject_type": "project", "subject_id": dependent.project_id, "role": "affected"}, {"subject_type": "task", "subject_id": dependent.id, "role": "primary"}],
                )
                unblocked_titles.append(dependent.title)
        session.commit()
        if unblocked_titles:
            return f"Completed task '{task.title}'. Unblocked: {', '.join(unblocked_titles)}."
        return f"Completed task '{task.title}'."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to complete task: {e}")
        return f"Failed to complete task: {str(e)}"
    finally:
        session.close()


@tool
def skip_task(task_id: str, reason: str) -> str:
    """Skip a task with a required rationale."""
    session = SessionLocal()
    try:
        task = _task_or_error(session, task_id)
        before = snapshot_model(task)
        task.status = "skipped"
        task.notes = f"{task.notes}\nSkip reason: {reason}".strip() if task.notes else f"Skip reason: {reason}"
        record_update_event(
            session,
            event_type="task_skipped",
            category="task",
            summary=f"Skipped task '{task.title}'.",
            before=before,
            obj=task,
            project_id=task.project_id,
            revision_id=task.revision_id,
            metadata={"reason": reason},
            subjects=[{"subject_type": "project", "subject_id": task.project_id, "role": "affected"}, {"subject_type": "task", "subject_id": task.id, "role": "primary"}],
        )
        session.commit()
        return f"Skipped task '{task.title}'."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to skip task: {e}")
        return f"Failed to skip task: {str(e)}"
    finally:
        session.close()


@tool
def defer_task(task_id: str, deferred_until: str, reason: Optional[str] = None) -> str:
    """Defer a task until a later date."""
    session = SessionLocal()
    try:
        task = _task_or_error(session, task_id)
        defer_dt = _parse_date(deferred_until, "deferred_until")
        before = snapshot_model(task)
        task.status = "deferred"
        task.deferred_until = defer_dt
        if reason:
            task.notes = f"{task.notes}\nDeferred: {reason}".strip() if task.notes else f"Deferred: {reason}"
        record_update_event(
            session,
            event_type="task_deferred",
            category="task",
            summary=f"Deferred task '{task.title}' until {defer_dt.date().isoformat()}.",
            before=before,
            obj=task,
            project_id=task.project_id,
            revision_id=task.revision_id,
            metadata={"reason": reason, "deferred_until": defer_dt.isoformat()},
            subjects=[{"subject_type": "project", "subject_id": task.project_id, "role": "affected"}, {"subject_type": "task", "subject_id": task.id, "role": "primary"}],
        )
        session.commit()
        return f"Deferred task '{task.title}' until {defer_dt.date().isoformat()}."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to defer task: {e}")
        return f"Failed to defer task: {str(e)}"
    finally:
        session.close()


@tool
def update_task(
    task_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    scheduled_date: Optional[str] = None,
    earliest_start: Optional[str] = None,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    deadline: Optional[str] = None,
    estimated_minutes: Optional[int] = None,
    notes: Optional[str] = None,
    status: Optional[str] = None,
    reversible: Optional[bool] = None,
    what_happens_if_skipped: Optional[str] = None,
    what_happens_if_delayed: Optional[str] = None,
) -> str:
    """Update editable task fields without regenerating the full project task graph."""
    session = SessionLocal()
    try:
        task = _task_or_error(session, task_id)
        error = _validate_minutes(estimated_minutes, "estimated_minutes")
        if error:
            return error
        if status is not None and status not in VALID_TASK_STATUSES:
            return f"Invalid task status '{status}'. Must be one of: {', '.join(sorted(VALID_TASK_STATUSES))}."

        before = snapshot_model(task)
        if title is not None:
            task.title = title
        if description is not None:
            task.description = description
        if scheduled_date is not None:
            task.scheduled_date = _parse_date(scheduled_date, "scheduled_date")
        if earliest_start is not None:
            task.earliest_start = _parse_date(earliest_start, "earliest_start")
        if window_start is not None:
            task.window_start = _parse_date(window_start, "window_start")
        if window_end is not None:
            task.window_end = _parse_date(window_end, "window_end")
        if deadline is not None:
            task.deadline = _parse_date(deadline, "deadline")
        if estimated_minutes is not None:
            task.estimated_minutes = estimated_minutes
        if notes is not None:
            task.notes = notes
        if status is not None:
            task.status = status
        if reversible is not None:
            task.reversible = reversible
        if what_happens_if_skipped is not None:
            task.what_happens_if_skipped = what_happens_if_skipped
        if what_happens_if_delayed is not None:
            task.what_happens_if_delayed = what_happens_if_delayed
        task.is_user_modified = True

        event = record_update_event(
            session,
            event_type="task_updated",
            category="task",
            summary=f"Updated task '{task.title}'.",
            before=before,
            obj=task,
            project_id=task.project_id,
            revision_id=task.revision_id,
            subjects=[{"subject_type": "project", "subject_id": task.project_id, "role": "affected"}, {"subject_type": "task", "subject_id": task.id, "role": "primary"}],
        )
        if event is None:
            session.rollback()
            return "No task fields changed."
        session.commit()
        return f"Updated task '{task.title}'."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to update task: {e}")
        return f"Failed to update task: {str(e)}"
    finally:
        session.close()


@tool
def update_task_series(
    series_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    cadence: Optional[str] = None,
    cadence_days: Optional[int] = None,
    next_generation_date: Optional[str] = None,
    default_estimated_minutes: Optional[int] = None,
    active: Optional[bool] = None,
) -> str:
    """Update a recurring task rule used for rolling task materialization."""
    session = SessionLocal()
    try:
        series = _series_or_error(session, series_id)
        error = _validate_minutes(default_estimated_minutes, "default_estimated_minutes")
        if error:
            return error

        before = snapshot_model(series)
        if title is not None:
            series.title = title
        if description is not None:
            series.description = description
        if cadence is not None:
            series.cadence = cadence
        if cadence_days is not None:
            if cadence_days < 1:
                return "cadence_days must be at least 1."
            series.cadence_days = cadence_days
        if next_generation_date is not None:
            series.next_generation_date = _parse_date(next_generation_date, "next_generation_date")
        if default_estimated_minutes is not None:
            series.default_estimated_minutes = default_estimated_minutes
        if active is not None:
            series.active = active

        event = record_update_event(
            session,
            event_type="task_series_updated",
            category="task",
            summary=f"Updated recurring task series '{series.title}'.",
            before=before,
            obj=series,
            project_id=series.project_id,
            revision_id=series.revision_id,
            subjects=[{"subject_type": "project", "subject_id": series.project_id, "role": "affected"}, {"subject_type": "task_series", "subject_id": series.id, "role": "primary"}],
        )
        if event is None:
            session.rollback()
            return "No task series fields changed."
        session.commit()
        return f"Updated recurring task series '{series.title}'."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to update task series: {e}")
        return f"Failed to update task series: {str(e)}"
    finally:
        session.close()

