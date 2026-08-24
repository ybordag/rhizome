from __future__ import annotations

from datetime import datetime

import pytest

from agent.core.temporal import build_temporal_context, infer_session_context
from agent.domain.weather import derive_weather_impacts, evaluate_weather_task_impacts, get_latest_weather_snapshot
from agent.domain.triage import build_triage_snapshot, get_latest_triage_snapshot
from db.database import current_user_id
from tests.support.factories import (
    make_profile,
    make_project,
    make_project_brief,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_generation_run,
    make_triage_snapshot,
    make_weather_snapshot,
)


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
def test_infer_session_context_preserves_opener_as_text_first_focus(db_session):
    context = infer_session_context(
        db_session,
        "I only have 20 minutes, low energy, and want to work on the Tomato Project outside.",
    )

    assert context == {
        "time_text": None,
        "energy_text": None,
        "focus_text": "I only have 20 minutes, low energy, and want to work on the Tomato Project outside.",
        "focus_context": [],
    }
    assert "available_minutes" not in context
    assert "energy_level" not in context
    assert "focus_project_id" not in context


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


@pytest.mark.unit
def test_weather_task_impacts_use_task_intents_not_generic_planting_keywords(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    generation_run = make_task_generation_run(db_session, project, revision)

    prepare_task = make_task(
        db_session,
        project=project,
        revision=revision,
        generation_run=generation_run,
        title="Prepare growbag_1",
        description="Prepare growbag_1 for planting.",
        generator_key="prepare.container.growbag_1",
        type="milestone",
    )
    fertilize_task = make_task(
        db_session,
        project=project,
        revision=revision,
        generation_run=generation_run,
        title="Fertilize Tomato after transplant",
        description="Apply the first post-transplant feed to Tomato.",
        generator_key="tomato.followup_fertilize",
        type="maintenance",
    )
    transplant_task = make_task(
        db_session,
        project=project,
        revision=revision,
        generation_run=generation_run,
        title="Transplant Tomato to final location",
        description="Move Tomato into its final location.",
        generator_key="tomato.transplant",
        type="milestone",
    )
    weather = make_weather_snapshot(
        db_session,
        derived_impacts=[
            {"date": "2026-04-14", "impact_type": "heavy_rain", "severity": "high", "summary": "Heavy rain likely."},
            {"date": "2026-04-15", "impact_type": "good_planting_window", "severity": "low", "summary": "Good planting conditions."},
            {"date": "2026-04-16", "impact_type": "heat", "severity": "high", "summary": "Heat stress likely."},
        ],
    )

    impacts = evaluate_weather_task_impacts(db_session, project_id=project.id, weather_snapshot=weather)

    impacts_by_task = {}
    for impact in impacts:
        impacts_by_task.setdefault(impact["task_id"], []).append(impact)

    assert prepare_task.id not in impacts_by_task
    assert fertilize_task.id not in impacts_by_task
    transplant_impacts = {impact["impact_type"] for impact in impacts_by_task[transplant_task.id]}
    assert {"heavy_rain", "good_planting_window", "heat"} == transplant_impacts


@pytest.mark.unit
def test_build_triage_snapshot_does_not_filter_tasks_from_text_first_session_context(db_session):
    profile = make_profile(db_session)
    tomato_project = make_project(db_session, profile, name="Tomato Project")
    pepper_project = make_project(db_session, profile, name="Pepper Project")

    tomato_brief = make_project_brief(db_session, tomato_project)
    tomato_proposal = make_project_proposal(db_session, tomato_project, tomato_brief)
    tomato_revision = make_project_revision(db_session, tomato_project, tomato_proposal)
    tomato_run = make_task_generation_run(db_session, tomato_project, tomato_revision)
    tomato_task = make_task(
        db_session,
        project=tomato_project,
        revision=tomato_revision,
        generation_run=tomato_run,
        title="Short tomato watering",
        estimated_minutes=10,
        scheduled_date=datetime(2026, 4, 14),
    )

    pepper_brief = make_project_brief(db_session, pepper_project)
    pepper_proposal = make_project_proposal(db_session, pepper_project, pepper_brief)
    pepper_revision = make_project_revision(db_session, pepper_project, pepper_proposal)
    pepper_run = make_task_generation_run(db_session, pepper_project, pepper_revision)
    pepper_task = make_task(
        db_session,
        project=pepper_project,
        revision=pepper_revision,
        generation_run=pepper_run,
        title="Long pepper trellis repair",
        estimated_minutes=90,
        scheduled_date=datetime(2026, 4, 14),
    )

    current_user_id.set("1")
    try:
        snapshot = build_triage_snapshot(
            db_session,
            opener="I only have 5 minutes and low energy for the Tomato Project.",
            now=datetime(2026, 4, 14),
        )
    finally:
        current_user_id.set("1")

    assert tomato_task.id in snapshot.recommended_task_ids
    assert pepper_task.id in snapshot.recommended_task_ids
    assert snapshot.session_context == {
        "time_text": None,
        "energy_text": None,
        "focus_text": "I only have 5 minutes and low energy for the Tomato Project.",
        "focus_context": [],
    }


@pytest.mark.unit
def test_build_triage_snapshot_preserves_session_context_override(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile, name="Tomato Project")
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project, revision)
    task = make_task(
        db_session,
        project=project,
        revision=revision,
        generation_run=run,
        title="Prepare growbag",
    )
    context = {
        "time_text": "35 minutes",
        "energy_text": "low but focused",
        "focus_text": "Courtyard Tomatoes March 2026",
        "focus_context": [{"subject_type": "project", "subject_id": project.id}],
        "source": "user",
    }

    current_user_id.set("1")
    snapshot = build_triage_snapshot(
        db_session,
        opener="A different opener should not replace stored context.",
        session_context=context,
        now=datetime(2026, 4, 14),
    )

    assert task.id in snapshot.recommended_task_ids
    assert snapshot.session_context == context
    assert "time=35 minutes" in snapshot.user_focus_summary
    assert "focus=Courtyard Tomatoes March 2026" in snapshot.user_focus_summary


