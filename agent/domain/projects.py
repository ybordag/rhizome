"""
Domain logic for projects shared between the chat-tool layer (which formats
this data as prose) and the data API (which serializes it as structured
JSON for the frontend).
"""
from datetime import datetime, timezone

from db.database import current_user_id
from db.models import GardeningProject, ProjectExecutionSpec, ProjectRevision, Task


def get_project_progress_data(session, project_id: str) -> dict | None:
    """Compute task completion progress, timeline status, and budget
    tracking for a project. Returns None if no project with that id exists
    for the current user."""
    project = session.query(GardeningProject).filter(
        GardeningProject.id == project_id,
        GardeningProject.user_id == current_user_id.get(),
    ).first()
    if not project:
        return None

    revision = (
        session.query(ProjectRevision)
        .filter(ProjectRevision.project_id == project_id, ProjectRevision.status == "active")
        .order_by(ProjectRevision.revision_number.desc())
        .first()
    )
    spec = (
        session.query(ProjectExecutionSpec)
        .filter(
            ProjectExecutionSpec.project_id == project_id,
            ProjectExecutionSpec.status == "active",
        )
        .order_by(ProjectExecutionSpec.updated_at.desc())
        .first()
    ) if revision else None

    all_tasks = (
        session.query(Task)
        .filter(Task.project_id == project_id, Task.status != "superseded")
        .all()
    )
    leaf_tasks = [t for t in all_tasks if t.parent_task_id is not None]
    total = len(leaf_tasks)
    done = sum(1 for t in leaf_tasks if t.status == "done")
    skipped = sum(1 for t in leaf_tasks if t.status == "skipped")
    blocked = sum(1 for t in leaf_tasks if t.status == "blocked")
    in_progress = sum(1 for t in leaf_tasks if t.status == "in_progress")
    pct = round((done + skipped) / total * 100) if total else 0

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    data = {
        "project_id": project.id,
        "project_name": project.name,
        "status": project.status,
        "tasks_total": total,
        "tasks_done": done,
        "tasks_skipped": skipped,
        "tasks_in_progress": in_progress,
        "tasks_blocked": blocked,
        "percent_complete": pct,
        "schedule_percent_elapsed": None,
        "days_remaining": None,
        "on_track": None,
        "budget_cap": None,
        "estimated_cost": None,
        "budget_percent_used": None,
        "critical_tasks": [],
    }

    if spec:
        windows = spec.timing_windows or {}
        start = windows.get("expected_first_action_date")
        completion = windows.get("expected_completion_date")
        if start and completion:
            try:
                start_dt = datetime.fromisoformat(start) if isinstance(start, str) else start
                end_dt = datetime.fromisoformat(completion) if isinstance(completion, str) else completion
                total_days = max((end_dt - start_dt).days, 1)
                elapsed_days = max((now - start_dt).days, 0)
                schedule_pct = round(min(elapsed_days / total_days * 100, 100))
                days_remaining = max((end_dt - now).days, 0)
                on_track = pct >= schedule_pct - 10
                data["schedule_percent_elapsed"] = schedule_pct
                data["days_remaining"] = days_remaining
                data["on_track"] = on_track
            except (ValueError, TypeError):
                pass

    if revision:
        plan = revision.approved_plan or {}
        cost_estimate = plan.get("cost_estimate") or {}
        budget_cap = project.budget_ceiling
        estimated_cost = cost_estimate.get("total_estimated_cost")
        data["budget_cap"] = budget_cap
        data["estimated_cost"] = estimated_cost
        if budget_cap and estimated_cost:
            data["budget_percent_used"] = round(estimated_cost / budget_cap * 100)

    blocker_tasks = [t for t in leaf_tasks if t.status not in {"done", "skipped", "superseded", "deferred"}]
    from agent.domain.tracker import compute_task_urgency
    critical_tasks = [
        t for t in blocker_tasks
        if compute_task_urgency(t, now) == "blocker"
    ]
    data["critical_tasks"] = [
        {"id": t.id, "title": t.title, "status": t.status} for t in critical_tasks
    ]

    return data
