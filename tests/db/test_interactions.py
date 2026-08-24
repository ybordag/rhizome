from __future__ import annotations

from agent.domain.interactions import (
    build_confirmation_interaction,
    build_proposal_review_interaction,
    build_triage_view_interaction,
    build_weather_change_review_interaction,
    infer_resolution_status,
    record_interaction_summary,
    resolve_interaction_record,
    get_pending_interaction_record,
)
from db.database import current_user_id
from db.models import InteractionRecord, ProjectProposal, TriageSnapshot, WeatherSnapshot, WeatherTaskChangeSet
from tests.support.factories import (
    make_profile,
    make_project,
    make_project_brief,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_generation_run,
    make_triage_snapshot,
)


def test_confirmation_interaction_serializes_actions():
    interaction = build_confirmation_interaction(
        [{"name": "delete_project", "args": {"project_id": "proj-1"}}]
    )

    assert interaction["interaction_type"] == "confirmation_request"
    assert interaction["actions"][0]["id"] == "confirm"
    assert interaction["actions"][1]["id"] == "cancel"


def test_record_and_resolve_interaction_summary(db_session):
    interaction = build_confirmation_interaction(
        [{"name": "delete_project", "args": {"project_id": "proj-1"}}]
    )
    record = record_interaction_summary(
        db_session,
        interaction,
        source_type="confirmation",
        source_id="proj-1",
    )
    resolve_interaction_record(
        db_session,
        record,
        action_id="confirm",
        resolution_summary="Confirmed in the CLI.",
    )
    db_session.commit()

    stored = db_session.query(InteractionRecord).filter(InteractionRecord.id == record.id).one()
    assert stored.status == "resolved"
    assert stored.resolution_action == "confirm"
    assert stored.record_metadata["actions"][0]["label"] == "Confirm"


# ---------------------------------------------------------------------------
# record_interaction_summary — notification push (#130)
# ---------------------------------------------------------------------------

def test_record_interaction_summary_pushes_interaction_pending(db_session):
    from agent.domain import notifications
    from db.database import current_user_id

    current_user_id.set("user-1")
    queue = notifications.get_or_create_user_queue("user-1")
    try:
        interaction = build_confirmation_interaction(
            [{"name": "delete_project", "args": {"project_id": "proj-1"}}]
        )
        record = record_interaction_summary(
            db_session, interaction, source_type="confirmation", source_id="proj-1",
        )

        event = queue.get_nowait()
        assert event["type"] == "interaction_pending"
        assert event["payload"]["id"] == record.id
        assert event["payload"]["interaction_type"] == "confirmation_request"
    finally:
        notifications.remove_user_queue("user-1")


def test_record_interaction_summary_push_noop_without_active_queue(db_session):
    """No active queue (no SSE connection) — must not raise."""
    from db.database import current_user_id

    current_user_id.set("user-without-queue")
    interaction = build_confirmation_interaction(
        [{"name": "delete_project", "args": {"project_id": "proj-1"}}]
    )
    record = record_interaction_summary(
        db_session, interaction, source_type="confirmation", source_id="proj-1",
    )
    assert record.id is not None


def test_record_interaction_summary_does_not_push_for_non_pending_status(db_session):
    """Only freshly-created pending interactions push — resolved ones (rare at
    creation time, but the status check should still hold) do not."""
    from agent.domain import notifications
    from agent.domain.interactions import INTERACTION_RESOLVED
    from db.database import current_user_id

    current_user_id.set("user-2")
    queue = notifications.get_or_create_user_queue("user-2")
    try:
        interaction = build_confirmation_interaction(
            [{"name": "delete_project", "args": {"project_id": "proj-1"}}]
        )
        interaction["status"] = INTERACTION_RESOLVED
        record_interaction_summary(
            db_session, interaction, source_type="confirmation", source_id="proj-1",
        )
        assert queue.empty()
    finally:
        notifications.remove_user_queue("user-2")


# ---------------------------------------------------------------------------
# user_id scoping — InteractionRecord multi-tenancy fix
# ---------------------------------------------------------------------------

def test_record_interaction_summary_stamps_current_user_id(db_session):
    from db.database import current_user_id

    current_user_id.set("user-a")
    interaction = build_confirmation_interaction(
        [{"name": "delete_project", "args": {"project_id": "proj-1"}}]
    )
    record = record_interaction_summary(
        db_session, interaction, source_type="confirmation", source_id="proj-1",
    )
    assert record.user_id == "user-a"


def test_get_pending_interaction_record_scoped_to_current_user(db_session):
    from agent.domain.interactions import get_pending_interaction_record
    from db.database import current_user_id

    current_user_id.set("user-a")
    record_interaction_summary(
        db_session,
        build_confirmation_interaction([{"name": "delete_project", "args": {"project_id": "proj-1"}}]),
        source_type="confirmation",
        source_id="proj-1",
    )
    db_session.commit()

    current_user_id.set("user-b")
    assert get_pending_interaction_record(db_session) is None

    current_user_id.set("user-a")
    assert get_pending_interaction_record(db_session) is not None


