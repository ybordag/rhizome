from __future__ import annotations

import uuid
from typing import Optional

from langchain.tools import tool

from agent.core.temporal import DEFAULT_TIMEZONE
from agent.domain.notifications import push_event
from agent.domain.triage import build_triage_snapshot, format_triage_snapshot, get_latest_triage_snapshot as get_latest_triage_snapshot_data
from db.database import SessionLocal, current_user_id


@tool
def run_daily_triage(opener: str, timezone: str = DEFAULT_TIMEZONE) -> str:
    """Run a daily triage pass based on the user's opening message, time context, and latest weather."""
    user_id = current_user_id.get()
    job_id = f"triage_{uuid.uuid4().hex[:8]}"
    push_event(user_id, {"type": "job_started", "job_id": job_id, "title": "Daily triage"})

    def sink(step: str, status: str) -> None:
        push_event(user_id, {"type": "job_step", "job_id": job_id, "step": step, "status": status})

    session = SessionLocal()
    try:
        snapshot = build_triage_snapshot(session, opener=opener, timezone=timezone, event_sink=sink)
        session.commit()
        result = format_triage_snapshot(session, snapshot)
        push_event(user_id, {"type": "job_complete", "job_id": job_id, "title": "Daily triage", "summary": result[:200]})
        return result
    except Exception as e:
        session.rollback()
        error = str(e)
        push_event(user_id, {"type": "job_failed", "job_id": job_id, "title": "Daily triage", "error": error})
        return f"Failed to run daily triage: {error}"
    finally:
        session.close()


@tool
def get_latest_triage_snapshot() -> str:
    """Show the latest persisted triage snapshot."""
    session = SessionLocal()
    try:
        snapshot = get_latest_triage_snapshot_data(session)
        if not snapshot:
            return "No triage snapshot found."
        return format_triage_snapshot(session, snapshot)
    except Exception as e:
        return f"Failed to load triage snapshot: {str(e)}"
    finally:
        session.close()


@tool
def list_triage_recommendations(limit: int = 9) -> str:
    """List the task recommendations from the latest triage snapshot for frontend/API use."""
    session = SessionLocal()
    try:
        snapshot = get_latest_triage_snapshot_data(session)
        if not snapshot:
            return "No triage snapshot found."
        task_ids = (snapshot.recommended_task_ids or [])[:limit]
        if not task_ids:
            return "The latest triage snapshot has no task recommendations."
        lines = ["Latest triage recommendations:", ""]
        for task_id in task_ids:
            lines.append(f"- {task_id}")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list triage recommendations: {str(e)}"
    finally:
        session.close()
