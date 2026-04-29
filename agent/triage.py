from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from typing import Any, Optional

from agent.activity_log import record_create_event
from agent.model import model
from agent.temporal import DEFAULT_TIMEZONE, build_temporal_context, infer_session_context
from agent.tracker import build_due_task_view, compute_task_urgency
from agent.weather import evaluate_weather_task_impacts, get_latest_weather_snapshot
from db.models import Task, TriageSnapshot
from langchain.messages import HumanMessage, SystemMessage


TRIAGE_SECTIONS = ("Urgent", "Routine", "Project Work")
EMERGENCY_TITLE_TERMS = ("treat", "spray", "weed", "protect", "cover", "shield", "respond")
triage_summary_model = model


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
    if (
        task.type == "emergency"
        or (task.generator_key or "").startswith(("weather.", "incident."))
        or any(term in title for term in EMERGENCY_TITLE_TERMS)
    ):
        return "Urgent"
    if task.series_id or task.type == "maintenance" or any(term in title for term in ("water", "inspect", "fertiliz", "prune")):
        return "Routine"
    return "Project Work"


def _visible_triage_sections(snapshot: TriageSnapshot) -> list[tuple[str, list[str]]]:
    sections = [
        ("Urgent", snapshot.urgent_task_ids or []),
        ("Routine", snapshot.routine_task_ids or []),
        ("Project Work", snapshot.project_task_ids or []),
    ]
    visible = [(title, ids) for title, ids in sections if ids]
    if visible:
        return visible
    return [("Routine", snapshot.routine_task_ids or [])]


