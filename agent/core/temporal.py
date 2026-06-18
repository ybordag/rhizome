from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any, Optional
from zoneinfo import ZoneInfo

from db.models import GardenProfile, GardeningProject, TriageSnapshot, WeatherSnapshot


DEFAULT_TIMEZONE = "America/Los_Angeles"


def build_temporal_context(
    session,
    *,
    timezone: str = DEFAULT_TIMEZONE,
    now: Optional[datetime] = None,
    days_ahead: int = 7,
) -> dict[str, Any]:
    zone = ZoneInfo(timezone)
    current = now.astimezone(zone) if now else datetime.now(zone)
    latest_weather = session.query(WeatherSnapshot).order_by(WeatherSnapshot.created_at.desc()).first()
    latest_triage = session.query(TriageSnapshot).order_by(TriageSnapshot.created_at.desc()).first()
    return {
        "current_time": current.isoformat(),
        "current_date": current.date().isoformat(),
        "timezone": timezone,
        "today": current.date().isoformat(),
        "tomorrow": (current.date() + timedelta(days=1)).isoformat(),
        "days_ahead_end": (current.date() + timedelta(days=days_ahead)).isoformat(),
        "session_started_at": current.isoformat(),
        "latest_weather_snapshot_id": latest_weather.id if latest_weather else None,
        "latest_weather_generated_at": latest_weather.created_at.isoformat() if latest_weather else None,
        "latest_triage_snapshot_id": latest_triage.id if latest_triage else None,
        "latest_triage_generated_at": latest_triage.created_at.isoformat() if latest_triage else None,
    }


def _parse_minutes(text: str) -> Optional[int]:
    minute_match = re.search(r"(\d+)\s*minutes?", text)
    if minute_match:
        return int(minute_match.group(1))
    hour_match = re.search(r"(\d+(?:\.\d+)?)\s*hours?", text)
    if hour_match:
        return int(float(hour_match.group(1)) * 60)
    quick = {
        "a few minutes": 15,
        "quick": 20,
        "short": 30,
        "all day": 240,
    }
    for phrase, minutes in quick.items():
        if phrase in text:
            return minutes
    return None


def _infer_energy_level(text: str) -> str:
    low_markers = ("tired", "exhausted", "low energy", "wiped", "spent")
    high_markers = ("lots of energy", "high energy", "motivated", "productive", "strong")
    if any(marker in text for marker in low_markers):
        return "low"
    if any(marker in text for marker in high_markers):
        return "high"
    return "medium"


def _match_focus_project(session, text: str) -> Optional[str]:
    projects = session.query(GardeningProject).filter(GardeningProject.status.in_(["planning", "active", "maintaining"])).all()
    lowered = text.lower()
    for project in projects:
        if project.name.lower() in lowered:
            return project.id
    return None


def infer_session_context(session, opener: str, *, timezone: str = DEFAULT_TIMEZONE) -> dict[str, Any]:
    lowered = opener.lower()
    available_minutes = _parse_minutes(lowered)
    focus_project_id = _match_focus_project(session, lowered)

    preferred_location_type = None
    if "container" in lowered or "growbag" in lowered or "pot" in lowered:
        preferred_location_type = "container"
    elif "bed" in lowered or "yard" in lowered:
        preferred_location_type = "bed"

    open_to_outdoor_work = None
    if "outside" in lowered or "outdoor" in lowered or "yard" in lowered:
        open_to_outdoor_work = True
    elif "inside" in lowered or "indoors" in lowered:
        open_to_outdoor_work = False

    return {
        "available_minutes": available_minutes,
        "energy_level": _infer_energy_level(lowered),
        "focus_project_id": focus_project_id,
        "preferred_location_type": preferred_location_type,
        "preferred_location_id": None,
        "wants_quick_wins": "quick" in lowered or "easy" in lowered or "one thing" in lowered,
        "open_to_outdoor_work": open_to_outdoor_work,
        "open_to_dirty_heavy_work": not any(marker in lowered for marker in ("light", "easy", "clean")),
        "timezone": timezone,
        "opener": opener,
    }


def profile_weather_location(profile: Optional[GardenProfile]) -> Optional[dict[str, Any]]:
    if not profile or profile.latitude is None or profile.longitude is None:
        return None
    return {
        "latitude": float(profile.latitude),
        "longitude": float(profile.longitude),
        "location_label": profile.location_label or "Configured garden weather location",
    }
