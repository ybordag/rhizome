from __future__ import annotations

from typing import Optional

from langchain.tools import tool

from db.database import SessionLocal
from db.models import ActivityEvent, ActivitySubject, Bed, Container, Plant


def _load_subject(session, subject_type: str, subject_id: str):
    model = {"plant": Plant, "container": Container, "bed": Bed}.get(subject_type)
    if not model:
        raise ValueError(f"Unsupported subject_type '{subject_type}'.")
    subject = session.query(model).filter(model.id == subject_id).first()
    if not subject:
        raise ValueError(f"No {subject_type} found with id {subject_id}.")
    return subject


@tool
def get_current_care_state(subject_type: str, subject_id: str) -> str:
    """Show the current care-state timestamps and notes for a plant, container, or bed."""
    session = SessionLocal()
    try:
        subject = _load_subject(session, subject_type, subject_id)
        lines = [f"Current care state for {subject_type} {subject_id}:", ""]
        for field in (
            "last_watered_at",
            "last_fertilized_at",
            "last_amended_at",
            "last_inspected_at",
            "last_treated_at",
            "last_pruned_at",
        ):
            if hasattr(subject, field):
                value = getattr(subject, field)
                lines.append(f"- {field}: {value.isoformat() if value else 'not set'}")
        lines.append(f"- care_state_notes: {getattr(subject, 'care_state_notes', None) or 'none'}")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to load current care state: {str(e)}"
    finally:
        session.close()


@tool
def get_recent_care_history(subject_type: str, subject_id: str, limit: int = 20) -> str:
    """Show recent semantic care events for a plant, container, or bed."""
    session = SessionLocal()
    try:
        if limit < 1:
            return "limit must be at least 1."
        events = (
            session.query(ActivityEvent)
            .join(ActivitySubject, ActivityEvent.id == ActivitySubject.event_id)
            .filter(
                ActivitySubject.subject_type == subject_type,
                ActivitySubject.subject_id == subject_id,
                ActivityEvent.event_type.in_(
                    [
                        "plant_watered",
                        "container_watered",
                        "bed_watered",
                        "plant_fertilized",
                        "container_fertilized",
                        "bed_fertilized",
                        "bed_amended",
                        "container_amended",
                        "plant_pruned",
                        "plant_inspected",
                        "container_inspected",
                        "bed_inspected",
                        "plant_treated",
                        "container_treated",
                        "bed_treated",
                    ]
                ),
            )
            .order_by(ActivityEvent.created_at.desc())
            .limit(limit)
            .all()
        )
        if not events:
            return "No recent care history found."
        lines = [f"Recent care history for {subject_type} {subject_id}:", ""]
        for event in events:
            lines.append(f"- {event.created_at.date().isoformat()} | {event.event_type} | {event.summary}")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to load care history: {str(e)}"
    finally:
        session.close()
