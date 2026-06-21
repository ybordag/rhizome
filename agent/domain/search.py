from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_

from db.models import (
    Bed,
    Container,
    GardeningProject,
    IncidentReport,
    IncidentSubject,
    Plant,
    Task,
)

ALL_TYPES = ("plant", "bed", "container", "task", "project", "incident")


def _is_uuid(value: str) -> bool:
    try:
        _uuid.UUID(value)
        return True
    except ValueError:
        return False


def _fmt_date(dt: Optional[datetime]) -> Optional[str]:
    return dt.date().isoformat() if dt else None


def _last_care_summary(plant: Plant) -> Optional[str]:
    candidates = [
        t for t in [
            plant.last_watered_at,
            plant.last_fertilized_at,
            plant.last_inspected_at,
            plant.last_treated_at,
            plant.last_pruned_at,
        ]
        if t is not None
    ]
    if not candidates:
        return None
    return f"Last care {max(candidates).date().isoformat()}"


def _due_summary(task: Task) -> Optional[str]:
    dt = task.scheduled_date or task.deadline
    if dt is None:
        return None
    label = "Due" if task.deadline else "Scheduled"
    return f"{label} {dt.date().isoformat()}"


def _truncate(text: str, max_len: int = 60) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


# ---------------------------------------------------------------------------
# Per-type search helpers
# ---------------------------------------------------------------------------

def _search_plants(session, user_id: str, query: str, is_id: bool, limit: int) -> list[dict]:
    search = f"%{query}%"
    if is_id:
        rows = session.query(Plant).filter(
            Plant.user_id == user_id,
            Plant.id == query,
            Plant.status != "removed",
        ).limit(limit).all()
        if not rows:
            # fall through to ILIKE
            is_id = False
    if not is_id:
        rows = session.query(Plant).filter(
            Plant.user_id == user_id,
            Plant.status != "removed",
            or_(Plant.name.ilike(search), Plant.variety.ilike(search)),
        ).limit(limit).all()

    if not rows:
        return []

    bed_ids = {p.bed_id for p in rows if p.bed_id}
    container_ids = {p.container_id for p in rows if p.container_id}
    bed_names = {
        b.id: b.name
        for b in session.query(Bed).filter(Bed.id.in_(bed_ids), Bed.user_id == user_id).all()
    } if bed_ids else {}
    container_names = {
        c.id: c.name
        for c in session.query(Container).filter(Container.id.in_(container_ids), Container.user_id == user_id).all()
    } if container_ids else {}

    results = []
    for p in rows:
        label = p.name + (f" ({p.variety})" if p.variety else "")
        if p.bed_id and p.bed_id in bed_names:
            loc = bed_names[p.bed_id]
        elif p.container_id and p.container_id in container_names:
            loc = container_names[p.container_id]
        else:
            loc = None
        secondary = (f"{loc} · " if loc else "") + p.status
        results.append({
            "subject_type": "plant",
            "subject_id": p.id,
            "label": label,
            "secondary_label": secondary,
            "summary": _last_care_summary(p),
        })
    return results


def _search_beds(session, user_id: str, query: str, is_id: bool, limit: int) -> list[dict]:
    search = f"%{query}%"
    if is_id:
        rows = session.query(Bed).filter(
            Bed.user_id == user_id,
            Bed.id == query,
        ).limit(limit).all()
        if not rows:
            is_id = False
    if not is_id:
        rows = session.query(Bed).filter(
            Bed.user_id == user_id,
            or_(Bed.name.ilike(search), Bed.location.ilike(search)),
        ).limit(limit).all()

    if not rows:
        return []

    bed_ids = [b.id for b in rows]
    plant_counts = dict(
        session.query(Plant.bed_id, func.count(Plant.id))
        .filter(Plant.bed_id.in_(bed_ids), Plant.user_id == user_id, Plant.status != "removed")
        .group_by(Plant.bed_id)
        .all()
    )

    return [
        {
            "subject_type": "bed",
            "subject_id": b.id,
            "label": b.name,
            "secondary_label": b.location or None,
            "summary": f"{plant_counts.get(b.id, 0)} active plant(s)",
        }
        for b in rows
    ]


def _search_containers(session, user_id: str, query: str, is_id: bool, limit: int) -> list[dict]:
    search = f"%{query}%"
    if is_id:
        rows = session.query(Container).filter(
            Container.user_id == user_id,
            Container.id == query,
        ).limit(limit).all()
        if not rows:
            is_id = False
    if not is_id:
        rows = session.query(Container).filter(
            Container.user_id == user_id,
            or_(Container.name.ilike(search), Container.location.ilike(search)),
        ).limit(limit).all()

    if not rows:
        return []

    container_ids = [c.id for c in rows]
    plant_counts = dict(
        session.query(Plant.container_id, func.count(Plant.id))
        .filter(Plant.container_id.in_(container_ids), Plant.user_id == user_id, Plant.status != "removed")
        .group_by(Plant.container_id)
        .all()
    )

    return [
        {
            "subject_type": "container",
            "subject_id": c.id,
            "label": c.name,
            "secondary_label": " · ".join(filter(None, [c.container_type, c.location])) or None,
            "summary": f"{plant_counts.get(c.id, 0)} active plant(s)",
        }
        for c in rows
    ]


