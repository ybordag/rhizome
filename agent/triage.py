from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from agent.activity_log import record_create_event
from agent.temporal import DEFAULT_TIMEZONE, build_temporal_context, infer_session_context
from agent.tracker import build_due_task_view, compute_task_urgency
from agent.weather import evaluate_weather_task_impacts, get_latest_weather_snapshot
from db.models import Task, TriageSnapshot


TRIAGE_SECTIONS = ("Urgent", "Routine", "Project Work")


def _task_matches_project_focus(task: Task, focus_project_id: Optional[str]) -> bool:
    return not focus_project_id or task.project_id == focus_project_id


def _task_matches_location_preference(task: Task, preferred_location_type: Optional[str]) -> bool:
    if not preferred_location_type:
        return True
    linked = task.linked_subjects or []
    return any(subject.get("subject_type") == preferred_location_type for subject in linked)


def _task_matches_effort(task: Task, available_minutes: Optional[int], energy_level: str, wants_quick_wins: bool) -> bool:
    if available_minutes is not None and task.estimated_minutes and task.estimated_minutes > max(available_minutes, 1):
        return False
    if energy_level == "low" and task.estimated_minutes and task.estimated_minutes > 45:
        return False
    if wants_quick_wins and task.estimated_minutes and task.estimated_minutes > 30:
        return False
    return True


def _weather_impacts_by_task(impacts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for impact in impacts:
        grouped.setdefault(impact["task_id"], []).append(impact)
    return grouped


def _triage_section_for_task(task: Task, urgency: str, impacts: list[dict[str, Any]]) -> str:
    title = task.title.lower()
    if impacts or urgency in {"blocker", "time_sensitive"} or any(term in title for term in ("treat", "spray", "weed", "protect")):
        return "Urgent"
    if task.series_id or task.type == "maintenance" or any(term in title for term in ("water", "inspect", "fertiliz", "prune")):
        return "Routine"
    return "Project Work"


def _sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    urgency_order = {"blocker": 0, "time_sensitive": 1, "scheduled": 2, "backlog": 3}
    task = row["task"]
    return (
        urgency_order.get(row["urgency"], 4),
        task.estimated_minutes or 0,
        task.title.lower(),
    )


def build_triage_snapshot(
    session,
    *,
    opener: str,
    timezone: str = DEFAULT_TIMEZONE,
    days_ahead: int = 7,
    now: Optional[datetime] = None,
) -> TriageSnapshot:
    temporal_context = build_temporal_context(session, timezone=timezone, now=now, days_ahead=days_ahead)
    session_context = infer_session_context(session, opener, timezone=timezone)
    weather_snapshot = get_latest_weather_snapshot(session)
    weather_impacts = evaluate_weather_task_impacts(session, weather_snapshot=weather_snapshot)
    impacts_by_task = _weather_impacts_by_task(weather_impacts)

    rows = build_due_task_view(session, days_ahead=days_ahead, now=now)
    filtered_rows: list[dict[str, Any]] = []
    for row in rows:
        task = row["task"]
        if not _task_matches_project_focus(task, session_context.get("focus_project_id")):
            continue
        if not _task_matches_location_preference(task, session_context.get("preferred_location_type")):
            continue
        if row["urgency"] not in {"blocker", "time_sensitive"} and not _task_matches_effort(
            task,
            session_context.get("available_minutes"),
            session_context.get("energy_level", "medium"),
            session_context.get("wants_quick_wins", False),
        ):
            continue
        filtered_rows.append(row)

    if not filtered_rows:
        filtered_rows = rows[:]

    filtered_rows.sort(key=_sort_key)
    urgent_ids: list[str] = []
    routine_ids: list[str] = []
    project_ids: list[str] = []
    recommended_ids: list[str] = []
    reasoning_lines: list[str] = []

    for row in filtered_rows:
        task = row["task"]
        urgency = compute_task_urgency(task, now or datetime.utcnow())
        section = _triage_section_for_task(task, urgency, impacts_by_task.get(task.id, []))
        recommended_ids.append(task.id)
        if section == "Urgent":
            urgent_ids.append(task.id)
        elif section == "Routine":
            routine_ids.append(task.id)
        else:
            project_ids.append(task.id)

        impact_labels = ", ".join(impact["impact_type"] for impact in impacts_by_task.get(task.id, []))
        reason = f"{task.title} is {urgency}"
        if impact_labels:
            reason += f" and weather-impacted ({impact_labels})"
        reasoning_lines.append(reason + ".")

    focus_summary = []
    if session_context.get("available_minutes") is not None:
        focus_summary.append(f"{session_context['available_minutes']} minutes available")
    focus_summary.append(f"energy={session_context.get('energy_level', 'medium')}")
    if session_context.get("focus_project_id"):
        focus_summary.append(f"focused on project {session_context['focus_project_id']}")

    snapshot = TriageSnapshot(
        timezone=timezone,
        session_context=session_context,
        temporal_context=temporal_context,
        weather_snapshot_id=weather_snapshot.id if weather_snapshot else None,
        recommended_task_ids=recommended_ids[:9],
        urgent_task_ids=urgent_ids[:5],
        routine_task_ids=routine_ids[:5],
        project_task_ids=project_ids[:5],
        reasoning_summary=" ".join(reasoning_lines[:6]) or "No due work found; focus on lightweight garden check-ins.",
        user_focus_summary=", ".join(focus_summary),
        notes="Generated at session start.",
    )
    session.add(snapshot)
    session.flush()
    record_create_event(
        session,
        event_type="triage_snapshot_created",
        category="triage",
        summary="Generated a daily triage snapshot.",
        obj=snapshot,
        metadata={"recommended_count": len(snapshot.recommended_task_ids)},
        subjects=[{"subject_type": "triage_snapshot", "subject_id": snapshot.id, "role": "primary"}],
    )
    return snapshot


def format_triage_snapshot(session, snapshot: TriageSnapshot) -> str:
    tasks = {
        task.id: task
        for task in session.query(Task).filter(Task.id.in_(snapshot.recommended_task_ids or [""])).all()
    }

    def lines_for(ids: list[str]) -> list[str]:
        lines = []
        for task_id in ids:
            task = tasks.get(task_id)
            if not task:
                continue
            lines.append(f"- {task.title} ({task.status}, {task.estimated_minutes} min)")
        return lines or ["- none"]

    sections = [
        "Daily triage:",
        "",
        "Urgent:",
        *lines_for(snapshot.urgent_task_ids or []),
        "",
        "Routine:",
        *lines_for(snapshot.routine_task_ids or []),
        "",
        "Project Work:",
        *lines_for(snapshot.project_task_ids or []),
        "",
        f"Why: {snapshot.reasoning_summary}",
    ]
    if snapshot.user_focus_summary:
        sections.append(f"Context: {snapshot.user_focus_summary}")
    return "\n".join(sections)
