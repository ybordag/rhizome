"""
Planner tools for project briefs, proposals, revisions, and schedule previews.
"""

from __future__ import annotations

from typing import Any, Optional

from langchain.tools import tool

from agent.activity_log import (
    DEFAULT_ACTOR_LABEL,
    DEFAULT_ACTOR_TYPE,
    record_activity_event,
    record_create_event,
    record_update_event,
    snapshot_model,
)
from agent.planner import (
    VALID_BRIEF_STATUSES,
    assemble_planning_context_data,
    build_execution_spec_payload,
    build_plan_input,
    check_blocking_unknowns_data,
    check_plan_feasibility,
    estimate_plan_cost,
    estimate_plan_effort,
    estimate_plan_timeline,
    format_planning_context,
    format_proposal,
    format_schedule_preview,
    generate_schedule_preview,
    get_or_create_brief,
    list_candidate_locations_data,
    list_candidate_plant_material_data,
    parse_optional_date,
)
from db.database import SessionLocal
from db.models import GardenProfile, GardeningProject, ProjectBrief, ProjectExecutionSpec, ProjectProposal, ProjectRevision


def _brief_subject(brief_id: str, role: str = "primary") -> dict[str, str]:
    return {"subject_type": "project_brief", "subject_id": brief_id, "role": role}


def _proposal_subject(proposal_id: str, role: str = "primary") -> dict[str, str]:
    return {"subject_type": "project_proposal", "subject_id": proposal_id, "role": role}


def _revision_subject(revision_id: str, role: str = "primary") -> dict[str, str]:
    return {"subject_type": "project_revision", "subject_id": revision_id, "role": role}


def _execution_spec_subject(spec_id: str, role: str = "primary") -> dict[str, str]:
    return {"subject_type": "project_execution_spec", "subject_id": spec_id, "role": role}


def _validate_status(status: Optional[str]) -> Optional[str]:
    if status is not None and status not in VALID_BRIEF_STATUSES:
        return f"Invalid brief status '{status}'. Must be one of: {', '.join(sorted(VALID_BRIEF_STATUSES))}."
    return None


def _validate_non_negative_budget(value: Optional[float]) -> Optional[str]:
    if value is not None and value < 0:
        return "budget_cap must be 0 or greater."
    return None


def _resolve_project(session, project_id: str) -> GardeningProject:
    project = session.query(GardeningProject).filter(GardeningProject.id == project_id).first()
    if not project:
        raise ValueError(f"No project found with id {project_id}.")
    return project


def _resolve_profile(session, project: GardeningProject) -> GardenProfile:
    profile = session.query(GardenProfile).filter(GardenProfile.id == project.garden_profile_id).first()
    if not profile:
        raise ValueError("Error: no garden profile found for this project.")
    return profile


@tool
def get_or_create_project_brief(project_id: str) -> str:
    """Get the active project brief for planning, creating one from the project if needed."""
    session = SessionLocal()
    try:
        project = _resolve_project(session, project_id)
        brief, created = get_or_create_brief(session, project_id)
        if created:
            record_create_event(
                session,
                event_type="project_brief_created",
                category="project",
                summary=f"Created planning brief for project '{project.name}'.",
                obj=brief,
                project_id=project.id,
                subjects=[
                    {"subject_type": "project", "subject_id": project.id, "role": "affected"},
                    _brief_subject(brief.id),
                ],
                actor_type=DEFAULT_ACTOR_TYPE,
                actor_label=DEFAULT_ACTOR_LABEL,
            )
            session.commit()
            session.refresh(brief)
        return brief.to_summary()
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to get/create project brief: {e}")
        return f"Failed to get or create project brief: {str(e)}"
    finally:
        session.close()


