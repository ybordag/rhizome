from __future__ import annotations

from datetime import datetime

from agent.tools.activity import get_project_activity
from agent.tools.planning import (
    accept_project_proposal,
    assemble_planning_context,
    check_blocking_unknowns,
    get_or_create_project_brief,
    get_project_brief,
    list_candidate_locations,
    list_candidate_plant_material,
    list_project_proposals,
    preview_project_schedule,
    save_project_proposal,
    update_project_brief,
)
from db.models import ActivityEvent, ProjectBrief, ProjectExecutionSpec, ProjectProposal, ProjectRevision
from tests.support.factories import (
    link_container_to_project,
    make_batch,
    make_container,
    make_plant,
    make_profile,
    make_project,
)


def test_project_brief_tools_create_update_and_fetch(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)

    created = get_or_create_project_brief.invoke({"project_id": project.id})
    updated = update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "Fresh basil and tomatoes by midsummer.",
            "target_start": "2026-04-15",
            "target_completion": "2026-07-15",
            "budget_cap": 90.0,
            "effort_preference": "low",
            "propagation_preference": "mixed",
            "priority_preferences": ["cost", "low_work"],
        }
    )
    fetched = get_project_brief.invoke({"project_id": project.id})

    assert "[Project Brief]" in created
    assert "Desired outcome: Fresh basil and tomatoes by midsummer." in updated
    assert "Budget cap: $90.0" in fetched

    brief = db_session.query(ProjectBrief).filter(ProjectBrief.project_id == project.id).one()
    assert brief.status == "ready_for_proposal"


def test_check_blocking_unknowns_writes_unknowns_event_when_brief_is_incomplete(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)

    get_or_create_project_brief.invoke({"project_id": project.id})
    result = check_blocking_unknowns.invoke({"project_id": project.id})

    db_session.expire_all()
    events = (
        db_session.query(ActivityEvent)
        .filter(
            ActivityEvent.project_id == project.id,
            ActivityEvent.event_type == "project_planning_unknowns_identified",
        )
        .all()
    )

    assert "Blocking unknowns:" in result
    assert "- desired_outcome" in result
    assert "- target_completion" in result
    assert events
    assert set(events[-1].event_metadata["unknowns"]) >= {"desired_outcome", "target_completion", "available_location"}


def test_planning_context_and_candidate_tools_surface_project_constraints(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    container = make_container(db_session, profile, name="Tomato Growbag")
    make_batch(db_session, profile, project=project, plant_name="Tomato")
    make_plant(db_session, profile, container=container, name="Rosemary", status="established", source="existing")
    link_container_to_project(db_session, project, container)
    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "Patio tomatoes for summer.",
            "budget_cap": 100.0,
            "target_completion": "2026-07-01",
        }
    )

    context = assemble_planning_context.invoke({"project_id": project.id})
    unknowns = check_blocking_unknowns.invoke({"project_id": project.id})
    locations = list_candidate_locations.invoke({"project_id": project.id})
    material = list_candidate_plant_material.invoke({"project_id": project.id})

    assert "Planning context for project" in context
    assert "Candidate locations:" in locations
    assert "Tomato Growbag" in locations
    assert "Candidate plant material" in material
    assert "Rosemary" in material
    assert "Blocking unknowns" not in unknowns


def test_planning_context_marks_conflicting_locations_unavailable(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    active_project = make_project(db_session, profile, name="Existing Summer Project", status="active")
    planning_project = make_project(db_session, profile, name="New Planning Project")
    shared_container = make_container(db_session, profile, name="Shared Growbag")

    link_container_to_project(db_session, active_project, shared_container)
    update_project_brief.invoke(
        {
            "project_id": planning_project.id,
            "desired_outcome": "Use the best available container for fall herbs.",
            "target_completion": "2026-09-01",
            "budget_cap": 50.0,
        }
    )

    locations = list_candidate_locations.invoke({"project_id": planning_project.id})
    context = assemble_planning_context.invoke({"project_id": planning_project.id})

    assert "Shared Growbag" in locations
    assert "unavailable" in locations
    assert "Shared Growbag" in context
    assert "unavailable" in context


def test_save_and_list_project_proposals_with_revisioning(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "A reliable summer tomato crop.",
            "target_start": "2026-04-01",
            "target_completion": "2026-07-01",
            "budget_cap": 120.0,
        }
    )

    first = save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Balanced tomato plan",
            "summary": "Seed start tomatoes in two growbags.",
            "recommended_approach": "Use seed-start tomatoes and reuse existing growbags.",
            "selected_locations": [
                {"location_type": "container", "location_id": "c1", "name": "Growbag 1", "estimated_setup_cost": 18}
            ],
            "selected_plants": [
                {"name": "Tomato", "quantity": 2, "propagation_method": "seed"},
                {"name": "Basil", "quantity": 2, "propagation_method": "seed"},
            ],
            "tradeoffs": ["Lower cost, more weekly effort"],
            "risks": ["Late spring weather can slow growth."],
        }
    )
    first_proposal = db_session.query(ProjectProposal).filter(ProjectProposal.project_id == project.id).one()

    revised = save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Faster mixed-start plan",
            "summary": "Buy tomato starts and seed basil to reduce lead time.",
            "recommended_approach": "Use nursery starts for tomatoes and direct sow basil.",
            "selected_locations": [
                {"location_type": "container", "location_id": "c1", "name": "Growbag 1", "estimated_setup_cost": 18}
            ],
            "selected_plants": [
                {"name": "Tomato", "quantity": 2, "propagation_method": "start"},
                {"name": "Basil", "quantity": 2, "propagation_method": "seed"},
            ],
            "tradeoffs": ["Higher cost, lower schedule risk"],
            "risks": ["Nursery starts may be leggy."],
            "replaces_proposal_id": first_proposal.id,
        }
    )
    proposal_list = list_project_proposals.invoke({"project_id": project.id})

    assert "Estimated effort:" in first
    assert "Faster mixed-start plan" in revised
    assert "Version: 2" in proposal_list

    db_session.expire_all()
    refreshed_first = db_session.query(ProjectProposal).filter(ProjectProposal.id == first_proposal.id).one()
    assert refreshed_first.status == "superseded"


