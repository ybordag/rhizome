"""
Activity history tools for querying object and project timelines.
"""

from datetime import datetime
from typing import Optional

from langchain.tools import tool

from agent.domain.activity_log import (
    format_activity_feed,
    get_activity_for_subject,
    get_activity_for_subject_in_project,
    list_recent_activity_entries,
)
from db.database import SessionLocal
from db.models import ActivitySubject


def _parse_timestamp(value: Optional[str], field_name: str) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name} '{value}'. Use ISO format YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.") from exc


def _get_subject_activity(
    subject_type: str,
    subject_id: str,
    limit: int,
    event_type: Optional[str],
) -> str:
    session = SessionLocal()
    try:
        events = get_activity_for_subject(
            session,
            subject_type=subject_type,
            subject_id=subject_id,
            limit=limit,
            event_type=event_type,
        )
        title = f"Recent activity for {subject_type} {subject_id}:"
        return format_activity_feed(session, title=title, events=events)
    except Exception as e:
        print(f"[DEBUG] Failed to get {subject_type} activity: {e}")
        return f"Failed to get {subject_type} activity: {str(e)}"
    finally:
        session.close()


@tool
def get_project_activity(
    project_id: str,
    limit: int = 20,
    event_type: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """Show recent activity for a specific project."""
    session = SessionLocal()
    try:
        events = list_recent_activity_entries(
            session,
            project_id=project_id,
            event_type=event_type,
            category=category,
            limit=limit,
        )
        title = f"Recent activity for project {project_id}:"
        return format_activity_feed(session, title=title, events=events)
    except Exception as e:
        print(f"[DEBUG] Failed to get project activity: {e}")
        return f"Failed to get project activity: {str(e)}"
    finally:
        session.close()


@tool
def list_project_activity(
    project_id: str,
    category: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[str] = None,
    before_timestamp: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    Full cross-object activity timeline for a project with filtering and pagination.
    Returns all events linked to the project — tasks, plants, planning, incidents, care, weather.
    Use since/before_timestamp (ISO date strings) to page through history.
    category filters by domain: 'task', 'project', 'plant', 'incident', 'interaction', 'care', 'weather'.
    """
    session = SessionLocal()
    try:
        since_dt = _parse_timestamp(since, "since")
        before_dt = _parse_timestamp(before_timestamp, "before_timestamp")
        events = get_activity_for_subject_in_project(
            session,
            project_id=project_id,
            category=category,
            event_type=event_type,
            since=since_dt,
            before_timestamp=before_dt,
            limit=limit,
        )
        title = f"Activity timeline for project {project_id}:"
        if category:
            title += f" (category: {category})"
        return format_activity_feed(session, title=title, events=events)
    except Exception as e:
        print(f"[DEBUG] Failed to list project activity: {e}")
        return f"Failed to list project activity: {str(e)}"
    finally:
        session.close()


@tool
def get_plant_activity(plant_id: str, limit: int = 20, event_type: Optional[str] = None) -> str:
    """Show recent activity for a specific plant."""
    return _get_subject_activity("plant", plant_id, limit, event_type)


@tool
def get_bed_activity(bed_id: str, limit: int = 20, event_type: Optional[str] = None) -> str:
    """Show recent activity for a specific bed."""
    return _get_subject_activity("bed", bed_id, limit, event_type)


@tool
def get_container_activity(container_id: str, limit: int = 20, event_type: Optional[str] = None) -> str:
    """Show recent activity for a specific container."""
    return _get_subject_activity("container", container_id, limit, event_type)


@tool
def get_batch_activity(batch_id: str, limit: int = 20, event_type: Optional[str] = None) -> str:
    """Show recent activity for a specific batch."""
    return _get_subject_activity("batch", batch_id, limit, event_type)


@tool
def get_task_activity(task_id: str, limit: int = 20) -> str:
    """Show the full history for a specific task — creation, status changes, care updates."""
    return _get_subject_activity("task", task_id, limit, None)


@tool
def get_incident_activity(incident_id: str, limit: int = 20) -> str:
    """Show the full history for a specific incident — reporting, treatment drafting, resolution."""
    return _get_subject_activity("incident_report", incident_id, limit, None)


@tool
def list_recent_activity(
    project_id: Optional[str] = None,
    subject_type: Optional[str] = None,
    event_type: Optional[str] = None,
    category: Optional[str] = None,
    since: Optional[str] = None,
    before_timestamp: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    List recent activity globally or scoped to a project/entity type.
    Supports filtering by category, event_type, and ISO date range (since/before_timestamp).
    Use before_timestamp from the last event in a page to fetch the next page.
    """
    session = SessionLocal()
    try:
        since_dt = _parse_timestamp(since, "since")
        before_dt = _parse_timestamp(before_timestamp, "before_timestamp")
        events = list_recent_activity_entries(
            session,
            project_id=project_id,
            subject_type=subject_type,
            event_type=event_type,
            category=category,
            since=since_dt,
            before_timestamp=before_dt,
            limit=limit,
        )
        if project_id:
            title = f"Recent activity for project {project_id}:"
        elif subject_type:
            title = f"Recent activity for {subject_type} objects:"
        else:
            title = "Recent activity:"
        return format_activity_feed(session, title=title, events=events)
    except Exception as e:
        print(f"[DEBUG] Failed to list recent activity: {e}")
        return f"Failed to list recent activity: {str(e)}"
    finally:
        session.close()