@tool
def update_project_brief(
    project_id: str,
    desired_outcome: Optional[str] = None,
    target_start: Optional[str] = None,
    target_completion: Optional[str] = None,
    budget_cap: Optional[float] = None,
    effort_preference: Optional[str] = None,
    propagation_preference: Optional[str] = None,
    priority_preferences: Optional[list[str]] = None,
    notes: Optional[str] = None,
    status: Optional[str] = None,
) -> str:
    """Update the working planning brief for a project."""
    session = SessionLocal()
    try:
        error = _validate_status(status)
        if error:
            return error
        error = _validate_non_negative_budget(budget_cap)
        if error:
            return error

        project = _resolve_project(session, project_id)
        brief, created = get_or_create_brief(session, project_id)
        before = snapshot_model(brief)

        if desired_outcome is not None:
            brief.desired_outcome = desired_outcome
        if target_start is not None:
            brief.target_start = parse_optional_date(target_start, "target_start")
        if target_completion is not None:
            brief.target_completion = parse_optional_date(target_completion, "target_completion")
        if budget_cap is not None:
            brief.budget_cap = budget_cap
        if effort_preference is not None:
            brief.effort_preference = effort_preference
        if propagation_preference is not None:
            brief.propagation_preference = propagation_preference
        if priority_preferences is not None:
            brief.priority_preferences = priority_preferences
        if notes is not None:
            brief.notes = notes

        if status is not None:
            brief.status = status
        elif brief.desired_outcome and brief.budget_cap is not None and brief.target_completion:
            brief.status = "ready_for_proposal"
        else:
            brief.status = "draft"

        if created:
            record_create_event(
                session,
                event_type="project_brief_created",
                category="project",
                summary=f"Created planning brief for project '{project.name}'.",
                obj=brief,
                project_id=project.id,
                subjects=[
                    {"subject_type": "project", "subject_id": project.id, "role": "affected"},
                    _brief_subject(brief.id),
                ],
                actor_type=DEFAULT_ACTOR_TYPE,
                actor_label=DEFAULT_ACTOR_LABEL,
            )
        else:
            record_update_event(
                session,
                event_type="project_brief_updated",
                category="project",
                summary=f"Updated planning brief for project '{project.name}'.",
                before=before,
                obj=brief,
                project_id=project.id,
                subjects=[
                    {"subject_type": "project", "subject_id": project.id, "role": "affected"},
                    _brief_subject(brief.id),
                ],
                actor_type=DEFAULT_ACTOR_TYPE,
                actor_label=DEFAULT_ACTOR_LABEL,
            )
        session.commit()
        return brief.to_summary()
    except ValueError as e:
        session.rollback()
        return str(e)
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to update project brief: {e}")
        return f"Failed to update project brief: {str(e)}"
    finally:
        session.close()


@tool
def get_project_brief(project_id: str) -> str:
    """Show the current planning brief for a project."""
    session = SessionLocal()
    try:
        project = _resolve_project(session, project_id)
        brief, created = get_or_create_brief(session, project_id)
        if created:
            record_create_event(
                session,
                event_type="project_brief_created",
                category="project",
                summary=f"Created planning brief for project '{project.name}'.",
                obj=brief,
                project_id=project.id,
                subjects=[
                    {"subject_type": "project", "subject_id": project.id, "role": "affected"},
                    _brief_subject(brief.id),
                ],
                actor_type=DEFAULT_ACTOR_TYPE,
                actor_label=DEFAULT_ACTOR_LABEL,
            )
            session.commit()
        return brief.to_summary()
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to get project brief: {e}")
        return f"Failed to get project brief: {str(e)}"
    finally:
        session.close()


@tool
def assemble_planning_context(project_id: str) -> str:
    """Assemble and summarize planning context from the project, garden, resources, and activity history."""
    session = SessionLocal()
    try:
        project = _resolve_project(session, project_id)
        context = assemble_planning_context_data(session, project_id)
        record_activity_event(
            session,
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
            event_type="project_planning_context_assembled",
            category="project",
            summary=f"Assembled planning context for project '{project.name}'.",
            project_id=project.id,
            metadata={"context_summary": context},
            subjects=[{"subject_type": "project", "subject_id": project.id, "role": "primary"}],
        )
        session.commit()
        return format_planning_context(context)
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to assemble planning context: {e}")
        return f"Failed to assemble planning context: {str(e)}"
    finally:
        session.close()