def test_save_project_proposal_captures_conflict_and_constraint_notes(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "Container tomatoes despite a tight timeline.",
            "target_start": "2026-04-15",
            "target_completion": "2026-05-01",
            "budget_cap": 20.0,
        }
    )

    save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Conflict heavy plan",
            "summary": "Force tomatoes into a shaded, unavailable container on a tiny budget.",
            "recommended_approach": "Try to make it work anyway.",
            "selected_locations": [
                {
                    "location_type": "container",
                    "location_id": "c1",
                    "name": "Shaded Growbag",
                    "sunlight": "deep shade",
                    "available": False,
                    "estimated_setup_cost": 18,
                }
            ],
            "selected_plants": [
                {"name": "Tomato", "quantity": 2, "propagation_method": "seed"},
            ],
        }
    )

    proposal = db_session.query(ProjectProposal).filter(ProjectProposal.project_id == project.id).one()
    notes_text = " ".join(proposal.feasibility_notes or [])

    assert "unavailable" in notes_text.lower()
    assert "completion date" in notes_text.lower()
    assert "budget" in notes_text.lower()
    assert "shaded" in notes_text.lower()


def test_failed_save_project_proposal_rolls_back_rows_and_activity_events(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "A reliable summer tomato crop.",
            "target_start": "2026-04-01",
            "target_completion": "2026-07-01",
            "budget_cap": 120.0,
        }
    )

    result = save_project_proposal.invoke(
        {
            "project_id": "missing-project",
            "title": "Impossible plan",
            "summary": "Should fail.",
            "recommended_approach": "No-op.",
            "selected_locations": [{"location_type": "container", "location_id": "c1", "name": "Growbag 1"}],
            "selected_plants": [{"name": "Tomato", "quantity": 2, "propagation_method": "seed"}],
        }
    )

    assert "Failed to save project proposal" in result
    assert db_session.query(ProjectProposal).count() == 0
    assert db_session.query(ProjectRevision).count() == 0
    assert db_session.query(ProjectExecutionSpec).count() == 0
    assert db_session.query(ActivityEvent).count() == 1  # brief update event only


def test_accepting_proposals_creates_revision_and_execution_spec_and_supersedes_old_revision(
    db_session,
    patched_sessionlocal,
):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "A patio tomato project with manageable upkeep.",
            "target_start": "2026-04-01",
            "target_completion": "2026-07-01",
            "budget_cap": 150.0,
        }
    )

    save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Seed start plan",
            "summary": "Seed start tomatoes.",
            "recommended_approach": "Use trays and growbags.",
            "selected_locations": [{"location_type": "container", "location_id": "c1", "name": "Growbag 1"}],
            "selected_plants": [{"name": "Tomato", "quantity": 2, "propagation_method": "seed"}],
        }
    )
    proposal_one = db_session.query(ProjectProposal).filter(ProjectProposal.project_id == project.id).one()
    accepted_one = accept_project_proposal.invoke({"project_id": project.id, "proposal_id": proposal_one.id})

    save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Starts plan",
            "summary": "Buy starts for a faster project.",
            "recommended_approach": "Buy two starts and skip tray work.",
            "selected_locations": [{"location_type": "container", "location_id": "c1", "name": "Growbag 1"}],
            "selected_plants": [{"name": "Tomato", "quantity": 2, "propagation_method": "start"}],
        }
    )
    proposal_two = (
        db_session.query(ProjectProposal)
        .filter(ProjectProposal.project_id == project.id, ProjectProposal.version == 2)
        .one()
    )
    accepted_two = accept_project_proposal.invoke({"project_id": project.id, "proposal_id": proposal_two.id})

    db_session.expire_all()
    revisions = (
        db_session.query(ProjectRevision)
        .filter(ProjectRevision.project_id == project.id)
        .order_by(ProjectRevision.revision_number.asc())
        .all()
    )
    specs = db_session.query(ProjectExecutionSpec).filter(ProjectExecutionSpec.project_id == project.id).all()

    assert "Created revision 1" in accepted_one
    assert "Created revision 2" in accepted_two
    assert len(revisions) == 2
    assert revisions[0].status == "superseded"
    assert revisions[1].status == "active"
    assert len(specs) == 2
    assert sum(1 for spec in specs if spec.status == "active") == 1


