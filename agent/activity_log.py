from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from db.models import (
    ActivityEvent,
    ActivitySubject,
    Bed,
    Container,
    GardeningProject,
    Plant,
    PlantBatch,
    ProjectBrief,
    ProjectExecutionSpec,
    ProjectProposal,
    ProjectRevision,
    Task,
    TaskGenerationRun,
    TaskSeries,
)

DEFAULT_ACTOR_TYPE = "agent"
DEFAULT_ACTOR_LABEL = "rhizome_tool"


SNAPSHOT_FIELDS = {
    GardeningProject: [
        "id",
        "name",
        "goal",
        "status",
        "tray_slots",
        "budget_ceiling",
        "approved_plan",
        "notes",
    ],
    ProjectBrief: [
        "id",
        "project_id",
        "status",
        "goal",
        "desired_outcome",
        "target_start",
        "target_completion",
        "budget_cap",
        "effort_preference",
        "propagation_preference",
        "priority_preferences",
        "notes",
    ],
    ProjectProposal: [
        "id",
        "project_id",
        "brief_id",
        "version",
        "status",
        "title",
        "summary",
        "recommended_approach",
        "selected_locations",
        "selected_plants",
        "material_strategy",
        "propagation_strategy",
        "assumptions",
        "tradeoffs",
        "risks",
        "feasibility_notes",
        "cost_estimate",
        "timeline_estimate",
        "effort_estimate",
        "maintenance_assumptions",
        "resource_assumptions",
        "budget_assumptions",
        "timing_anchors",
    ],
    ProjectRevision: [
        "id",
        "project_id",
        "source_proposal_id",
        "revision_number",
        "status",
        "approved_plan",
        "approved_at",
        "superseded_at",
    ],
    ProjectExecutionSpec: [
        "id",
        "project_id",
        "revision_id",
        "status",
        "selected_plants",
        "selected_locations",
        "propagation_strategy",
        "timing_windows",
        "maintenance_assumptions",
        "resource_assumptions",
        "budget_assumptions",
        "preferred_completion_target",
        "plant_categories",
        "timing_anchors",
    ],
    TaskGenerationRun: [
        "id",
        "project_id",
        "revision_id",
        "run_type",
        "status",
        "source_event_id",
        "summary",
        "run_metadata",
    ],
    Task: [
        "id",
        "project_id",
        "revision_id",
        "generation_run_id",
        "parent_task_id",
        "series_id",
        "source_type",
        "generator_key",
        "title",
        "description",
        "type",
        "status",
        "scheduled_date",
        "earliest_start",
        "window_start",
        "window_end",
        "deadline",
        "completed_at",
        "deferred_until",
        "estimated_minutes",
        "actual_minutes",
        "reversible",
        "what_happens_if_skipped",
        "what_happens_if_delayed",
        "notes",
        "event_anchor_type",
        "event_anchor_subject_type",
        "event_anchor_subject_id",
        "event_anchor_offset_days",
        "is_user_modified",
    ],
    TaskSeries: [
        "id",
        "project_id",
        "revision_id",
        "generation_run_id",
        "parent_task_id",
        "source_type",
        "generator_key",
        "title",
        "description",
        "type",
        "cadence",
        "cadence_days",
        "start_condition",
        "end_condition",
        "linked_subjects",
        "default_estimated_minutes",
        "next_generation_date",
        "active",
    ],
    Bed: [
        "id",
        "name",
        "location",
        "sunlight",
        "soil_type",
        "dimensions_sqft",
        "notes",
    ],
    Container: [
        "id",
        "name",
        "container_type",
        "size_gallons",
        "location",
        "is_mobile",
        "notes",
    ],
    Plant: [
        "id",
        "name",
        "variety",
        "quantity",
        "status",
        "source",
        "container_id",
        "bed_id",
        "batch_id",
        "sow_date",
        "red_cup_date",
        "transplant_date",
        "is_flowering",
        "is_fruiting",
        "fertilizing_schedule",
        "last_fertilized_at",
        "special_instructions",
        "notes",
    ],
    PlantBatch: [
        "id",
        "name",
        "plant_name",
        "variety",
        "project_id",
        "quantity_sown",
        "source",
        "sow_date",
        "supplier",
        "supplier_reference",
        "grow_light",
        "tray",
        "notes",
    ],
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def snapshot_model(obj: Any) -> dict[str, Any]:
    for model_type, fields in SNAPSHOT_FIELDS.items():
        if isinstance(obj, model_type):
            return {
                field: _json_safe(getattr(obj, field))
                for field in fields
            }
    raise ValueError(f"Unsupported model type for activity snapshot: {type(obj)!r}")


def compute_changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    changed = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changed.append(key)
    return changed


def record_activity_event(
    session,
    *,
    actor_type: str,
    actor_label: Optional[str] = None,
    event_type: str,
    category: str,
    summary: str,
    notes: Optional[str] = None,
    project_id: Optional[str] = None,
    caused_by_event_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    revision_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    subjects: Optional[Iterable[dict[str, Any]]] = None,
) -> ActivityEvent:
    event = ActivityEvent(
        actor_type=actor_type,
        actor_label=actor_label,
        event_type=event_type,
        category=category,
        summary=summary,
        notes=notes,
        project_id=project_id,
        caused_by_event_id=caused_by_event_id,
        conversation_id=conversation_id,
        thread_id=thread_id,
        revision_id=revision_id,
        event_metadata=_json_safe(metadata or {}),
    )
    session.add(event)
    session.flush()

    for subject in subjects or []:
        session.add(
            ActivitySubject(
                event_id=event.id,
                subject_type=subject["subject_type"],
                subject_id=subject["subject_id"],
                role=subject.get("role"),
            )
        )

    session.flush()
    return event


def record_create_event(
    session,
    *,
    event_type: str,
    category: str,
    summary: str,
    obj: Any,
    notes: Optional[str] = None,
    project_id: Optional[str] = None,
    caused_by_event_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    revision_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    subjects: Optional[Iterable[dict[str, Any]]] = None,
    actor_type: str = DEFAULT_ACTOR_TYPE,
    actor_label: str = DEFAULT_ACTOR_LABEL,
) -> ActivityEvent:
    payload = dict(metadata or {})
    payload["after"] = snapshot_model(obj)
    return record_activity_event(
        session,
        actor_type=actor_type,
        actor_label=actor_label,
        event_type=event_type,
        category=category,
        summary=summary,
        notes=notes,
        project_id=project_id,
        caused_by_event_id=caused_by_event_id,
        conversation_id=conversation_id,
        thread_id=thread_id,
        revision_id=revision_id,
        metadata=payload,
        subjects=subjects,
    )


def record_update_event(
    session,
    *,
    event_type: str,
    category: str,
    summary: str,
    before: dict[str, Any],
    obj: Any,
    notes: Optional[str] = None,
    project_id: Optional[str] = None,
    caused_by_event_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    revision_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    subjects: Optional[Iterable[dict[str, Any]]] = None,
    actor_type: str = DEFAULT_ACTOR_TYPE,
    actor_label: str = DEFAULT_ACTOR_LABEL,
) -> Optional[ActivityEvent]:
    after = snapshot_model(obj)
    changed_fields = compute_changed_fields(before, after)
    if not changed_fields:
        return None

    payload = dict(metadata or {})
    payload["before"] = before
    payload["after"] = after
    payload["changed_fields"] = changed_fields

    return record_activity_event(
        session,
        actor_type=actor_type,
        actor_label=actor_label,
        event_type=event_type,
        category=category,
        summary=summary,
        notes=notes,
        project_id=project_id,
        caused_by_event_id=caused_by_event_id,
        conversation_id=conversation_id,
        thread_id=thread_id,
        revision_id=revision_id,
        metadata=payload,
        subjects=subjects,
    )


def record_delete_event(
    session,
    *,
    event_type: str,
    category: str,
    summary: str,
    before: dict[str, Any],
    notes: Optional[str] = None,
    project_id: Optional[str] = None,
    caused_by_event_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    revision_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    subjects: Optional[Iterable[dict[str, Any]]] = None,
    actor_type: str = DEFAULT_ACTOR_TYPE,
    actor_label: str = DEFAULT_ACTOR_LABEL,
) -> ActivityEvent:
    payload = dict(metadata or {})
    payload["before"] = before
    payload["changed_fields"] = list(before.keys())
    return record_activity_event(
        session,
        actor_type=actor_type,
        actor_label=actor_label,
        event_type=event_type,
        category=category,
        summary=summary,
        notes=notes,
        project_id=project_id,
        caused_by_event_id=caused_by_event_id,
        conversation_id=conversation_id,
        thread_id=thread_id,
        revision_id=revision_id,
        metadata=payload,
        subjects=subjects,
    )


def get_activity_for_subject(session, *, subject_type: str, subject_id: str, limit: int = 20, event_type: Optional[str] = None):
    query = (
        session.query(ActivityEvent)
        .join(ActivitySubject, ActivityEvent.id == ActivitySubject.event_id)
        .filter(
            ActivitySubject.subject_type == subject_type,
            ActivitySubject.subject_id == subject_id,
        )
    )
    if event_type:
        query = query.filter(ActivityEvent.event_type == event_type)
    return query.order_by(ActivityEvent.created_at.desc()).limit(limit).all()


def list_recent_activity_entries(
    session,
    *,
    project_id: Optional[str] = None,
    subject_type: Optional[str] = None,
    limit: int = 50,
):
    query = session.query(ActivityEvent)
    if project_id:
        query = query.filter(ActivityEvent.project_id == project_id)
    if subject_type:
        query = (
            query.join(ActivitySubject, ActivityEvent.id == ActivitySubject.event_id)
            .filter(ActivitySubject.subject_type == subject_type)
            .distinct()
        )
    return query.order_by(ActivityEvent.created_at.desc()).limit(limit).all()


def format_activity_feed(session, *, title: str, events: list[ActivityEvent]) -> str:
    if not events:
        return f"{title}\n\nNo activity found."

    lines = [title, ""]
    for event in events:
        timestamp = event.created_at.strftime("%B %d, %Y")
        lines.append(f"- {timestamp} | {event.event_type}")
        lines.append(f"  {event.summary}")
        if event.notes:
            lines.append(f"  Notes: {event.notes}")
        subjects = (
            session.query(ActivitySubject)
            .filter(ActivitySubject.event_id == event.id)
            .all()
        )
        affected = [
            f"{subject.subject_type}:{subject.subject_id}"
            for subject in subjects
            if subject.role and subject.role != "primary"
        ]
        if affected:
            lines.append(f"  Affected: {', '.join(affected)}")
    return "\n".join(lines)
