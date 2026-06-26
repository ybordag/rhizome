from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func

from db.models import (
    Bed,
    Container,
    GardeningProject,
    IncidentReport,
    IncidentSubject,
    Plant,
    PlantBatch,
    ProjectBed,
    ProjectContainer,
    ProjectPlant,
    Task,
)


SESSION_CONTEXT_FIELDS = (
    "time_text",
    "energy_text",
    "focus_text",
    "focus_context",
)
OPEN_TASK_STATUSES = {"pending", "in_progress", "deferred", "blocked"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _serialize_dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _focus_context_label(session, user_id: str, subject_type: str, subject_id: str) -> str | None:
    if not subject_type or not subject_id:
        return None
    row = _resolve_context_object(session, user_id, subject_type, subject_id)
    if row is None:
        return None
    if subject_type == "plant":
        return f"{row.name} ({row.variety})" if row.variety else row.name
    if subject_type in {"batch", "bed", "container", "project"}:
        return row.name
    if subject_type == "task":
        return row.title
    if subject_type == "incident":
        return row.summary
    return None


def _resolve_context_object(session, user_id: str, subject_type: str, subject_id: str) -> Any | None:
    if not subject_type or not subject_id:
        return None
    if subject_type == "plant":
        return session.query(Plant).filter(Plant.id == subject_id, Plant.user_id == user_id).first()
    if subject_type == "batch":
        return session.query(PlantBatch).filter(PlantBatch.id == subject_id, PlantBatch.user_id == user_id).first()
    if subject_type == "bed":
        return session.query(Bed).filter(Bed.id == subject_id, Bed.user_id == user_id).first()
    if subject_type == "container":
        return session.query(Container).filter(Container.id == subject_id, Container.user_id == user_id).first()
    if subject_type == "project":
        return (
            session.query(GardeningProject)
            .filter(GardeningProject.id == subject_id, GardeningProject.user_id == user_id)
            .first()
        )
    if subject_type == "task":
        return (
            session.query(Task)
            .join(GardeningProject, Task.project_id == GardeningProject.id)
            .filter(Task.id == subject_id, GardeningProject.user_id == user_id)
            .first()
        )
    if subject_type == "incident":
        return (
            session.query(IncidentReport)
            .filter(IncidentReport.id == subject_id, IncidentReport.user_id == user_id)
            .first()
        )
    return None


def _truncate(value: str | None, limit: int = 500) -> str:
    if not value:
        return "none"
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _plant_location_name(session, row: Plant) -> str | None:
    if row.container_id:
        container = session.query(Container).filter(Container.id == row.container_id).first()
        if container:
            return container.name
    if row.bed_id:
        bed = session.query(Bed).filter(Bed.id == row.bed_id).first()
        if bed:
            return bed.name
    return None


def _project_counts(session, project_id: str) -> dict[str, int]:
    return {
        "plant_count": session.query(ProjectPlant)
        .filter(ProjectPlant.project_id == project_id, ProjectPlant.removed_at.is_(None))
        .count(),
        "bed_count": session.query(ProjectBed).filter(ProjectBed.project_id == project_id).count(),
        "container_count": session.query(ProjectContainer).filter(ProjectContainer.project_id == project_id).count(),
        "batch_count": session.query(PlantBatch).filter(PlantBatch.project_id == project_id).count(),
    }


def _project_name(session, project_id: str | None) -> str:
    if not project_id:
        return "none"
    project = session.query(GardeningProject).filter(GardeningProject.id == project_id).first()
    return project.name if project else project_id


def _batch_status_breakdown(session, batch_id: str) -> str:
    rows = (
        session.query(Plant.status, func.count(Plant.id))
        .filter(Plant.batch_id == batch_id)
        .group_by(Plant.status)
        .all()
    )
    if not rows:
        return "none"
    return ", ".join(f"{status or 'unknown'}: {count}" for status, count in rows)


def _task_is_blocked(session, row: Task) -> bool:
    try:
        from agent.domain.tracker import compute_task_blocked_state

        return bool(compute_task_blocked_state(session, row))
    except Exception:
        return row.status == "blocked"


def _task_prompt_text(session, row: Task) -> str:
    base = row.to_summary()
    due_bits = []
    if row.earliest_start:
        due_bits.append(f"earliest start: {_serialize_dt(row.earliest_start)}")
    if row.window_start or row.window_end:
        due_bits.append(
            f"window: {_serialize_dt(row.window_start) or 'not set'} "
            f"to {_serialize_dt(row.window_end) or 'not set'}"
        )
    if row.deferred_until:
        due_bits.append(f"deferred until: {_serialize_dt(row.deferred_until)}")
    timing = " | ".join(due_bits) if due_bits else "none"
    return (
        base
        + f"\n  Project: {_project_name(session, row.project_id)}"
        + f"\n  Blocked: {_task_is_blocked(session, row)}"
        + f"\n  Additional timing: {timing}"
        + f"\n  Description: {_truncate(row.description, 300)}"
        + f"\n  Notes: {_truncate(row.notes, 300)}"
    )


def _task_matches_subject(row: Task, subject_type: str, subject_ids: set[str]) -> bool:
    if not subject_ids:
        return False
    if subject_type == "project" and row.project_id in subject_ids:
        return True
    for subject in row.linked_subjects or []:
        if not isinstance(subject, dict):
            continue
        if subject.get("subject_type") == subject_type and subject.get("subject_id") in subject_ids:
            return True
    return False


def _project_ids_for_context_object(session, subject_type: str, subject_id: str, row: Any) -> set[str]:
    if subject_type == "project":
        return {subject_id}
    if subject_type == "batch":
        return {row.project_id} if row.project_id else set()
    if subject_type == "plant":
        rows = session.query(ProjectPlant.project_id).filter(
            ProjectPlant.plant_id == subject_id,
            ProjectPlant.removed_at.is_(None),
        ).all()
        return {project_id for (project_id,) in rows}
    if subject_type == "bed":
        rows = session.query(ProjectBed.project_id).filter(ProjectBed.bed_id == subject_id).all()
        return {project_id for (project_id,) in rows}
    if subject_type == "container":
        rows = session.query(ProjectContainer.project_id).filter(ProjectContainer.container_id == subject_id).all()
        return {project_id for (project_id,) in rows}
    if subject_type == "incident":
        return {row.project_id} if row.project_id else set()
    if subject_type == "task":
        return {row.project_id} if row.project_id else set()
    return set()


def _related_subject_ids_for_context_object(session, subject_type: str, subject_id: str, row: Any) -> dict[str, set[str]]:
    subjects: dict[str, set[str]] = {subject_type: {subject_id}}
    project_ids = _project_ids_for_context_object(session, subject_type, subject_id, row)
    if project_ids:
        subjects["project"] = project_ids
    if subject_type == "batch":
        plant_ids = {
            plant_id
            for (plant_id,) in session.query(Plant.id)
            .filter(Plant.batch_id == subject_id, Plant.user_id == row.user_id)
            .all()
        }
        if plant_ids:
            subjects["plant"] = plant_ids
    return subjects


def _related_open_tasks_for_context_object(
    session,
    user_id: str,
    subject_type: str,
    subject_id: str,
    row: Any,
    *,
    limit: int = 5,
) -> list[Task]:
    subjects = _related_subject_ids_for_context_object(session, subject_type, subject_id, row)
    project_ids = subjects.get("project", set())
    candidates = (
        session.query(Task)
        .join(GardeningProject, Task.project_id == GardeningProject.id)
        .filter(
            GardeningProject.user_id == user_id,
            Task.status.in_(sorted(OPEN_TASK_STATUSES)),
        )
        .all()
    )
    related: list[Task] = []
    seen: set[str] = set()
    for task in candidates:
        if task.id in seen:
            continue
        if task.project_id in project_ids or any(
            _task_matches_subject(task, stype, ids) for stype, ids in subjects.items()
        ):
            related.append(task)
            seen.add(task.id)
    related.sort(key=lambda task: (
        0 if _task_is_blocked(session, task) else 1,
        _serialize_dt(task.earliest_start or task.scheduled_date or task.deadline) or "",
        task.estimated_minutes or 0,
        task.title.lower(),
    ))
    return related[:limit]


def _related_task_prompt_lines(session, tasks: list[Task]) -> list[str]:
    lines = []
    for task in tasks:
        due = _serialize_dt(task.earliest_start or task.scheduled_date or task.deadline) or "not scheduled"
        minutes = f"{task.estimated_minutes} min" if task.estimated_minutes is not None else "unknown minutes"
        blocked = ", blocker" if _task_is_blocked(session, task) else ""
        lines.append(f"- {task.title} [id: {task.id}] ({task.status}, {task.priority}, {minutes}, due {due}{blocked})")
    return lines


def _incident_prompt_text(session, subject_id: str, row: IncidentReport) -> str:
    detected = _serialize_dt(row.detected_at) or "unknown"
    affected_count = session.query(IncidentSubject).filter(IncidentSubject.incident_id == subject_id).count()
    project = _project_name(session, row.project_id)
    return (
        f"[Incident] {row.incident_type} (id: {subject_id})\n"
        f"  Status: {row.status} | Severity: {row.severity or 'unknown'} | Affected subjects: {affected_count}\n"
        f"  Project: {project}\n"
        f"  Summary: {_truncate(row.summary, 500)}\n"
        f"  Detected at: {detected}\n"
        f"  Notes: {_truncate(row.notes, 300)}"
    )


def _context_object_prompt_text(session, user_id: str, subject_type: str, subject_id: str, row: Any) -> str:
    if subject_type == "plant":
        text = row.to_detailed(location_name=_plant_location_name(session, row))
    elif subject_type == "batch":
        text = (
            row.to_detailed()
            + f"\n  Project: {_project_name(session, row.project_id)}"
            + f"\n  Child plant status: {_batch_status_breakdown(session, subject_id)}"
        )
    elif subject_type == "bed":
        text = row.to_detailed()
    elif subject_type == "container":
        text = row.to_detailed()
    elif subject_type == "project":
        text = row.to_detailed(**_project_counts(session, subject_id))
    elif subject_type == "task":
        text = _task_prompt_text(session, row)
    elif subject_type == "incident":
        text = _incident_prompt_text(session, subject_id, row)
    else:
        text = f"[{subject_type}] {subject_id} (id: {subject_id})"

    related_tasks = _related_open_tasks_for_context_object(session, user_id, subject_type, subject_id, row)
    if related_tasks:
        text += "\n  Related open tasks:\n  " + "\n  ".join(_related_task_prompt_lines(session, related_tasks))
    return text


def context_refs_prompt_text(
    session,
    user_id: str,
    items: Any,
    *,
    include_missing: bool = False,
) -> str:
    rendered = []
    for item in _normalize_focus_context(items):
        subject_type = item["subject_type"]
        subject_id = item["subject_id"]
        row = _resolve_context_object(session, user_id, subject_type, subject_id)
        if row is None:
            if include_missing:
                rendered.append(f"- {subject_type}: {subject_id} [id: {subject_id}]")
            continue
        rendered.append(_context_object_prompt_text(session, user_id, subject_type, subject_id, row))
    return "\n\n".join(rendered)


def _normalize_focus_context(items: Any) -> list[dict[str, Any]]:
    if not items:
        return []
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        subject_type = item.get("subject_type")
        subject_id = item.get("subject_id")
        if subject_type and subject_id:
            normalized.append({"subject_type": subject_type, "subject_id": subject_id})
    return normalized[:10]


def _focus_context_to_view(session, user_id: str, items: Any) -> list[dict[str, Any]]:
    refs = []
    for item in _normalize_focus_context(items):
        refs.append(
            {
                **item,
                "label": _focus_context_label(session, user_id, item["subject_type"], item["subject_id"]),
            }
        )
    return refs


def empty_session_context_view() -> dict[str, Any]:
    return {
        "time_text": None,
        "energy_text": None,
        "focus_text": None,
        "focus_context": [],
        "source": "unset",
        "updated_at": None,
    }


def session_context_to_view_data(session, user_id: str, context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return empty_session_context_view()

    data = {
        "time_text": context.get("time_text"),
        "energy_text": context.get("energy_text"),
        "focus_text": context.get("focus_text"),
        "focus_context": _focus_context_to_view(session, user_id, context.get("focus_context")),
        "source": context.get("source") or "inferred",
        "updated_at": _serialize_dt(context.get("updated_at")),
    }
    return data


def normalize_inferred_session_context(
    session,
    user_id: str,
    inferred: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    data = {field: inferred.get(field) for field in SESSION_CONTEXT_FIELDS}
    data["source"] = "inferred"
    data["updated_at"] = _serialize_dt(now or _utc_now())
    return data


def session_context_for_graph(
    inferred: dict[str, Any] | None,
    stored: dict[str, Any] | None,
) -> dict[str, Any]:
    if not stored:
        return inferred or {}

    merged = dict(inferred or {})
    for field in SESSION_CONTEXT_FIELDS:
        if field in stored:
            merged[field] = stored.get(field)
    if stored.get("source"):
        merged["source"] = stored.get("source")
    return merged


def session_context_summary_text(session, user_id: str, context: dict[str, Any] | None) -> str | None:
    if not context:
        return None

    lines = []
    if context.get("time_text"):
        lines.append(f"Time available: {context['time_text']}")
    if context.get("energy_text"):
        lines.append(f"Energy: {context['energy_text']}")
    if context.get("focus_text"):
        lines.append(f"Thread focus: {context['focus_text']}")

    focus_text = context_refs_prompt_text(
        session,
        user_id,
        context.get("focus_context"),
        include_missing=True,
    )
    if focus_text:
        lines.append("Focus objects:")
        lines.append(focus_text)

    if not lines:
        return None
    return "\n".join(lines)


def apply_session_context_patch(
    session,
    user_id: str,
    current: dict[str, Any] | None,
    updates: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    next_context = dict(current or {})
    for field, value in updates.items():
        if field in SESSION_CONTEXT_FIELDS:
            if field == "focus_context":
                next_context[field] = _normalize_focus_context(value)
            else:
                next_context[field] = value

    next_context["source"] = "user"
    next_context["updated_at"] = _serialize_dt(now or _utc_now())
    return next_context
