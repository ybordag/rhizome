from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import urlopen

from agent.activity_log import DEFAULT_ACTOR_LABEL, DEFAULT_ACTOR_TYPE, record_create_event, record_update_event, snapshot_model
from agent.temporal import DEFAULT_TIMEZONE, profile_weather_location
from db.models import (
    GardenProfile,
    GardeningProject,
    ProjectRevision,
    Task,
    TaskGenerationRun,
    WeatherSnapshot,
    WeatherTaskChangeSet,
)


WEATHER_FRESHNESS_HOURS = 12
VALID_CHANGESET_STATUSES = {"draft", "approved", "dismissed"}


def fetch_open_meteo_forecast(
    *,
    latitude: float,
    longitude: float,
    timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    params = urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": timezone,
            "forecast_days": 7,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def derive_weather_impacts(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    maxes = daily.get("temperature_2m_max") or []
    mins = daily.get("temperature_2m_min") or []
    precipitation = daily.get("precipitation_sum") or []
    wind = daily.get("wind_speed_10m_max") or []

    impacts: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    summaries: list[str] = []

    for idx, day in enumerate(dates):
        max_temp = float(maxes[idx]) if idx < len(maxes) and maxes[idx] is not None else None
        min_temp = float(mins[idx]) if idx < len(mins) and mins[idx] is not None else None
        rain = float(precipitation[idx]) if idx < len(precipitation) and precipitation[idx] is not None else 0.0
        wind_speed = float(wind[idx]) if idx < len(wind) and wind[idx] is not None else 0.0
        summaries.append(
            f"{day}: high {max_temp if max_temp is not None else '?'}F-equivalent, "
            f"low {min_temp if min_temp is not None else '?'}F-equivalent, rain {rain}mm, wind {wind_speed}."
        )

        if min_temp is not None and min_temp <= 1:
            impacts.append({"date": day, "impact_type": "frost", "severity": "high", "summary": "Frost risk."})
            actions.append({"date": day, "action": "Protect tender plants and delay transplanting."})
        if max_temp is not None and max_temp >= 32:
            impacts.append({"date": day, "impact_type": "heat", "severity": "high", "summary": "Heat stress likely."})
            actions.append({"date": day, "action": "Prioritize watering and shade protection."})
        if rain >= 15:
            impacts.append({"date": day, "impact_type": "heavy_rain", "severity": "medium", "summary": "Heavy rain likely."})
            actions.append({"date": day, "action": "Avoid soil disturbance and check drainage."})
        if wind_speed >= 35:
            impacts.append({"date": day, "impact_type": "storm", "severity": "high", "summary": "High wind or storm risk."})
            actions.append({"date": day, "action": "Secure supports and postpone delicate work."})
        if (
            max_temp is not None
            and 15 <= max_temp <= 27
            and (min_temp is None or min_temp >= 7)
            and rain < 5
            and wind_speed < 20
        ):
            impacts.append({"date": day, "impact_type": "good_planting_window", "severity": "low", "summary": "Good planting conditions."})
            actions.append({"date": day, "action": "Good window for planting or transplanting."})

    alerts = [impact["summary"] + f" ({impact['date']})" for impact in impacts if impact["impact_type"] != "good_planting_window"]
    return impacts, actions, "\n".join(summaries[:3]), "\n".join(alerts) if alerts else "No significant weather alerts."


def get_latest_weather_snapshot(session) -> Optional[WeatherSnapshot]:
    return session.query(WeatherSnapshot).order_by(WeatherSnapshot.created_at.desc()).first()


def refresh_weather_snapshot(
    session,
    *,
    timezone: str = DEFAULT_TIMEZONE,
    fetcher=fetch_open_meteo_forecast,
) -> WeatherSnapshot:
    profile = session.query(GardenProfile).filter(GardenProfile.user_id == 1).first()
    location = profile_weather_location(profile)
    if not location:
        raise ValueError("Garden profile is missing latitude/longitude. Update the weather location first.")

    payload = fetcher(latitude=location["latitude"], longitude=location["longitude"], timezone=timezone)
    impacts, actions, conditions_summary, alerts_summary = derive_weather_impacts(payload)
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    start = datetime.fromisoformat(dates[0]) if dates else datetime.utcnow()
    end = datetime.fromisoformat(dates[-1]) if dates else datetime.utcnow()
    snapshot = WeatherSnapshot(
        timezone=timezone,
        location_label=location["location_label"],
        forecast_start_date=start,
        forecast_end_date=end,
        conditions_summary=conditions_summary,
        alerts_summary=alerts_summary,
        derived_impacts=impacts,
        recommended_actions=actions,
        source="open-meteo",
        raw_payload=payload,
    )
    session.add(snapshot)
    session.flush()
    record_create_event(
        session,
        event_type="weather_snapshot_created",
        category="weather",
        summary=f"Refreshed weather snapshot for {snapshot.location_label}.",
        obj=snapshot,
        metadata={"impact_count": len(impacts)},
        subjects=[{"subject_type": "weather_snapshot", "subject_id": snapshot.id, "role": "primary"}],
    )
    return snapshot


def load_or_refresh_weather_snapshot(
    session,
    *,
    timezone: str = DEFAULT_TIMEZONE,
    freshness_hours: int = WEATHER_FRESHNESS_HOURS,
    fetcher=fetch_open_meteo_forecast,
) -> Optional[WeatherSnapshot]:
    latest = get_latest_weather_snapshot(session)
    if latest and latest.created_at >= datetime.utcnow() - timedelta(hours=freshness_hours):
        return latest
    try:
        return refresh_weather_snapshot(session, timezone=timezone, fetcher=fetcher)
    except Exception:
        return latest


def evaluate_weather_task_impacts(
    session,
    *,
    project_id: Optional[str] = None,
    weather_snapshot: Optional[WeatherSnapshot] = None,
) -> list[dict[str, Any]]:
    snapshot = weather_snapshot or get_latest_weather_snapshot(session)
    if not snapshot:
        return []

    query = session.query(Task).filter(Task.status.notin_(["done", "skipped", "superseded"]))
    if project_id:
        query = query.filter(Task.project_id == project_id)
    tasks = query.order_by(Task.deadline.asc(), Task.window_end.asc(), Task.scheduled_date.asc()).all()

    impacts: list[dict[str, Any]] = []
    for task in tasks:
        haystack = f"{task.title} {task.description or ''} {task.generator_key}".lower()
        for impact in snapshot.derived_impacts or []:
            impact_type = impact.get("impact_type")
            impact_date = impact.get("date")
            proposed_change = None
            if impact_type == "heat" and ("water" in haystack or "transplant" in haystack):
                proposed_change = {
                    "kind": "create_task" if "water" not in haystack else "update_task",
                    "summary": f"Heat risk affects '{task.title}'.",
                    "task_id": task.id,
                    "date": impact_date,
                    "updates": {"notes_append": "Heat advisory: prioritize hydration or shade support."},
                }
            elif impact_type in {"frost", "storm", "heavy_rain"} and any(word in haystack for word in ("transplant", "plant", "amend", "sow")):
                proposed_change = {
                    "kind": "defer_task",
                    "summary": f"Weather may delay '{task.title}'.",
                    "task_id": task.id,
                    "date": impact_date,
                    "updates": {"deferred_until": impact_date},
                }
            elif impact_type == "good_planting_window" and any(word in haystack for word in ("transplant", "plant", "sow")):
                proposed_change = {
                    "kind": "highlight",
                    "summary": f"Good planting window aligns with '{task.title}'.",
                    "task_id": task.id,
                    "date": impact_date,
                    "updates": {},
                }
            if proposed_change:
                impacts.append(
                    {
                        "project_id": task.project_id,
                        "task_id": task.id,
                        "task_title": task.title,
                        "impact_type": impact_type,
                        "impact_date": impact_date,
                        "summary": proposed_change["summary"],
                        "proposed_change": proposed_change,
                    }
                )
    return impacts


def draft_weather_task_changes(
    session,
    *,
    project_id: Optional[str] = None,
) -> WeatherTaskChangeSet:
    snapshot = get_latest_weather_snapshot(session)
    if not snapshot:
        raise ValueError("No weather snapshot found. Refresh weather first.")
    impacts = evaluate_weather_task_impacts(session, project_id=project_id, weather_snapshot=snapshot)
    summary = (
        f"Drafted {len(impacts)} weather-aware task recommendations."
        if impacts
        else "No weather-driven task changes are recommended right now."
    )
    change_set = WeatherTaskChangeSet(
        weather_snapshot_id=snapshot.id,
        project_id=project_id,
        status="draft",
        summary=summary,
        proposed_changes=impacts,
    )
    session.add(change_set)
    session.flush()
    record_create_event(
        session,
        event_type="weather_task_changes_drafted",
        category="weather",
        summary=summary,
        obj=change_set,
        project_id=project_id,
        metadata={"change_count": len(impacts)},
        subjects=[{"subject_type": "weather_task_change_set", "subject_id": change_set.id, "role": "primary"}],
    )
    return change_set


def _event_followup_run(session, *, project_id: str, revision_id: str, summary: str) -> TaskGenerationRun:
    run = TaskGenerationRun(
        project_id=project_id,
        revision_id=revision_id,
        run_type="event_followup",
        status="complete",
        summary=summary,
        run_metadata={"source": "weather"},
    )
    session.add(run)
    session.flush()
    record_create_event(
        session,
        event_type="task_generation_run_created",
        category="task",
        summary=summary,
        obj=run,
        project_id=project_id,
        revision_id=revision_id,
        subjects=[
            {"subject_type": "project", "subject_id": project_id, "role": "affected"},
            {"subject_type": "task_generation_run", "subject_id": run.id, "role": "primary"},
        ],
    )
    return run


def approve_weather_task_changes(session, change_set_id: str) -> WeatherTaskChangeSet:
    change_set = session.query(WeatherTaskChangeSet).filter(WeatherTaskChangeSet.id == change_set_id).first()
    if not change_set:
        raise ValueError(f"No weather task change set found with id {change_set_id}.")
    if change_set.status != "draft":
        raise ValueError(f"Weather task change set {change_set_id} is already {change_set.status}.")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in change_set.proposed_changes or []:
        grouped.setdefault(item["project_id"], []).append(item)

    for project_id, items in grouped.items():
        project = session.query(GardeningProject).filter(GardeningProject.id == project_id).first()
        if not project:
            continue
        revision = (
            session.query(ProjectRevision)
            .filter(ProjectRevision.project_id == project_id, ProjectRevision.status == "active")
            .order_by(ProjectRevision.revision_number.desc())
            .first()
        )
        if not revision:
            continue
        run = _event_followup_run(
            session,
            project_id=project_id,
            revision_id=revision.id,
            summary=f"Applied weather-driven task updates for project '{project.name}'.",
        )
        for item in items:
            proposed = item.get("proposed_change") or {}
            task = session.query(Task).filter(Task.id == item.get("task_id")).first()
            if not task:
                continue
            before = snapshot_model(task)
            kind = proposed.get("kind")
            if kind == "defer_task":
                task.status = "deferred"
                task.deferred_until = datetime.fromisoformat(proposed["updates"]["deferred_until"])
                record_update_event(
                    session,
                    event_type="task_deferred",
                    category="task",
                    summary=f"Deferred task '{task.title}' due to weather.",
                    before=before,
                    obj=task,
                    project_id=task.project_id,
                    revision_id=task.revision_id,
                    metadata={"source": "weather"},
                    subjects=[{"subject_type": "task", "subject_id": task.id, "role": "primary"}],
                )
            elif kind == "update_task":
                append = proposed.get("updates", {}).get("notes_append")
                if append:
                    task.notes = f"{task.notes}\n{append}".strip() if task.notes else append
                record_update_event(
                    session,
                    event_type="task_updated",
                    category="task",
                    summary=f"Updated task '{task.title}' due to weather.",
                    before=before,
                    obj=task,
                    project_id=task.project_id,
                    revision_id=task.revision_id,
                    metadata={"source": "weather"},
                    subjects=[{"subject_type": "task", "subject_id": task.id, "role": "primary"}],
                )
            elif kind == "create_task":
                advisory = Task(
                    project_id=project_id,
                    revision_id=revision.id,
                    generation_run_id=run.id,
                    parent_task_id=task.parent_task_id,
                    series_id=None,
                    source_type="generated_override",
                    generator_key=f"weather.{item['impact_type']}.{task.id}",
                    title=f"Respond to {item['impact_type']} for {task.title}",
                    description=item["summary"],
                    type="emergency",
                    status="pending",
                    scheduled_date=datetime.fromisoformat(item["impact_date"]),
                    earliest_start=datetime.fromisoformat(item["impact_date"]),
                    window_start=datetime.fromisoformat(item["impact_date"]),
                    window_end=datetime.fromisoformat(item["impact_date"]) + timedelta(days=1),
                    deadline=datetime.fromisoformat(item["impact_date"]) + timedelta(days=1),
                    estimated_minutes=20,
                    reversible=True,
                    what_happens_if_skipped="Weather-driven mitigation may be missed.",
                    what_happens_if_delayed="Damage risk may increase.",
                    notes="Created from approved weather draft changes.",
                    linked_subjects=[{"subject_type": "task", "subject_id": task.id, "role": "source"}],
                )
                session.add(advisory)
                session.flush()
                record_create_event(
                    session,
                    event_type="task_created",
                    category="task",
                    summary=f"Created weather-response task '{advisory.title}'.",
                    obj=advisory,
                    project_id=project_id,
                    revision_id=revision.id,
                    metadata={"source": "weather"},
                    subjects=[{"subject_type": "task", "subject_id": advisory.id, "role": "primary"}],
                )

    before_set = snapshot_model(change_set)
    change_set.status = "approved"
    change_set.approved_at = datetime.utcnow()
    record_update_event(
        session,
        event_type="weather_task_changes_approved",
        category="weather",
        summary=change_set.summary,
        before=before_set,
        obj=change_set,
        project_id=change_set.project_id,
        metadata={"status": "approved"},
        subjects=[{"subject_type": "weather_task_change_set", "subject_id": change_set.id, "role": "primary"}],
    )
    return change_set