def test_accept_project_proposal_writes_acceptance_and_revision_events_and_project_mirror(
    db_session,
    patched_sessionlocal,
):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "A patio tomato project with manageable upkeep.",
            "target_start": "2026-04-01",
            "target_completion": "2026-07-01",
            "budget_cap": 150.0,
        }
    )
    save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Seed start plan",
            "summary": "Seed start tomatoes.",
            "recommended_approach": "Use trays and growbags.",
            "selected_locations": [{"location_type": "container", "location_id": "c1", "name": "Growbag 1"}],
            "selected_plants": [{"name": "Tomato", "quantity": 2, "propagation_method": "seed"}],
        }
    )
    proposal = db_session.query(ProjectProposal).filter(ProjectProposal.project_id == project.id).one()

    accept_project_proposal.invoke({"project_id": project.id, "proposal_id": proposal.id})

    db_session.expire_all()
    refreshed_project = db_session.query(type(project)).filter_by(id=project.id).one()
    refreshed_proposal = db_session.query(ProjectProposal).filter_by(id=proposal.id).one()
    acceptance_events = db_session.query(ActivityEvent).filter(
        ActivityEvent.project_id == project.id,
        ActivityEvent.event_type == "project_proposal_accepted",
    ).all()
    revision_events = db_session.query(ActivityEvent).filter(
        ActivityEvent.project_id == project.id,
        ActivityEvent.event_type == "project_revision_created",
    ).all()

    assert refreshed_project.approved_plan["proposal_id"] == proposal.id
    assert refreshed_proposal.status == "accepted"
    assert acceptance_events
    assert len(revision_events) == 2


def test_schedule_preview_and_activity_events_work_for_accepted_revisions(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "Tomatoes and basil by midsummer.",
            "target_start": "2026-04-01",
            "target_completion": "2026-07-01",
            "budget_cap": 120.0,
        }
    )
    save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Mixed herb and tomato plan",
            "summary": "Seed start tomatoes and basil.",
            "recommended_approach": "Use a seed-start workflow with two containers.",
            "selected_locations": [{"location_type": "container", "location_id": "c1", "name": "Growbag 1"}],
            "selected_plants": [
                {"name": "Tomato", "quantity": 2, "propagation_method": "seed"},
                {"name": "Basil", "quantity": 2, "propagation_method": "seed"},
            ],
        }
    )
    proposal = db_session.query(ProjectProposal).filter(ProjectProposal.project_id == project.id).one()
    accept_project_proposal.invoke({"project_id": project.id, "proposal_id": proposal.id})
    db_session.expire_all()
    revision = db_session.query(ProjectRevision).filter(ProjectRevision.project_id == project.id).one()

    preview = preview_project_schedule.invoke({"project_id": project.id, "revision_id": revision.id})
    history = get_project_activity.invoke({"project_id": project.id})

    preview_events = (
        db_session.query(ActivityEvent)
        .filter(ActivityEvent.project_id == project.id, ActivityEvent.event_type == "project_schedule_preview_generated")
        .all()
    )

    assert "Project schedule preview:" in preview
    assert "Recurring care rules:" in preview
    assert preview_events
    assert "project_schedule_preview_generated" in history


def test_preview_project_schedule_from_proposal_does_not_create_revision_or_execution_spec(
    db_session,
    patched_sessionlocal,
):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    update_project_brief.invoke(
        {
            "project_id": project.id,
            "desired_outcome": "Tomatoes and basil by midsummer.",
            "target_start": "2026-04-01",
            "target_completion": "2026-07-01",
            "budget_cap": 120.0,
        }
    )
    save_project_proposal.invoke(
        {
            "project_id": project.id,
            "title": "Proposal-only preview",
            "summary": "Preview before acceptance.",
            "recommended_approach": "Use one growbag and seed starts.",
            "selected_locations": [{"location_type": "container", "location_id": "c1", "name": "Growbag 1"}],
            "selected_plants": [{"name": "Tomato", "quantity": 2, "propagation_method": "seed"}],
        }
    )
    proposal = db_session.query(ProjectProposal).filter(ProjectProposal.project_id == project.id).one()

    preview = preview_project_schedule.invoke({"project_id": project.id, "proposal_id": proposal.id})

    assert "Project schedule preview:" in preview
    assert db_session.query(ProjectRevision).count() == 0
    assert db_session.query(ProjectExecutionSpec).count() == 0
