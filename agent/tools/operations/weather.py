from __future__ import annotations

from typing import Optional

from langchain.tools import tool

from agent.weather import (
    approve_weather_task_changes as approve_weather_task_changes_data,
    draft_weather_task_changes as draft_weather_task_changes_data,
    evaluate_weather_task_impacts,
    get_latest_weather_snapshot as get_latest_weather_snapshot_data,
    refresh_weather_snapshot as refresh_weather_snapshot_data,
)
from db.database import SessionLocal


@tool
def refresh_weather_snapshot() -> str:
    """Refresh the latest persisted weather forecast snapshot from Open-Meteo."""
    session = SessionLocal()
    try:
        snapshot = refresh_weather_snapshot_data(session)
        session.commit()
        return (
            f"Weather refreshed for {snapshot.location_label}.\n"
            f"- Forecast window: {snapshot.forecast_start_date.date().isoformat()} to {snapshot.forecast_end_date.date().isoformat()}\n"
            f"- Alerts: {snapshot.alerts_summary}"
        )
    except Exception as e:
        session.rollback()
        return f"Failed to refresh weather snapshot: {str(e)}"
    finally:
        session.close()


@tool
def get_latest_weather_snapshot() -> str:
    """Show the latest weather snapshot used for triage and weather-aware task recommendations."""
    session = SessionLocal()
    try:
        snapshot = get_latest_weather_snapshot_data(session)
        if not snapshot:
            return "No weather snapshot found."
        return (
            f"Latest weather snapshot for {snapshot.location_label}:\n"
            f"- Generated: {snapshot.created_at.isoformat()}\n"
            f"- Conditions: {snapshot.conditions_summary}\n"
            f"- Alerts: {snapshot.alerts_summary}"
        )
    except Exception as e:
        return f"Failed to load weather snapshot: {str(e)}"
    finally:
        session.close()


@tool
def list_weather_impacted_tasks(project_id: Optional[str] = None) -> str:
    """List active tasks that are materially affected by the latest weather snapshot."""
    session = SessionLocal()
    try:
        impacts = evaluate_weather_task_impacts(session, project_id=project_id)
        if not impacts:
            return "No weather-impacted tasks found."
        lines = ["Weather-impacted tasks:", ""]
        for impact in impacts:
            lines.append(f"- {impact['task_title']} | {impact['impact_type']} on {impact['impact_date']} | {impact['summary']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to evaluate weather impacts: {str(e)}"
    finally:
        session.close()


@tool
def draft_weather_task_changes(project_id: Optional[str] = None) -> str:
    """Draft approval-gated weather-aware task changes without mutating tasks yet."""
    session = SessionLocal()
    try:
        change_set = draft_weather_task_changes_data(session, project_id=project_id)
        session.commit()
        return (
            f"Drafted weather task changes.\n"
            f"- Change set: {change_set.id}\n"
            f"- Status: {change_set.status}\n"
            f"- Summary: {change_set.summary}"
        )
    except Exception as e:
        session.rollback()
        return f"Failed to draft weather task changes: {str(e)}"
    finally:
        session.close()


@tool
def approve_weather_task_changes(change_set_id: str) -> str:
    """Apply a previously drafted weather-aware task change set."""
    session = SessionLocal()
    try:
        change_set = approve_weather_task_changes_data(session, change_set_id)
        session.commit()
        return f"Approved weather task changes for change set {change_set.id}."
    except Exception as e:
        session.rollback()
        return f"Failed to approve weather task changes: {str(e)}"
    finally:
        session.close()
