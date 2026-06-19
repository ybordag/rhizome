from __future__ import annotations

from agent.domain.interactions import (
    build_confirmation_interaction,
    build_proposal_review_interaction,
    build_triage_view_interaction,
    record_interaction_summary,
)
from agent.tools.operations.interactions import (
    get_interaction_record,
    get_pending_interaction,
    list_recent_interactions,
    resolve_interaction,
)
from agent.tools.projects.planning import save_project_proposal, update_project_brief
from db.models import InteractionRecord, ProjectProposal, TriageSnapshot
from tests.support.factories import (
    make_profile,
    make_project,
    make_project_brief,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_generation_run,
)


def test_interaction_query_tools_show_pending_and_recent_records(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    interaction = build_confirmation_interaction(
        [{"name": "delete_project", "args": {"project_id": project.id}}]
    )
    record = record_interaction_summary(
        db_session,
        interaction,
        source_type="confirmation",
        source_id=project.id,
        project_id=project.id,
    )
    db_session.commit()

    pending = get_pending_interaction.invoke({})
    recent = list_recent_interactions.invoke({"project_id": project.id})
    detail = get_interaction_record.invoke({"interaction_id": record.id})

    assert record.id in pending
    assert "confirmation_request" in recent
    assert "Actions:" in detail


def test_resolve_interaction_accepts_proposal_and_updates_record(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "Tomatoes by midsummer.",
            "target_start": "2026-04-20",
            "target_completion": "2026-07-15",
            "budget_cap": 90.0,
        }
    )
    save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Balanced plan",
            "summary": "Seed-start tomatoes in a growbag.",
            "recommended_approach": "Start indoors and transplant later.",
            "selected_locations": [{"location_type": "container", "location_id": "c-1", "name": "Growbag"}],
            "selected_plants": [{"name": "Tomato", "quantity": 2, "propagation_method": "seed"}],
        }
    )
    proposal = db_session.query(ProjectProposal).filter(ProjectProposal.project_id == project.id).one()
    interaction = build_proposal_review_interaction(db_session, project.id, proposal.id)
    record = record_interaction_summary(
        db_session,
        interaction,
        source_type="planner",
        source_id=proposal.id,
        project_id=project.id,
    )
    db_session.commit()

    result = resolve_interaction.invoke(
        {
            "interaction_id": record.id,
            "action_id": "accept_proposal",
            "inputs": {},
        }
    )

    db_session.expire_all()
    refreshed = db_session.query(InteractionRecord).filter(InteractionRecord.id == record.id).one()
    assert "Accepted proposal" in result
    assert refreshed.status == "resolved"
    assert refreshed.resolution_action == "accept_proposal"


def test_resolve_interaction_handles_triage_actions(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    generation_run = make_task_generation_run(db_session, project, revision)
    child_task = make_task(db_session, project, revision, generation_run, title="Inspect tomato foliage")
    snapshot = TriageSnapshot(
        timezone="America/Los_Angeles",
        session_context={"available_minutes": 20},
        temporal_context={"today": "2026-04-12"},
        weather_snapshot_id=None,
        recommended_task_ids=[child_task.id],
        urgent_task_ids=[],
        routine_task_ids=[child_task.id],
        project_task_ids=[],
        reasoning_summary="Short session.",
        user_focus_summary="20 minutes available",
    )
    db_session.add(snapshot)
    db_session.commit()
    interaction = build_triage_view_interaction(db_session, snapshot)
    record = record_interaction_summary(
        db_session,
        interaction,
        source_type="triage",
        source_id=snapshot.id,
        project_id=project.id,
    )
    db_session.commit()

    result = resolve_interaction.invoke(
        {
            "interaction_id": record.id,
            "action_id": "show_task_details",
            "inputs": {"task_id": child_task.id},
        }
    )

    assert child_task.title in result
