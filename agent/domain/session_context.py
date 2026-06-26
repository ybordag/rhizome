from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db.models import Bed, Container, GardeningProject, IncidentReport, Plant, PlantBatch, Task


SESSION_CONTEXT_FIELDS = (
    "time_text",
    "energy_text",
    "focus_text",
    "focus_context",
)


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
    if subject_type == "plant":
        row = session.query(Plant).filter(Plant.id == subject_id, Plant.user_id == user_id).first()
        if row:
            return f"{row.name} ({row.variety})" if row.variety else row.name
    elif subject_type == "batch":
        row = session.query(PlantBatch).filter(PlantBatch.id == subject_id, PlantBatch.user_id == user_id).first()
        if row:
            return row.name
    elif subject_type == "bed":
        row = session.query(Bed).filter(Bed.id == subject_id, Bed.user_id == user_id).first()
        if row:
            return row.name
    elif subject_type == "container":
        row = session.query(Container).filter(Container.id == subject_id, Container.user_id == user_id).first()
        if row:
            return row.name
    elif subject_type == "project":
        row = (
            session.query(GardeningProject)
            .filter(GardeningProject.id == subject_id, GardeningProject.user_id == user_id)
            .first()
        )
        if row:
            return row.name
    elif subject_type == "task":
        row = (
            session.query(Task)
            .join(GardeningProject, Task.project_id == GardeningProject.id)
            .filter(Task.id == subject_id, GardeningProject.user_id == user_id)
            .first()
        )
        if row:
            return row.title
    elif subject_type == "incident":
        row = (
            session.query(IncidentReport)
            .filter(IncidentReport.id == subject_id, IncidentReport.user_id == user_id)
            .first()
        )
        if row:
            return row.summary
    return None


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

    focus_items = _focus_context_to_view(session, user_id, context.get("focus_context"))
    if focus_items:
        lines.append("Focus objects:")
        for item in focus_items:
            label = item.get("label") or item["subject_id"]
            lines.append(f"- {item['subject_type']}: {label} [id: {item['subject_id']}]")

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
