from __future__ import annotations

from datetime import datetime

import pytest

from agent.temporal import build_temporal_context, infer_session_context
from agent.weather import derive_weather_impacts
from tests.support.factories import make_profile, make_triage_snapshot, make_weather_snapshot


@pytest.mark.unit
def test_build_temporal_context_uses_timezone_and_latest_snapshots(db_session):
    make_profile(db_session)
    weather = make_weather_snapshot(db_session)
    triage = make_triage_snapshot(db_session, weather_snapshot_id=weather.id)

    context = build_temporal_context(
        db_session,
        timezone="America/Los_Angeles",
        now=datetime.fromisoformat("2026-04-12T09:30:00-07:00"),
        days_ahead=7,
    )

    assert context["today"] == "2026-04-12"
    assert context["tomorrow"] == "2026-04-13"
    assert context["latest_weather_snapshot_id"] == weather.id
    assert context["latest_triage_snapshot_id"] == triage.id


@pytest.mark.unit
def test_infer_session_context_parses_time_energy_and_focus(db_session):
    profile = make_profile(db_session)
    from tests.support.factories import make_project

    project = make_project(db_session, profile, name="Tomato Project")

    context = infer_session_context(
        db_session,
        "I only have 20 minutes, low energy, and want to work on the Tomato Project outside.",
    )

    assert context["available_minutes"] == 20
    assert context["energy_level"] == "low"
    assert context["focus_project_id"] == project.id
    assert context["open_to_outdoor_work"] is True


@pytest.mark.unit
def test_derive_weather_impacts_detects_actionable_conditions():
    payload = {
        "daily": {
            "time": ["2026-04-14", "2026-04-15", "2026-04-16"],
            "temperature_2m_max": [34, 22, 18],
            "temperature_2m_min": [12, 0, 10],
            "precipitation_sum": [0, 20, 1],
            "wind_speed_10m_max": [8, 10, 40],
        }
    }

    impacts, actions, conditions, alerts = derive_weather_impacts(payload)
    impact_types = {impact["impact_type"] for impact in impacts}

    assert {"heat", "frost", "heavy_rain", "storm"} <= impact_types
    assert "2026-04-14" in conditions
    assert "Frost risk." in alerts
    assert any("Prioritize watering" in action["action"] for action in actions)