def test_get_pending_interaction_record_skips_empty_triage_view(db_session):
    make_profile(db_session)
    current_user_id.set("1")
    triage = make_triage_snapshot(db_session, recommended_task_ids=[], routine_task_ids=[])
    record_interaction_summary(
        db_session,
        build_triage_view_interaction(db_session, triage),
        source_type="triage",
        source_id=triage.id,
    )
    db_session.commit()

    assert get_pending_interaction_record(db_session) is None


def test_get_pending_interaction_record_skips_superseded_triage_view(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project, revision)
    task = make_task(db_session, project, revision, run, title="Water tomatoes")
    current_user_id.set("1")
    old_triage = make_triage_snapshot(
        db_session,
        recommended_task_ids=[task.id],
        routine_task_ids=[task.id],
    )
    record_interaction_summary(
        db_session,
        build_triage_view_interaction(db_session, old_triage),
        source_type="triage",
        source_id=old_triage.id,
    )
    make_triage_snapshot(
        db_session,
        recommended_task_ids=[task.id],
        routine_task_ids=[task.id],
        reasoning_summary="Newer snapshot.",
    )
    db_session.commit()

    assert get_pending_interaction_record(db_session) is None


def test_get_pending_interaction_record_returns_latest_nonempty_triage_view(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project, revision)
    task = make_task(db_session, project, revision, run, title="Water tomatoes")
    current_user_id.set("1")
    triage = make_triage_snapshot(
        db_session,
        recommended_task_ids=[task.id],
        routine_task_ids=[task.id],
    )
    record = record_interaction_summary(
        db_session,
        build_triage_view_interaction(db_session, triage),
        source_type="triage",
        source_id=triage.id,
    )
    db_session.commit()

    assert get_pending_interaction_record(db_session).id == record.id


def test_list_recent_interaction_records_scoped_to_current_user(db_session):
    from agent.domain.interactions import list_recent_interaction_records
    from db.database import current_user_id

    current_user_id.set("user-a")
    record_interaction_summary(
        db_session,
        build_confirmation_interaction([{"name": "delete_project", "args": {"project_id": "proj-1"}}]),
        source_type="confirmation",
        source_id="proj-1",
    )
    db_session.commit()

    current_user_id.set("user-b")
    assert list_recent_interaction_records(db_session) == []

    current_user_id.set("user-a")
    assert len(list_recent_interaction_records(db_session)) == 1


def test_build_proposal_review_interaction_includes_estimates(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)

    interaction = build_proposal_review_interaction(db_session, project.id, proposal.id)

    assert interaction["interaction_type"] == "proposal_review"
    assert any(section["title"] == "Estimates" for section in interaction["sections"])
    assert any(action["id"] == "request_revision" for action in interaction["actions"])


def test_build_weather_and_triage_interactions_capture_sections(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    generation_run = make_task_generation_run(db_session, project, revision)
    child_task = make_task(db_session, project, revision, generation_run, title="Water tomatoes", type="maintenance")
    snapshot = WeatherSnapshot(
        timezone="America/Los_Angeles",
        location_label="Backyard",
        forecast_start_date=child_task.created_at,
        forecast_end_date=child_task.created_at,
        conditions_summary="Warm and clear.",
        alerts_summary="Heat advisory.",
        derived_impacts=[],
        recommended_actions=[],
        source="open-meteo",
        raw_payload={},
    )
    db_session.add(snapshot)
    db_session.flush()
    change_set = WeatherTaskChangeSet(
        weather_snapshot_id=snapshot.id,
        project_id=project.id,
        summary="Draft weather changes.",
        proposed_changes=[{"task_title": child_task.title, "summary": "Move watering earlier."}],
    )
    triage = TriageSnapshot(
        timezone="America/Los_Angeles",
        session_context={"time_text": "20 minutes"},
        temporal_context={"today": "2026-04-12"},
        weather_snapshot_id=snapshot.id,
        recommended_task_ids=[child_task.id],
        urgent_task_ids=[],
        routine_task_ids=[child_task.id],
        project_task_ids=[],
        reasoning_summary="Short session, so favor quick maintenance tasks.",
        user_focus_summary="20 minutes available, energy=low",
    )
    db_session.add_all([change_set, triage])
    db_session.commit()

    weather_interaction = build_weather_change_review_interaction(db_session, change_set.id)
    triage_interaction = build_triage_view_interaction(db_session, triage)

    assert weather_interaction["interaction_type"] == "weather_change_review"
    assert weather_interaction["sections"][0]["items"][0].startswith(child_task.title)
    assert triage_interaction["interaction_type"] == "triage_view"
    assert [section["title"] for section in triage_interaction["sections"]] == ["Routine"]
    focus_action = next(action for action in triage_interaction["actions"] if action["id"] == "focus_section")
    assert focus_action["input_schema"][0]["options"] == ["Routine"]
    assert infer_resolution_status("dismiss_changes") == "dismissed"
