from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.activity_log import DEFAULT_ACTOR_LABEL, DEFAULT_ACTOR_TYPE, record_activity_event
from db.models import Bed, Container, Plant, ProjectPlant, Task, TaskSeries


CARE_ACTIONS = {
    "water": {
        "plant": ("plant_watered", "last_watered_at"),
        "container": ("container_watered", "last_watered_at"),
        "bed": ("bed_watered", "last_watered_at"),
    },
    "fertilize": {
        "plant": ("plant_fertilized", "last_fertilized_at"),
        "container": ("container_fertilized", "last_fertilized_at"),
        "bed": ("bed_fertilized", "last_fertilized_at"),
    },
    "amend": {
        "container": ("container_amended", "last_amended_at"),
        "bed": ("bed_amended", "last_amended_at"),
    },
    "inspect": {
        "plant": ("plant_inspected", "last_inspected_at"),
        "container": ("container_inspected", "last_inspected_at"),
        "bed": ("bed_inspected", "last_inspected_at"),
    },
    "prune": {
        "plant": ("plant_pruned", "last_pruned_at"),
    },
    "treat": {
        "plant": ("plant_treated", "last_treated_at"),
        "container": ("container_treated", "last_inspected_at"),
        "bed": ("bed_treated", "last_inspected_at"),
    },
}


def infer_care_action(task: Task) -> str | None:
    haystack = f"{task.generator_key} {task.title} {task.description or ''}".lower()
    if "water" in haystack:
        return "water"
    if "fertiliz" in haystack or "feed" in haystack:
        return "fertilize"
    if "amend" in haystack or "compost" in haystack or "mulch" in haystack:
        return "amend"
    if "inspect" in haystack:
        return "inspect"
    if "prun" in haystack or "sucker" in haystack:
        return "prune"
    if any(term in haystack for term in ("treat", "spray", "remove pests", "weed", "blight", "aphid")):
        return "treat"
    return None


def _load_series_subjects(session, task: Task) -> list[dict[str, Any]]:
    if not task.series_id:
        return []
    series = session.query(TaskSeries).filter(TaskSeries.id == task.series_id).first()
    return list(series.linked_subjects or []) if series else []


def _resolve_subjects(session, task: Task) -> list[tuple[str, Any]]:
    resolved: list[tuple[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    linked_subjects = list(task.linked_subjects or []) + _load_series_subjects(session, task)
    for subject in linked_subjects:
        subject_type = subject.get("subject_type")
        subject_id = subject.get("subject_id")
        if not subject_type or not subject_id:
            continue
        if (subject_type, subject_id) in seen:
            continue
        model = {"plant": Plant, "container": Container, "bed": Bed}.get(subject_type)
        if not model:
            continue
        obj = session.query(model).filter(model.id == subject_id).first()
        if obj:
            seen.add((subject_type, subject_id))
            resolved.append((subject_type, obj))

    if any(subject_type == "plant" for subject_type, _ in resolved):
        return resolved

    project_plants = (
        session.query(Plant)
        .join(ProjectPlant, Plant.id == ProjectPlant.plant_id)
        .filter(ProjectPlant.project_id == task.project_id, ProjectPlant.removed_at.is_(None))
        .all()
    )
    title = task.title.lower()
    for plant in project_plants:
        if plant.name.lower() in title or (plant.variety and plant.variety.lower() in title):
            key = ("plant", plant.id)
            if key not in seen:
                seen.add(key)
                resolved.append(("plant", plant))
            if plant.container_id:
                container = session.query(Container).filter(Container.id == plant.container_id).first()
                if container and ("container", container.id) not in seen:
                    seen.add(("container", container.id))
                    resolved.append(("container", container))
            if plant.bed_id:
                bed = session.query(Bed).filter(Bed.id == plant.bed_id).first()
                if bed and ("bed", bed.id) not in seen:
                    seen.add(("bed", bed.id))
                    resolved.append(("bed", bed))
    return resolved


def apply_task_completion_side_effects(
    session,
    task: Task,
    *,
    completion_event_id: str,
    notes: str | None = None,
) -> list[str]:
    action = infer_care_action(task)
    if not action:
        return []

    resolved = _resolve_subjects(session, task)
    if not resolved:
        return []

    updated: list[str] = []
    mapping = CARE_ACTIONS[action]
    completed_at = task.completed_at or datetime.utcnow()

    for subject_type, obj in resolved:
        if subject_type not in mapping:
            continue
        event_type, field_name = mapping[subject_type]
        setattr(obj, field_name, completed_at)
        existing_note = getattr(obj, "care_state_notes", None)
        note_text = notes or f"Updated from task '{task.title}'."
        setattr(obj, "care_state_notes", f"{existing_note}\n{note_text}".strip() if existing_note else note_text)
        updated.append(f"{subject_type}:{obj.id}")
        record_activity_event(
            session,
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
            event_type=event_type,
            category=subject_type,
            summary=f"{obj.__class__.__name__} care updated via task '{task.title}'.",
            project_id=task.project_id,
            revision_id=task.revision_id,
            caused_by_event_id=completion_event_id,
            metadata={"task_id": task.id, "action": action, "subject_id": obj.id},
            subjects=[
                {"subject_type": "task", "subject_id": task.id, "role": "source"},
                {"subject_type": subject_type, "subject_id": obj.id, "role": "primary"},
            ],
        )
    return updated