def _search_tasks(session, user_id: str, query: str, is_id: bool, limit: int) -> list[dict]:
    user_pids = {
        pid for (pid,) in session.query(GardeningProject.id)
        .filter(GardeningProject.user_id == user_id)
        .all()
    }
    if not user_pids:
        return []

    excluded = {"done", "superseded"}
    search = f"%{query}%"

    if is_id:
        rows = session.query(Task).filter(
            Task.project_id.in_(user_pids),
            Task.id == query,
            Task.status.notin_(excluded),
        ).limit(limit).all()
        if not rows:
            is_id = False
    if not is_id:
        rows = session.query(Task).filter(
            Task.project_id.in_(user_pids),
            Task.status.notin_(excluded),
            Task.title.ilike(search),
        ).limit(limit).all()

    if not rows:
        return []

    project_names = {
        p.id: p.name
        for p in session.query(GardeningProject)
        .filter(GardeningProject.id.in_({t.project_id for t in rows}))
        .all()
    }

    return [
        {
            "subject_type": "task",
            "subject_id": t.id,
            "label": t.title,
            "secondary_label": " · ".join(filter(None, [
                project_names.get(t.project_id),
                t.status,
            ])) or None,
            "summary": _due_summary(t),
        }
        for t in rows
    ]


def _search_projects(session, user_id: str, query: str, is_id: bool, limit: int) -> list[dict]:
    search = f"%{query}%"
    if is_id:
        rows = session.query(GardeningProject).filter(
            GardeningProject.user_id == user_id,
            GardeningProject.id == query,
            GardeningProject.status != "complete",
        ).limit(limit).all()
        if not rows:
            is_id = False
    if not is_id:
        rows = session.query(GardeningProject).filter(
            GardeningProject.user_id == user_id,
            GardeningProject.status != "complete",
            GardeningProject.name.ilike(search),
        ).limit(limit).all()

    if not rows:
        return []

    project_ids = [p.id for p in rows]
    open_task_counts = dict(
        session.query(Task.project_id, func.count(Task.id))
        .filter(
            Task.project_id.in_(project_ids),
            Task.status.notin_({"done", "superseded", "skipped"}),
        )
        .group_by(Task.project_id)
        .all()
    )

    return [
        {
            "subject_type": "project",
            "subject_id": p.id,
            "label": p.name,
            "secondary_label": p.status,
            "summary": f"{open_task_counts.get(p.id, 0)} open task(s)",
        }
        for p in rows
    ]


def _search_incidents(session, user_id: str, query: str, is_id: bool, limit: int) -> list[dict]:
    search = f"%{query}%"
    base_filter = IncidentReport.user_id == user_id

    if is_id:
        rows = session.query(IncidentReport).filter(
            base_filter,
            IncidentReport.id == query,
            IncidentReport.status != "resolved",
        ).limit(limit).all()
        if not rows:
            is_id = False
    if not is_id:
        rows = session.query(IncidentReport).filter(
            base_filter,
            IncidentReport.status != "resolved",
            or_(
                IncidentReport.incident_type.ilike(search),
                IncidentReport.summary.ilike(search),
            ),
        ).limit(limit).all()

    if not rows:
        return []

    incident_ids = [i.id for i in rows]
    first_subjects: dict[str, str] = {}
    for s in session.query(IncidentSubject).filter(
        IncidentSubject.incident_id.in_(incident_ids)
    ).all():
        if s.incident_id not in first_subjects:
            first_subjects[s.incident_id] = f"{s.subject_type} {s.subject_id}"

    return [
        {
            "subject_type": "incident",
            "subject_id": i.id,
            "label": f"{i.incident_type}: {_truncate(i.summary)}",
            "secondary_label": " · ".join(filter(None, [i.severity, i.status])) or None,
            "summary": first_subjects.get(i.id),
        }
        for i in rows
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_TYPE_HANDLERS = {
    "plant": _search_plants,
    "bed": _search_beds,
    "container": _search_containers,
    "task": _search_tasks,
    "project": _search_projects,
    "incident": _search_incidents,
}


def search_entities(
    session,
    user_id: str,
    query: str,
    types: Optional[list[str]] = None,
    limit_per_type: int = 5,
) -> dict:
    """Search across garden entities and return structured results.

    Args:
        session: SQLAlchemy session.
        user_id: Owning user.
        query: Search string. A valid UUID triggers an exact ID lookup first.
        types: Entity types to search. Defaults to all six types.
        limit_per_type: Max results per type (capped at 20).

    Returns:
        {"results": [...], "by_type": {type: count, ...}}
    """
    if not query or not query.strip():
        raise ValueError("query must not be empty")

    limit_per_type = min(max(1, limit_per_type), 20)
    requested = list(types) if types else list(ALL_TYPES)
    unknown = set(requested) - set(ALL_TYPES)
    if unknown:
        raise ValueError(f"unknown entity type(s): {', '.join(sorted(unknown))}")

    is_id = _is_uuid(query.strip())
    results: list[dict] = []
    by_type: dict[str, int] = {t: 0 for t in ALL_TYPES}

    for entity_type in requested:
        handler = _TYPE_HANDLERS[entity_type]
        type_results = handler(session, user_id, query.strip(), is_id, limit_per_type)
        results.extend(type_results)
        by_type[entity_type] = len(type_results)

    return {"results": results, "by_type": by_type}