# ---------------------------------------------------------------------------
# WeatherSnapshot / TriageSnapshot garden_profile_id isolation
#
# Different users have different garden locations, so weather/triage data
# must not be shared across them (multi-tenancy audit fix, post-#130).
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_latest_weather_snapshot_scoped_to_current_users_garden(db_session):
    profile_a = make_profile(db_session, user_id="owner-a", location_label="Phoenix, AZ")
    profile_b = make_profile(db_session, user_id="owner-b", location_label="Duluth, MN")
    snapshot_a = make_weather_snapshot(db_session, garden_profile_id=profile_a.id, location_label="Phoenix, AZ")
    make_weather_snapshot(db_session, garden_profile_id=profile_b.id, location_label="Duluth, MN")

    current_user_id.set("owner-a")
    try:
        result = get_latest_weather_snapshot(db_session)
        assert result.id == snapshot_a.id
        assert result.location_label == "Phoenix, AZ"
    finally:
        current_user_id.set("1")


@pytest.mark.unit
def test_get_latest_weather_snapshot_none_without_garden_profile(db_session):
    current_user_id.set("no-profile-user")
    try:
        assert get_latest_weather_snapshot(db_session) is None
    finally:
        current_user_id.set("1")


@pytest.mark.unit
def test_get_latest_triage_snapshot_scoped_to_current_users_garden(db_session):
    profile_a = make_profile(db_session, user_id="owner-a")
    profile_b = make_profile(db_session, user_id="owner-b")
    triage_a = make_triage_snapshot(db_session, garden_profile_id=profile_a.id, user_focus_summary="owner-a session")
    make_triage_snapshot(db_session, garden_profile_id=profile_b.id, user_focus_summary="owner-b session")

    current_user_id.set("owner-b")
    try:
        result = get_latest_triage_snapshot(db_session)
        assert result.user_focus_summary == "owner-b session"
    finally:
        current_user_id.set("1")

    current_user_id.set("owner-a")
    try:
        result = get_latest_triage_snapshot(db_session)
        assert result.id == triage_a.id
    finally:
        current_user_id.set("1")
