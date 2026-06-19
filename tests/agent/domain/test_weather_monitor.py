"""
Tests for Phase 2 calendula additions to agent/domain/weather.py:
  - unsafe_outdoor_window / safe_outdoor_window impact types
  - _is_critical_task_impact()
  - apply_weather_impacts() auto-apply/queue policy and MonitorAlert creation
"""

import pytest

from agent.domain.weather import (
    _is_critical_task_impact,
    apply_weather_impacts,
    derive_weather_impacts,
)
from db.models import MonitorAlert, WeatherTaskChangeSet
from tests.support.factories import (
    make_profile,
    make_project,
    make_project_brief,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_generation_run,
    make_weather_snapshot,
)


# ---------------------------------------------------------------------------
# derive_weather_impacts — new window types
# ---------------------------------------------------------------------------

def _impacts_of_type(impacts, impact_type):
    return [i for i in impacts if i["impact_type"] == impact_type]


@pytest.mark.unit
def test_derive_impacts_unsafe_window_for_extreme_heat():
    payload = {
        "daily": {
            "time": ["2026-06-20"],
            "temperature_2m_max": [38],   # > 35 threshold
            "temperature_2m_min": [22],
            "precipitation_sum": [0],
            "wind_speed_10m_max": [10],
        }
    }
    impacts, _, _, _ = derive_weather_impacts(payload)
    unsafe = _impacts_of_type(impacts, "unsafe_outdoor_window")

    assert len(unsafe) == 1
    assert unsafe[0]["reason"] == "extreme_heat"
    assert unsafe[0]["severity"] == "high"
    assert "midday" in unsafe[0]["timing_advice"]


@pytest.mark.unit
def test_derive_impacts_unsafe_window_for_storm():
    payload = {
        "daily": {
            "time": ["2026-06-20"],
            "temperature_2m_max": [22],
            "temperature_2m_min": [15],
            "precipitation_sum": [5],
            "wind_speed_10m_max": [45],   # > 35 threshold
        }
    }
    impacts, _, _, _ = derive_weather_impacts(payload)
    unsafe = _impacts_of_type(impacts, "unsafe_outdoor_window")

    assert len(unsafe) == 1
    assert unsafe[0]["reason"] == "storm"
    assert unsafe[0]["severity"] == "high"


@pytest.mark.unit
def test_derive_impacts_unsafe_window_for_heavy_rain():
    payload = {
        "daily": {
            "time": ["2026-06-20"],
            "temperature_2m_max": [18],
            "temperature_2m_min": [12],
            "precipitation_sum": [30],    # > 25 threshold
            "wind_speed_10m_max": [10],
        }
    }
    impacts, _, _, _ = derive_weather_impacts(payload)
    unsafe = _impacts_of_type(impacts, "unsafe_outdoor_window")

    assert len(unsafe) == 1
    assert unsafe[0]["reason"] == "heavy_rain"
    assert unsafe[0]["severity"] == "medium"


@pytest.mark.unit
def test_derive_impacts_unsafe_window_for_frost():
    payload = {
        "daily": {
            "time": ["2026-01-10"],
            "temperature_2m_max": [8],
            "temperature_2m_min": [-1],   # <= 0 threshold
            "precipitation_sum": [0],
            "wind_speed_10m_max": [5],
        }
    }
    impacts, _, _, _ = derive_weather_impacts(payload)
    unsafe = _impacts_of_type(impacts, "unsafe_outdoor_window")

    assert len(unsafe) == 1
    assert unsafe[0]["reason"] == "frost"


@pytest.mark.unit
def test_derive_impacts_safe_window_for_pleasant_day():
    payload = {
        "daily": {
            "time": ["2026-04-15"],
            "temperature_2m_max": [22],   # in 10-28 range
            "temperature_2m_min": [12],   # >= 4
            "precipitation_sum": [2],     # < 8
            "wind_speed_10m_max": [10],   # < 22
        }
    }
    impacts, _, _, _ = derive_weather_impacts(payload)
    safe = _impacts_of_type(impacts, "safe_outdoor_window")

    assert len(safe) == 1
    assert safe[0]["reason"] == "pleasant_conditions"
    assert safe[0]["severity"] == "low"


@pytest.mark.unit
def test_derive_impacts_no_safe_window_when_unsafe_conditions_exist():
    payload = {
        "daily": {
            "time": ["2026-06-20"],
            "temperature_2m_max": [38],   # extreme heat → unsafe
            "temperature_2m_min": [22],
            "precipitation_sum": [0],
            "wind_speed_10m_max": [10],
        }
    }
    impacts, _, _, _ = derive_weather_impacts(payload)
    safe = _impacts_of_type(impacts, "safe_outdoor_window")
    unsafe = _impacts_of_type(impacts, "unsafe_outdoor_window")

    assert len(safe) == 0
    assert len(unsafe) == 1


@pytest.mark.unit
def test_derive_impacts_one_unsafe_window_per_day_most_severe_wins():
    # Storm trumps heavy rain — only one unsafe window per day
    payload = {
        "daily": {
            "time": ["2026-06-20"],
            "temperature_2m_max": [25],
            "temperature_2m_min": [15],
            "precipitation_sum": [30],    # heavy rain
            "wind_speed_10m_max": [40],   # storm — should win
        }
    }
    impacts, _, _, _ = derive_weather_impacts(payload)
    unsafe = _impacts_of_type(impacts, "unsafe_outdoor_window")

    assert len(unsafe) == 1
    assert unsafe[0]["reason"] == "storm"