@tool
def check_blocking_unknowns(project_id: str) -> str:
    """List only the missing project-planning inputs that materially block a proposal."""
    session = SessionLocal()
    try:
        project = _resolve_project(session, project_id)
        unknowns = check_blocking_unknowns_data(session, project_id)
        if unknowns:
            record_activity_event(
                session,
                actor_type=DEFAULT_ACTOR_TYPE,
                actor_label=DEFAULT_ACTOR_LABEL,
                event_type="project_planning_unknowns_identified",
                category="project",
                summary=f"Identified blocking planning unknowns for project '{project.name}'.",
                project_id=project.id,
                metadata={"unknowns": unknowns},
                subjects=[{"subject_type": "project", "subject_id": project.id, "role": "primary"}],
            )
            session.commit()
            return "Blocking unknowns:\n" + "\n".join(f"- {unknown}" for unknown in unknowns)
        return "No blocking unknowns. The project has enough context for proposal generation."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to check blocking unknowns: {e}")
        return f"Failed to check blocking unknowns: {str(e)}"
    finally:
        session.close()


@tool
def list_candidate_locations(project_id: str) -> str:
    """List available and unavailable candidate beds and containers for a project."""
    session = SessionLocal()
    try:
        locations = list_candidate_locations_data(session, project_id)
        if not locations:
            return "No candidate locations found."
        lines = [f"Candidate locations for project {project_id}:", "", "Candidate locations:"]
        for location in locations:
            availability = "available" if location["available"] else "unavailable"
            lines.append(
                f"- {location['name']} ({location['location_type']}) | "
                f"{availability} | sunlight: {location['sunlight'] or 'unknown'} | "
                f"soil: {location['soil_type'] or 'unknown'}"
            )
        return "\n".join(lines)
    except Exception as e:
        print(f"[DEBUG] Failed to list candidate locations: {e}")
        return f"Failed to list candidate locations: {str(e)}"
    finally:
        session.close()


@tool
def list_candidate_plant_material(project_id: str) -> str:
    """List existing plants and batches that could inform reuse, cuttings, or propagation choices."""
    session = SessionLocal()
    try:
        material = list_candidate_plant_material_data(session, project_id)
        lines = [f"Candidate plant material for project {project_id}:", ""]
        if material["plants"]:
            lines.append("Plants:")
            lines.extend(
                f"- {plant['name']} {plant.get('variety') or ''} | status: {plant['status']} | "
                f"can take cutting: {plant['can_take_cutting']}".rstrip()
                for plant in material["plants"]
            )
        if material["batches"]:
            lines.append("Batches:")
            lines.extend(
                f"- {batch['name']} | {batch['plant_name']} {batch.get('variety') or ''}".rstrip()
                for batch in material["batches"]
            )
        if not material["plants"] and not material["batches"]:
            lines.append("No candidate plant material found.")
        return "\n".join(lines)
    except Exception as e:
        print(f"[DEBUG] Failed to list candidate plant material: {e}")
        return f"Failed to list candidate plant material: {str(e)}"
    finally:
        session.close()


