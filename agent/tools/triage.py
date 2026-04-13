from __future__ import annotations

from typing import Optional

from langchain.tools import tool

from agent.temporal import DEFAULT_TIMEZONE
from agent.triage import build_triage_snapshot, format_triage_snapshot
from db.database import SessionLocal
from db.models import TriageSnapshot


@tool
def run_daily_triage(opener: str, timezone: str = DEFAULT_TIMEZONE) -> str:
    """Run a daily triage pass based on the user's opening message, time context, and latest weather."""
    session = SessionLocal()
    try:
        snapshot = build_triage_snapshot(session, opener=opener, timezone=timezone)
        session.commit()
        return format_triage_snapshot(session, snapshot)
    except Exception as e:
        session.rollback()
        return f"Failed to run daily triage: {str(e)}"
    finally:
        session.close()


@tool
def get_latest_triage_snapshot() -> str:
    """Show the latest persisted triage snapshot."""
    session = SessionLocal()
    try:
        snapshot = session.query(TriageSnapshot).order_by(TriageSnapshot.created_at.desc()).first()
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
        snapshot = session.query(TriageSnapshot).order_by(TriageSnapshot.created_at.desc()).first()
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
