from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db.models import GardeningProject


SESSION_CONTEXT_FIELDS = (
    "available_minutes",
    "energy_level",
    "focus_project_id",
    "preferred_location_type",
    "open_to_outdoor_work",
    "wants_quick_wins",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _serialize_dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _focus_label(session, user_id: str, focus_project_id: str | None) -> str | None:
    if not focus_project_id:
        return None
    project = (
        session.query(GardeningProject)
        .filter(GardeningProject.id == focus_project_id, GardeningProject.user_id == user_id)
        .first()
    )
    return project.name if project else None


def empty_session_context_view() -> dict[str, Any]:
    return {
        "available_minutes": None,
        "energy_level": None,
        "focus_project_id": None,
        "focus_label": None,
        "preferred_location_type": None,
        "open_to_outdoor_work": None,
        "wants_quick_wins": None,
        "source": "unset",
        "updated_at": None,
    }


def session_context_to_view_data(session, user_id: str, context: dict[str, Any] | None) -> dict[str, Any]:
    if not context:
        return empty_session_context_view()

    data = {
        "available_minutes": context.get("available_minutes"),
        "energy_level": context.get("energy_level"),
        "focus_project_id": context.get("focus_project_id"),
        "focus_label": _focus_label(session, user_id, context.get("focus_project_id")),
        "preferred_location_type": context.get("preferred_location_type"),
        "open_to_outdoor_work": context.get("open_to_outdoor_work"),
        "wants_quick_wins": context.get("wants_quick_wins"),
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
    inferred: dict[str, Any],
    stored: dict[str, Any] | None,
) -> dict[str, Any]:
    if not stored:
        return inferred

    merged = dict(inferred)
    for field in SESSION_CONTEXT_FIELDS:
        if field in stored:
            merged[field] = stored.get(field)
    return merged


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
            next_context[field] = value

    next_context["source"] = "user"
    next_context["updated_at"] = _serialize_dt(now or _utc_now())
    return next_context