@tool
def save_project_proposal(
    project_id: str,
    title: str,
    summary: str,
    recommended_approach: str,
    selected_locations: list[dict[str, Any]],
    selected_plants: list[dict[str, Any]],
    material_strategy: Optional[dict[str, Any]] = None,
    propagation_strategy: Optional[dict[str, Any]] = None,
    assumptions: Optional[list[str]] = None,
    tradeoffs: Optional[list[str]] = None,
    risks: Optional[list[str]] = None,
    feasibility_notes: Optional[list[str]] = None,
    maintenance_assumptions: Optional[dict[str, Any]] = None,
    resource_assumptions: Optional[dict[str, Any]] = None,
    budget_assumptions: Optional[dict[str, Any]] = None,
    timing_anchors: Optional[dict[str, Any]] = None,
    replaces_proposal_id: Optional[str] = None,
) -> str:
    """Persist a structured project proposal with deterministic feasibility, cost, timeline, and effort estimates."""
    session = SessionLocal()
    try:
        project = _resolve_project(session, project_id)
        profile = _resolve_profile(session, project)
        brief, _ = get_or_create_brief(session, project_id)

        if not selected_locations:
            return "selected_locations must contain at least one location."
        if not selected_plants:
            return "selected_plants must contain at least one plant."

        if replaces_proposal_id:
            replaced = session.query(ProjectProposal).filter(ProjectProposal.id == replaces_proposal_id).first()
            if not replaced:
                return f"No proposal found with id {replaces_proposal_id}."
            replaced.status = "superseded"

        max_version = (
            session.query(ProjectProposal)
            .filter(ProjectProposal.project_id == project_id)
            .order_by(ProjectProposal.version.desc())
            .first()
        )
        next_version = (max_version.version + 1) if max_version else 1

        plan_input = build_plan_input(
            project=project,
            brief=brief,
            profile=profile,
            selected_locations=selected_locations,
            selected_plants=selected_plants,
            propagation_strategy=propagation_strategy,
            maintenance_assumptions=maintenance_assumptions,
            resource_assumptions=resource_assumptions,
            budget_assumptions=budget_assumptions,
            timing_anchors=timing_anchors,
        )

        feasibility = check_plan_feasibility(plan_input)
        cost_estimate = estimate_plan_cost(plan_input)
        timeline_estimate = estimate_plan_timeline(plan_input)
        effort_estimate = estimate_plan_effort(plan_input)

        proposal = ProjectProposal(
            project_id=project.id,
            brief_id=brief.id,
            version=next_version,
            status="proposed",
            title=title,
            summary=summary,
            recommended_approach=recommended_approach,
            selected_locations=selected_locations,
            selected_plants=selected_plants,
            material_strategy=material_strategy or {},
            propagation_strategy=propagation_strategy or {},
            assumptions=assumptions or [],
            tradeoffs=tradeoffs or [],
            risks=risks or [],
            feasibility_notes=(feasibility_notes or []) + feasibility["warnings"] + feasibility["hard_constraint_violations"],
            cost_estimate=cost_estimate,
            timeline_estimate=timeline_estimate,
            effort_estimate=effort_estimate,
            maintenance_assumptions=maintenance_assumptions or {},
            resource_assumptions=resource_assumptions or {},
            budget_assumptions=budget_assumptions or {},
            timing_anchors=timing_anchors or {"modes": ["calendar", "event"], "calendar": [], "event": []},
        )
        session.add(proposal)
        session.flush()

        record_create_event(
            session,
            event_type="project_proposal_revised" if replaces_proposal_id else "project_proposal_created",
            category="project",
            summary=(
                f"Revised proposal '{proposal.title}' for project '{project.name}'."
                if replaces_proposal_id
                else f"Created proposal '{proposal.title}' for project '{project.name}'."
            ),
            obj=proposal,
            project_id=project.id,
            metadata={"feasibility": feasibility},
            subjects=[
                {"subject_type": "project", "subject_id": project.id, "role": "affected"},
                _proposal_subject(proposal.id),
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        session.commit()
        return format_proposal(proposal)
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to save project proposal: {e}")
        return f"Failed to save project proposal: {str(e)}"
    finally:
        session.close()


@tool
def list_project_proposals(project_id: str) -> str:
    """List all saved proposals for a project."""
    session = SessionLocal()
    try:
        proposals = (
            session.query(ProjectProposal)
            .filter(ProjectProposal.project_id == project_id)
            .order_by(ProjectProposal.version.desc())
            .all()
        )
        if not proposals:
            return "No project proposals found."
        return "\n\n".join(proposal.to_summary() for proposal in proposals)
    except Exception as e:
        print(f"[DEBUG] Failed to list project proposals: {e}")
        return f"Failed to list project proposals: {str(e)}"
    finally:
        session.close()


@tool
def accept_project_proposal(project_id: str, proposal_id: str) -> str:
    """Accept a proposal, create a new active revision, and derive the normalized execution spec."""
    session = SessionLocal()
    try:
        project = _resolve_project(session, project_id)
        proposal = (
            session.query(ProjectProposal)
            .filter(ProjectProposal.id == proposal_id, ProjectProposal.project_id == project_id)
            .first()
        )
        if not proposal:
            return f"No proposal found with id {proposal_id} for project {project_id}."

        brief = session.query(ProjectBrief).filter(ProjectBrief.id == proposal.brief_id).first()
        if not brief:
            return "Cannot accept proposal without an active project brief."

        active_revisions = (
            session.query(ProjectRevision)
            .filter(ProjectRevision.project_id == project_id, ProjectRevision.status == "active")
            .all()
        )
        for revision in active_revisions:
            revision.status = "superseded"
            revision.superseded_at = revision.superseded_at or revision.updated_at or revision.created_at

        active_specs = (
            session.query(ProjectExecutionSpec)
            .filter(ProjectExecutionSpec.project_id == project_id, ProjectExecutionSpec.status == "active")
            .all()
        )
        for spec in active_specs:
            spec.status = "superseded"

        revision_number = (
            session.query(ProjectRevision)
            .filter(ProjectRevision.project_id == project_id)
            .count()
            + 1
        )
        proposal_before = snapshot_model(proposal)
        proposal.status = "accepted"

        approved_plan = {
            "proposal_id": proposal.id,
            "title": proposal.title,
            "summary": proposal.summary,
            "recommended_approach": proposal.recommended_approach,
            "cost_estimate": proposal.cost_estimate,
            "timeline_estimate": proposal.timeline_estimate,
            "effort_estimate": proposal.effort_estimate,
            "tradeoffs": proposal.tradeoffs,
            "risks": proposal.risks,
            "selected_locations": proposal.selected_locations,
            "selected_plants": proposal.selected_plants,
        }
        revision = ProjectRevision(
            project_id=project.id,
            source_proposal_id=proposal.id,
            revision_number=revision_number,
            status="active",
            approved_plan=approved_plan,
        )
        session.add(revision)
        session.flush()

        spec_payload = build_execution_spec_payload(proposal, brief)
        execution_spec = ProjectExecutionSpec(
            project_id=project.id,
            revision_id=revision.id,
            status="active",
            selected_plants=spec_payload["selected_plants"],
            selected_locations=spec_payload["selected_locations"],
            propagation_strategy=spec_payload["propagation_strategy"],
            timing_windows=spec_payload["timing_windows"],
            maintenance_assumptions=spec_payload["maintenance_assumptions"],
            resource_assumptions=spec_payload["resource_assumptions"],
            budget_assumptions=spec_payload["budget_assumptions"],
            preferred_completion_target=spec_payload["preferred_completion_target"],
            plant_categories=spec_payload["plant_categories"],
            timing_anchors=spec_payload["timing_anchors"],
        )
        session.add(execution_spec)
        session.flush()

        project.approved_plan = approved_plan

        record_update_event(
            session,
            event_type="project_proposal_accepted",
            category="project",
            summary=f"Accepted proposal '{proposal.title}' for project '{project.name}'.",
            before=proposal_before,
            obj=proposal,
            project_id=project.id,
            subjects=[
                {"subject_type": "project", "subject_id": project.id, "role": "affected"},
                _proposal_subject(proposal.id),
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        record_create_event(
            session,
            event_type="project_revision_created",
            category="project",
            summary=f"Created revision {revision.revision_number} for project '{project.name}'.",
            obj=revision,
            project_id=project.id,
            revision_id=revision.id,
            subjects=[
                {"subject_type": "project", "subject_id": project.id, "role": "affected"},
                _revision_subject(revision.id),
                _proposal_subject(proposal.id, role="generated_from"),
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        record_create_event(
            session,
            event_type="project_revision_created",
            category="project",
            summary=f"Derived execution spec for project '{project.name}' revision {revision.revision_number}.",
            obj=execution_spec,
            project_id=project.id,
            revision_id=revision.id,
            subjects=[
                {"subject_type": "project", "subject_id": project.id, "role": "affected"},
                _revision_subject(revision.id, role="generated_from"),
                _execution_spec_subject(execution_spec.id),
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        session.commit()
        return (
            f"Accepted proposal '{proposal.title}' for project '{project.name}'. "
            f"Created revision {revision.revision_number} and execution spec {execution_spec.id}."
        )
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to accept project proposal: {e}")
        return f"Failed to accept project proposal: {str(e)}"
    finally:
        session.close()


@tool
def preview_project_schedule(
    project_id: str,
    proposal_id: Optional[str] = None,
    revision_id: Optional[str] = None,
) -> str:
    """Generate a non-persistent project schedule preview from a proposal or active revision."""
    session = SessionLocal()
    try:
        project = _resolve_project(session, project_id)
        if not proposal_id and not revision_id:
            return "Provide either proposal_id or revision_id."

        if proposal_id:
            proposal = (
                session.query(ProjectProposal)
                .filter(ProjectProposal.id == proposal_id, ProjectProposal.project_id == project_id)
                .first()
            )
            if not proposal:
                return f"No proposal found with id {proposal_id} for project {project_id}."
            brief = session.query(ProjectBrief).filter(ProjectBrief.id == proposal.brief_id).first()
            if not brief:
                return "Cannot preview a proposal without its brief."
            execution_spec = build_execution_spec_payload(proposal, brief)
            preview_reference = proposal.id
            preview_revision_id = None
        else:
            revision = (
                session.query(ProjectRevision)
                .filter(ProjectRevision.id == revision_id, ProjectRevision.project_id == project_id)
                .first()
            )
            if not revision:
                return f"No revision found with id {revision_id} for project {project_id}."
            execution_spec_model = (
                session.query(ProjectExecutionSpec)
                .filter(ProjectExecutionSpec.project_id == project_id, ProjectExecutionSpec.revision_id == revision.id)
                .first()
            )
            if not execution_spec_model:
                return f"No execution spec found for revision {revision.id}."
            execution_spec = {
                "selected_plants": execution_spec_model.selected_plants or [],
                "selected_locations": execution_spec_model.selected_locations or [],
                "propagation_strategy": execution_spec_model.propagation_strategy or {},
                "timing_windows": execution_spec_model.timing_windows or {},
                "maintenance_assumptions": execution_spec_model.maintenance_assumptions or {},
                "resource_assumptions": execution_spec_model.resource_assumptions or {},
                "budget_assumptions": execution_spec_model.budget_assumptions or {},
                "preferred_completion_target": execution_spec_model.preferred_completion_target,
                "plant_categories": execution_spec_model.plant_categories or [],
                "timing_anchors": execution_spec_model.timing_anchors or {},
            }
            preview_reference = revision.id
            preview_revision_id = revision.id

        preview = generate_schedule_preview(execution_spec)
        record_activity_event(
            session,
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
            event_type="project_schedule_preview_generated",
            category="project",
            summary=f"Generated schedule preview for project '{project.name}'.",
            project_id=project.id,
            revision_id=preview_revision_id,
            metadata={"preview_reference": preview_reference, "preview": preview},
            subjects=[{"subject_type": "project", "subject_id": project.id, "role": "primary"}],
        )
        session.commit()
        return format_schedule_preview(preview)
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to preview project schedule: {e}")
        return f"Failed to preview project schedule: {str(e)}"
    finally:
        session.close()
