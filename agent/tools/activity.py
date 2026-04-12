"""
Activity history tools for querying object and project timelines.
"""

from typing import Optional

from langchain.tools import tool

from agent.activity_log import (
    format_activity_feed,
    get_activity_for_subject,
    list_recent_activity_entries,
)
from db.database import SessionLocal


def _get_subject_activity(subject_type: str, subject_id: str, limit: int, event_type: Optional[str]) -> str:
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
def get_project_activity(project_id: str, limit: int = 20, event_type: Optional[str] = None) -> str:
    """Show recent activity for a specific project."""
    session = SessionLocal()
    try:
        events = list_recent_activity_entries(session, project_id=project_id, limit=limit)
        if event_type:
            events = [event for event in events if event.event_type == event_type]
        title = f"Recent activity for project {project_id}:"
        return format_activity_feed(session, title=title, events=events)
    except Exception as e:
        print(f"[DEBUG] Failed to get project activity: {e}")
        return f"Failed to get project activity: {str(e)}"
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
def list_recent_activity(
    project_id: Optional[str] = None,
    subject_type: Optional[str] = None,
    limit: int = 50,
) -> str:
    """List recent activity globally or for a project/entity type."""
    session = SessionLocal()
    try:
        events = list_recent_activity_entries(
            session,
            project_id=project_id,
            subject_type=subject_type,
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
