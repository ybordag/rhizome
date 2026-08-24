from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from db.models import GardenProfile, TriageSnapshot, WeatherSnapshot


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


def infer_session_context(session, opener: str, *, timezone: str = DEFAULT_TIMEZONE) -> dict[str, Any]:
    del session, timezone
    stripped = opener.strip()
    return {
        "time_text": None,
        "energy_text": None,
        "focus_text": stripped or None,
        "focus_context": [],
    }


def profile_weather_location(profile: Optional[GardenProfile]) -> Optional[dict[str, Any]]:
    if not profile or profile.latitude is None or profile.longitude is None:
        return None
    return {
        "latitude": float(profile.latitude),
        "longitude": float(profile.longitude),
        "location_label": profile.location_label or "Configured garden weather location",
    }