def _impact_labels(impacts: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    risks = sorted({impact["impact_type"] for impact in impacts if impact.get("impact_kind") == "risk"})
    opportunities = sorted({impact["impact_type"] for impact in impacts if impact.get("impact_kind") == "opportunity"})
    return risks, opportunities


def _sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
    urgency_order = {"blocker": 0, "time_sensitive": 1, "scheduled": 2, "backlog": 3}
    task = row["task"]
    return (
        urgency_order.get(row["urgency"], 4),
        task.estimated_minutes or 0,
        task.title.lower(),
    )


def _deterministic_reasoning_summary(
    rows: list[dict[str, Any]],
    *,
    urgent_ids: list[str],
    routine_ids: list[str],
    project_ids: list[str],
    impacts_by_task: dict[str, list[dict[str, Any]]],
    weather_snapshot,
) -> str:
    weather_bits: list[str] = []
    if weather_snapshot and weather_snapshot.alerts_summary:
        weather_bits.append(weather_snapshot.alerts_summary.strip())
    elif weather_snapshot and weather_snapshot.conditions_summary:
        weather_bits.append(weather_snapshot.conditions_summary.strip())

    top_rows = rows[:4]
    blockers = [row["task"].title for row in top_rows if row["urgency"] == "blocker"]
    time_sensitive = [row["task"].title for row in top_rows if row["urgency"] == "time_sensitive"]
    backlog = [row["task"].title for row in top_rows if row["urgency"] == "backlog"]

    overview_bits: list[str] = []
    if blockers:
        overview_bits.append(f"Main blockers to clear first: {', '.join(blockers[:2])}.")
    if time_sensitive:
        overview_bits.append(f"Keep an eye on {', '.join(time_sensitive[:2])} next.")
    if backlog and not blockers and not time_sensitive:
        overview_bits.append(f"Nothing looks urgent right now; {', '.join(backlog[:2])} can wait if needed.")

    impacted = 0
    for row in rows[:6]:
        if impacts_by_task.get(row["task"].id):
            impacted += 1
    if impacted:
        overview_bits.append(f"{impacted} of the top tasks may shift with the weather window.")

    section_bits = []
    if urgent_ids:
        section_bits.append(f"{len(urgent_ids)} urgent")
    if routine_ids:
        section_bits.append(f"{len(routine_ids)} routine")
    if project_ids:
        section_bits.append(f"{len(project_ids)} project")
    if section_bits:
        overview_bits.append(f"Today’s mix is {', '.join(section_bits)} tasks.")

    return " ".join(weather_bits + overview_bits) or "No due work found; focus on lightweight garden check-ins."


def _task_summary_lines(rows: list[dict[str, Any]], impacts_by_task: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines: list[str] = []
    for row in rows[:6]:
        task = row["task"]
        reason = f"{task.title} is {row['urgency']}"
        risks, opportunities = _impact_labels(impacts_by_task.get(task.id, []))
        if risks:
            reason += f" with weather risks ({', '.join(risks)})"
        if opportunities:
            connector = " and" if risks else " with"
            reason += f"{connector} weather opportunities ({', '.join(opportunities)})"
        lines.append(reason + ".")
    return lines


def _llm_reasoning_summary(
    rows: list[dict[str, Any]],
    *,
    session_context: dict[str, Any],
    weather_snapshot,
    impacts_by_task: dict[str, list[dict[str, Any]]],
    urgent_ids: list[str],
    routine_ids: list[str],
    project_ids: list[str],
) -> str:
    if triage_summary_model is None:
        raise RuntimeError("Triage summary model disabled.")

    weather_alerts = None
    weather_conditions = None
    if weather_snapshot is not None:
        weather_alerts = weather_snapshot.alerts_summary
        weather_conditions = weather_snapshot.conditions_summary

    task_lines = []
    for row in rows[:6]:
        task = row["task"]
        risks, opportunities = _impact_labels(impacts_by_task.get(task.id, []))
        pieces = [f"title={task.title}", f"urgency={row['urgency']}", f"status={task.status}"]
        if task.estimated_minutes is not None:
            pieces.append(f"minutes={task.estimated_minutes}")
        if risks:
            pieces.append(f"weather_risks={', '.join(risks)}")
        if opportunities:
            pieces.append(f"weather_opportunities={', '.join(opportunities)}")
        task_lines.append(" | ".join(pieces))

    prompt = "\n".join(
        [
            "Write a concise triage opener for a gardening assistant.",
            "Goal:",
            "- Start with the upcoming weather if it meaningfully changes what the user should do today.",
            "- Summarize the main work focus in 2-4 sentences.",
            "- Use natural language, not raw tag dumps.",
            "- Treat Urgent as true emergency work only.",
            "- Mention the most important blockers or time-sensitive work, and note when something can wait.",
            "",
            f"Weather alerts: {weather_alerts or 'none'}",
            f"Weather conditions: {weather_conditions or 'none'}",
            f"Session context: {session_context}",
            f"Section counts: urgent={len(urgent_ids)}, routine={len(routine_ids)}, project={len(project_ids)}",
            "Top tasks:",
            *task_lines,
        ]
    )
    response = triage_summary_model.invoke(
        [
            SystemMessage(content="You write short, practical garden triage summaries."),
            HumanMessage(content=prompt),
        ]
    )
    content = getattr(response, "content", "")
    if isinstance(content, str):
        summary = content.strip()
    elif isinstance(content, list):
        summary = " ".join(
            block.get("text", "").strip()
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
    else:
        summary = str(content).strip()
    if not summary:
        raise ValueError("Empty triage summary response.")
    return summary


def _build_reasoning_summary(
    rows: list[dict[str, Any]],
    *,
    session_context: dict[str, Any],
    weather_snapshot,
    impacts_by_task: dict[str, list[dict[str, Any]]],
    urgent_ids: list[str],
    routine_ids: list[str],
    project_ids: list[str],
) -> str:
    fallback = _deterministic_reasoning_summary(
        rows,
        urgent_ids=urgent_ids,
        routine_ids=routine_ids,
        project_ids=project_ids,
        impacts_by_task=impacts_by_task,
        weather_snapshot=weather_snapshot,
    )
    try:
        return _llm_reasoning_summary(
            rows,
            session_context=session_context,
            weather_snapshot=weather_snapshot,
            impacts_by_task=impacts_by_task,
            urgent_ids=urgent_ids,
            routine_ids=routine_ids,
            project_ids=project_ids,
        )
    except Exception:
        return fallback


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
    for row in filtered_rows:
        task = row["task"]
        urgency = compute_task_urgency(task, now or datetime.now(dt_timezone.utc))
        section = _triage_section_for_task(task, urgency, impacts_by_task.get(task.id, []))
        recommended_ids.append(task.id)
        if section == "Urgent":
            urgent_ids.append(task.id)
        elif section == "Routine":
            routine_ids.append(task.id)
        else:
            project_ids.append(task.id)

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
        reasoning_summary=_build_reasoning_summary(
            filtered_rows,
            session_context=session_context,
            weather_snapshot=weather_snapshot,
            impacts_by_task=impacts_by_task,
            urgent_ids=urgent_ids,
            routine_ids=routine_ids,
            project_ids=project_ids,
        ),
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

    sections = ["Daily triage:"]
    for title, ids in _visible_triage_sections(snapshot):
        sections.extend(["", f"{title}:", *lines_for(ids)])
    sections.extend(["", f"Why: {snapshot.reasoning_summary}"])
    if snapshot.user_focus_summary:
        sections.append(f"Context: {snapshot.user_focus_summary}")
    return "\n".join(sections)