@pytest.mark.unit
def test_derive_impacts_existing_types_still_detected():
    """Existing impact types (frost, heat, etc.) are unaffected by the new additions."""
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
    impact_types = {i["impact_type"] for i in impacts}

    assert {"heat", "frost", "heavy_rain", "storm"} <= impact_types
    assert "2026-04-14" in conditions


# ---------------------------------------------------------------------------
# _is_critical_task_impact
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("impact_type,expected", [
    ("storm", True),
    ("frost", True),
    ("heat", True),
    ("heavy_rain", False),
    ("good_planting_window", False),
    ("unsafe_outdoor_window", False),
    ("safe_outdoor_window", False),
])
def test_is_critical_task_impact(impact_type, expected):
    assert _is_critical_task_impact({"impact_type": impact_type}) is expected


# ---------------------------------------------------------------------------
# apply_weather_impacts — integration tests
# ---------------------------------------------------------------------------

def _make_transplant_task(db_session, profile, project, revision, run):
    return make_task(
        db_session,
        project=project,
        revision=revision,
        generation_run=run,
        title="Transplant Tomato",
        generator_key="tomato.transplant",
        type="milestone",
    )


def _setup_project(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project, revision)
    return profile, project, revision, run


@pytest.mark.integration
def test_apply_weather_impacts_auto_applies_critical_and_writes_alert(db_session, patched_sessionlocal):
    _, project, revision, run = _setup_project(db_session)
    _make_transplant_task(db_session, None, project, revision, run)

    snapshot = make_weather_snapshot(db_session, derived_impacts=[
        {"date": "2026-06-20", "impact_type": "frost", "severity": "high", "summary": "Frost risk."},
    ])

    result = apply_weather_impacts(db_session, snapshot=snapshot, user_id=1)
    db_session.flush()

    # Changeset was auto-approved
    change_sets = db_session.query(WeatherTaskChangeSet).all()
    approved = [cs for cs in change_sets if cs.status == "approved"]
    assert len(approved) == 1

    # Critical MonitorAlert written
    alerts = db_session.query(MonitorAlert).filter(MonitorAlert.alert_type == "weather_critical").all()
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"
    assert alerts[0].user_id == "1"

    assert result["critical_applied"] > 0
    assert result["advisory_queued"] == 0


@pytest.mark.integration
def test_apply_weather_impacts_queues_advisory_as_draft(db_session, patched_sessionlocal):
    _, project, revision, run = _setup_project(db_session)
    _make_transplant_task(db_session, None, project, revision, run)

    snapshot = make_weather_snapshot(db_session, derived_impacts=[
        {"date": "2026-06-20", "impact_type": "heavy_rain", "severity": "medium", "summary": "Heavy rain likely."},
    ])

    result = apply_weather_impacts(db_session, snapshot=snapshot, user_id=1)
    db_session.flush()

    # Changeset stays as draft (not auto-approved)
    change_sets = db_session.query(WeatherTaskChangeSet).all()
    assert all(cs.status == "draft" for cs in change_sets)

    # Advisory MonitorAlert written
    alerts = db_session.query(MonitorAlert).filter(MonitorAlert.alert_type == "weather_advisory").all()
    assert len(alerts) == 1
    assert alerts[0].severity == "medium"

    assert result["critical_applied"] == 0
    assert result["advisory_queued"] > 0


@pytest.mark.integration
def test_apply_weather_impacts_writes_working_window_alert(db_session, patched_sessionlocal):
    make_profile(db_session)
    snapshot = make_weather_snapshot(db_session, derived_impacts=[
        {
            "date": "2026-06-20",
            "impact_type": "unsafe_outdoor_window",
            "severity": "high",
            "summary": "Extreme heat on 2026-06-20. Work in early morning or evening only.",
            "reason": "extreme_heat",
            "timing_advice": "Work in early morning or evening only.",
        },
    ])

    result = apply_weather_impacts(db_session, snapshot=snapshot, user_id=1)
    db_session.flush()

    alerts = db_session.query(MonitorAlert).filter(MonitorAlert.alert_type == "working_window").all()
    assert len(alerts) == 1
    assert alerts[0].severity == "high"
    assert "morning or evening" in alerts[0].body

    assert result["window_alerts"] == 1
    assert result["critical_applied"] == 0
    assert result["advisory_queued"] == 0


@pytest.mark.integration
def test_apply_weather_impacts_no_alerts_when_no_impacts(db_session, patched_sessionlocal):
    make_profile(db_session)
    snapshot = make_weather_snapshot(db_session, derived_impacts=[])

    result = apply_weather_impacts(db_session, snapshot=snapshot, user_id=1)
    db_session.flush()

    assert db_session.query(MonitorAlert).count() == 0
    assert result == {"critical_applied": 0, "advisory_queued": 0, "window_alerts": 0}


@pytest.mark.integration
def test_apply_weather_impacts_splits_critical_and_advisory(db_session, patched_sessionlocal):
    _, project, revision, run = _setup_project(db_session)
    _make_transplant_task(db_session, None, project, revision, run)

    snapshot = make_weather_snapshot(db_session, derived_impacts=[
        {"date": "2026-06-20", "impact_type": "frost", "severity": "high", "summary": "Frost risk."},
        {"date": "2026-06-21", "impact_type": "heavy_rain", "severity": "medium", "summary": "Heavy rain."},
    ])

    result = apply_weather_impacts(db_session, snapshot=snapshot, user_id=1)
    db_session.flush()

    change_sets = db_session.query(WeatherTaskChangeSet).all()
    statuses = {cs.status for cs in change_sets}
    assert "approved" in statuses  # critical auto-applied
    assert "draft" in statuses     # advisory queued

    assert result["critical_applied"] > 0
    assert result["advisory_queued"] > 0
