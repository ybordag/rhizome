from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Optional

from db.models import (
    ActivityEvent,
    Bed,
    Container,
    GardenProfile,
    GardeningProject,
    Plant,
    PlantBatch,
    ProjectBed,
    ProjectBrief,
    ProjectContainer,
    ProjectExecutionSpec,
    ProjectPlant,
    ProjectProposal,
    ProjectRevision,
)


VALID_BRIEF_STATUSES = {"draft", "ready_for_proposal", "superseded"}
VALID_PROPOSAL_STATUSES = {"proposed", "accepted", "rejected", "superseded"}
VALID_REVISION_STATUSES = {"active", "superseded"}
VALID_EXECUTION_SPEC_STATUSES = {"active", "superseded"}

DEFAULT_PLANT_RULES = {
    "tomato": {
        "lead_weeks": 8,
        "establishment_weeks": 11,
        "maintenance_hours_per_week": 1.5,
        "seed_unit_cost": 0.5,
        "start_unit_cost": 4.0,
        "support_cost": 8.0,
        "task_profile": "fruiting_vine",
    },
    "pepper": {
        "lead_weeks": 10,
        "establishment_weeks": 13,
        "maintenance_hours_per_week": 1.0,
        "seed_unit_cost": 0.75,
        "start_unit_cost": 4.5,
        "support_cost": 5.0,
        "task_profile": "fruiting_bush",
    },
    "basil": {
        "lead_weeks": 4,
        "establishment_weeks": 6,
        "maintenance_hours_per_week": 0.5,
        "seed_unit_cost": 0.25,
        "start_unit_cost": 3.0,
        "support_cost": 0.0,
        "task_profile": "leafy_annual",
    },
}


def parse_optional_date(value: Optional[str], field_name: str) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name} '{value}'. Use ISO format YYYY-MM-DD.") from exc


def datetime_to_iso(value: Optional[datetime]) -> Optional[str]:
    return value.date().isoformat() if value else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _plant_rule(plant_name: str) -> dict[str, Any]:
    return DEFAULT_PLANT_RULES.get(plant_name.lower(), {
        "lead_weeks": 6,
        "establishment_weeks": 9,
        "maintenance_hours_per_week": 0.75,
        "seed_unit_cost": 0.5,
        "start_unit_cost": 4.0,
        "support_cost": 2.0,
        "task_profile": "general",
    })


def _normalize_location(location: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "location_type": location.get("location_type") or location.get("type") or "container",
        "location_id": location.get("location_id") or location.get("id"),
        "name": location.get("name") or location.get("label") or "Unnamed location",
        "sunlight": location.get("sunlight") or "unknown",
        "soil_type": location.get("soil_type") or "unknown",
        "available": location.get("available", True),
        "estimated_setup_cost": float(location.get("estimated_setup_cost", 0) or 0),
        "material_cost": float(location.get("material_cost", 0) or 0),
        "amendment_cost": float(location.get("amendment_cost", 0) or 0),
    }
    return normalized


def _normalize_plant(plant: dict[str, Any]) -> dict[str, Any]:
    rule = _plant_rule(str(plant.get("name") or ""))
    propagation_method = plant.get("propagation_method") or plant.get("source") or "seed"
    quantity = int(plant.get("quantity", 1) or 1)
    lead_weeks = float(plant.get("lead_weeks", rule["lead_weeks"]) or rule["lead_weeks"])
    establishment_weeks = float(
        plant.get("establishment_weeks", rule["establishment_weeks"]) or rule["establishment_weeks"]
    )
    unit_cost = float(
        plant.get(
            "unit_cost",
            rule["start_unit_cost"] if propagation_method in {"start", "starts", "transplant"} else rule["seed_unit_cost"],
        )
        or 0
    )
    return {
        "name": plant.get("name") or "Unnamed plant",
        "variety": plant.get("variety"),
        "quantity": quantity,
        "propagation_method": propagation_method,
        "lead_weeks": lead_weeks,
        "establishment_weeks": establishment_weeks,
        "unit_cost": unit_cost,
        "support_cost": float(plant.get("support_cost", rule["support_cost"]) or 0),
        "maintenance_hours_per_week": float(
            plant.get("maintenance_hours_per_week", rule["maintenance_hours_per_week"]) or 0
        ),
        "annual": bool(plant.get("annual", True)),
        "edible": bool(plant.get("edible", True)),
        "light_preference": plant.get("light_preference") or "full sun",
        "soil_preference": plant.get("soil_preference") or "well-drained",
        "task_profile": plant.get("task_profile") or rule["task_profile"],
        "event_triggers": deepcopy(plant.get("event_triggers") or []),
    }


def _days_to_completion(plan_input: dict[str, Any]) -> int:
    timeline = estimate_plan_timeline(plan_input)
    start = datetime.fromisoformat(timeline["planning_start"])
    end = datetime.fromisoformat(timeline["expected_completion_date"])
    return max((end - start).days, 1)


def _select_project(session, project_id: str) -> GardeningProject:
    project = session.query(GardeningProject).filter(GardeningProject.id == project_id).first()
    if not project:
        raise ValueError(f"No project found with id {project_id}.")
    return project


def _select_profile(session, garden_profile_id: str) -> GardenProfile:
    profile = session.query(GardenProfile).filter(GardenProfile.id == garden_profile_id).first()
    if not profile:
        raise ValueError("No garden profile found for this project.")
    return profile


def get_or_create_brief(session, project_id: str) -> tuple[ProjectBrief, bool]:
    project = _select_project(session, project_id)
    brief = (
        session.query(ProjectBrief)
        .filter(ProjectBrief.project_id == project_id, ProjectBrief.status != "superseded")
        .order_by(ProjectBrief.updated_at.desc())
        .first()
    )
    if brief:
        return brief, False

    brief = ProjectBrief(
        project_id=project.id,
        status="draft",
        goal=project.goal,
        budget_cap=project.budget_ceiling,
        notes=project.notes,
    )
    session.add(brief)
    session.flush()
    return brief, True


def _bed_candidate(session, bed: Bed, current_project_id: str) -> dict[str, Any]:
    conflict = (
        session.query(ProjectBed)
        .join(GardeningProject, ProjectBed.project_id == GardeningProject.id)
        .filter(
            ProjectBed.bed_id == bed.id,
            GardeningProject.id != current_project_id,
            GardeningProject.status.in_(["planning", "active"]),
        )
        .first()
    )
    return {
        "location_type": "bed",
        "location_id": bed.id,
        "name": bed.name,
        "sunlight": bed.sunlight,
        "soil_type": bed.soil_type,
        "available": conflict is None,
        "conflict_project_id": conflict.project_id if conflict else None,
        "estimated_setup_cost": 0,
        "material_cost": 0,
        "amendment_cost": 15.0 if (bed.soil_type or "").lower() in {"hard clay", "clay"} else 5.0,
    }


def _container_candidate(session, container: Container, current_project_id: str) -> dict[str, Any]:
    conflict = (
        session.query(ProjectContainer)
        .join(GardeningProject, ProjectContainer.project_id == GardeningProject.id)
        .filter(
            ProjectContainer.container_id == container.id,
            GardeningProject.id != current_project_id,
            GardeningProject.status.in_(["planning", "active"]),
        )
        .first()
    )
    return {
        "location_type": "container",
        "location_id": container.id,
        "name": container.name,
        "sunlight": container.location or "unknown",
        "soil_type": "container mix",
        "available": conflict is None,
        "conflict_project_id": conflict.project_id if conflict else None,
        "estimated_setup_cost": float(container.size_gallons or 0) * 1.5,
        "material_cost": float(container.size_gallons or 0) * 0.5,
        "amendment_cost": float(container.size_gallons or 0) * 0.4,
    }


def list_candidate_locations_data(session, project_id: str) -> list[dict[str, Any]]:
    project = _select_project(session, project_id)
    profile = _select_profile(session, project.garden_profile_id)
    beds = session.query(Bed).filter(Bed.garden_profile_id == profile.id).all()
    containers = session.query(Container).filter(Container.garden_profile_id == profile.id).all()
    locations = [_bed_candidate(session, bed, project_id) for bed in beds]
    locations.extend(_container_candidate(session, container, project_id) for container in containers)
    return locations


def list_candidate_plant_material_data(session, project_id: str) -> dict[str, list[dict[str, Any]]]:
    project = _select_project(session, project_id)
    living_plants = (
        session.query(Plant)
        .filter(
            Plant.garden_profile_id == project.garden_profile_id,
            Plant.status != "removed",
        )
        .all()
    )
    batches = session.query(PlantBatch).filter(PlantBatch.garden_profile_id == project.garden_profile_id).all()
    return {
        "plants": [
            {
                "id": plant.id,
                "name": plant.name,
                "variety": plant.variety,
                "status": plant.status,
                "source": plant.source,
                "can_take_cutting": plant.status in {"established", "producing"},
            }
            for plant in living_plants
        ],
        "batches": [
            {
                "id": batch.id,
                "name": batch.name,
                "plant_name": batch.plant_name,
                "variety": batch.variety,
                "source": batch.source,
                "quantity_sown": batch.quantity_sown,
            }
            for batch in batches
        ],
    }


def assemble_planning_context_data(session, project_id: str) -> dict[str, Any]:
    project = _select_project(session, project_id)
    brief, _ = get_or_create_brief(session, project_id)
    profile = _select_profile(session, project.garden_profile_id)
    locations = list_candidate_locations_data(session, project_id)
    plant_material = list_candidate_plant_material_data(session, project_id)
    active_projects = (
        session.query(GardeningProject)
        .filter(
            GardeningProject.garden_profile_id == project.garden_profile_id,
            GardeningProject.id != project_id,
            GardeningProject.status.in_(["planning", "active"]),
        )
        .all()
    )
    recent_activity = (
        session.query(ActivityEvent)
        .filter(ActivityEvent.project_id == project_id)
        .order_by(ActivityEvent.created_at.desc())
        .limit(5)
        .all()
    )
    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "goal": project.goal,
            "status": project.status,
            "tray_slots": project.tray_slots,
            "budget_ceiling": project.budget_ceiling,
            "notes": project.notes,
        },
        "brief": {
            "id": brief.id,
            "status": brief.status,
            "goal": brief.goal,
            "desired_outcome": brief.desired_outcome,
            "budget_cap": brief.budget_cap,
            "target_start": datetime_to_iso(brief.target_start),
            "target_completion": datetime_to_iso(brief.target_completion),
            "effort_preference": brief.effort_preference,
            "propagation_preference": brief.propagation_preference,
            "priority_preferences": brief.priority_preferences or [],
            "notes": brief.notes,
        },
        "garden_profile": {
            "id": profile.id,
            "climate_zone": profile.climate_zone,
            "soil_type": profile.soil_type,
            "tray_capacity": profile.tray_capacity,
            "tray_indoor_capacity": profile.tray_indoor_capacity,
            "hard_constraints": profile.hard_constraints or {},
            "soft_preferences": profile.soft_preferences or {},
        },
        "candidate_locations": locations,
        "candidate_plant_material": plant_material,
        "active_project_resource_use": [
            {
                "project_id": active.id,
                "name": active.name,
                "tray_slots": active.tray_slots,
                "budget_ceiling": active.budget_ceiling,
            }
            for active in active_projects
        ],
        "recent_activity": [
            {
                "event_type": event.event_type,
                "summary": event.summary,
                "created_at": event.created_at.isoformat(),
            }
            for event in recent_activity
        ],
    }


def check_blocking_unknowns_data(session, project_id: str) -> list[str]:
    context = assemble_planning_context_data(session, project_id)
    brief = context["brief"]
    locations = context["candidate_locations"]
    unknowns = []
    if not brief.get("desired_outcome"):
        unknowns.append("desired_outcome")
    if brief.get("budget_cap") is None:
        unknowns.append("budget_cap")
    if not brief.get("target_completion"):
        unknowns.append("target_completion")
    if not any(location["available"] for location in locations):
        unknowns.append("available_location")
    return unknowns


def _plant_costs(plants: list[dict[str, Any]]) -> tuple[float, float]:
    plant_material_cost = 0.0
    materials_cost = 0.0
    for plant in plants:
        plant_material_cost += plant["unit_cost"] * plant["quantity"]
        materials_cost += plant["support_cost"] * max(plant["quantity"], 1)
    return plant_material_cost, materials_cost


def estimate_plan_cost(plan_input: dict[str, Any]) -> dict[str, Any]:
    plants = [_normalize_plant(plant) for plant in plan_input.get("selected_plants", [])]
    locations = [_normalize_location(location) for location in plan_input.get("selected_locations", [])]
    plant_material_cost, materials_cost = _plant_costs(plants)
    amendment_cost = sum(location["amendment_cost"] for location in locations)
    container_cost = sum(location["estimated_setup_cost"] for location in locations if location["location_type"] == "container")
    materials_cost += sum(location["material_cost"] for location in locations)
    subtotal = plant_material_cost + materials_cost + amendment_cost + container_cost
    contingency_cost = round(subtotal * 0.1, 2)
    confidence = "high" if plants and all(plant["unit_cost"] > 0 for plant in plants) else "medium"
    return {
        "materials_cost": round(materials_cost, 2),
        "plant_material_cost": round(plant_material_cost, 2),
        "soil_amendment_cost": round(amendment_cost, 2),
        "container_cost": round(container_cost, 2),
        "contingency_cost": contingency_cost,
        "total_estimated_cost": round(subtotal + contingency_cost, 2),
        "cost_confidence": confidence,
    }


def estimate_plan_timeline(plan_input: dict[str, Any]) -> dict[str, Any]:
    plants = [_normalize_plant(plant) for plant in plan_input.get("selected_plants", [])]
    planning_start = parse_optional_date(plan_input.get("target_start"), "target_start") or datetime.utcnow()
    preferred_completion = parse_optional_date(plan_input.get("target_completion"), "target_completion")
    max_establishment_weeks = max((plant["establishment_weeks"] for plant in plants), default=6)
    first_action = planning_start
    establishment_date = planning_start + timedelta(weeks=max_establishment_weeks)
    completion_date = preferred_completion or (establishment_date + timedelta(days=21))
    maintenance_mode_date = min(completion_date, establishment_date + timedelta(days=14))
    return {
        "planning_start": planning_start.date().isoformat(),
        "expected_first_action_date": first_action.date().isoformat(),
        "expected_establishment_date": establishment_date.date().isoformat(),
        "expected_completion_date": completion_date.date().isoformat(),
        "maintenance_mode_date": maintenance_mode_date.date().isoformat(),
        "timeline_confidence": "medium" if preferred_completion is None else "high",
    }


def estimate_plan_effort(plan_input: dict[str, Any]) -> dict[str, Any]:
    plants = [_normalize_plant(plant) for plant in plan_input.get("selected_plants", [])]
    locations = [_normalize_location(location) for location in plan_input.get("selected_locations", [])]
    total_quantity = sum(plant["quantity"] for plant in plants)
    base_hours = 2.0
    setup_hours = len(locations) * 1.5
    propagation_hours = sum(
        1.0 if plant["propagation_method"] in {"start", "starts", "transplant"} else 2.5
        for plant in plants
    )
    care_hours = sum(plant["maintenance_hours_per_week"] for plant in plants)
    total_hours = round(base_hours + setup_hours + propagation_hours + (care_hours * 4) + (0.25 * total_quantity), 2)
    weeks = max(_days_to_completion(plan_input) / 7.0, 1.0)
    avg_hours = round(total_hours / weeks, 2)
    peak_hours = round(max(avg_hours * 1.75, avg_hours + 1.5), 2)
    maintenance_hours = round(care_hours + max(len(locations) * 0.25, 0.5), 2)
    work_buckets = [
        {"name": "setup", "hours": round(base_hours + setup_hours, 2)},
        {"name": "propagation", "hours": round(propagation_hours, 2)},
        {"name": "care", "hours": round(care_hours * 4, 2)},
    ]
    return {
        "total_hours": total_hours,
        "avg_hours_per_week": avg_hours,
        "peak_hours_per_week": peak_hours,
        "maintenance_hours_per_week": maintenance_hours,
        "effort_confidence": "medium",
        "major_work_buckets": work_buckets,
    }


def check_plan_feasibility(plan_input: dict[str, Any]) -> dict[str, Any]:
    plants = [_normalize_plant(plant) for plant in plan_input.get("selected_plants", [])]
    locations = [_normalize_location(location) for location in plan_input.get("selected_locations", [])]
    budget_cap = plan_input.get("budget_cap")
    target_completion = parse_optional_date(plan_input.get("target_completion"), "target_completion")
    target_start = parse_optional_date(plan_input.get("target_start"), "target_start") or datetime.utcnow()
    tray_slots = int(plan_input.get("tray_slots", 0) or 0)
    tray_capacity = int(plan_input.get("tray_indoor_capacity", 0) or 0)

    violations: list[str] = []
    warnings: list[str] = []

    if not plants:
        violations.append("At least one selected plant is required.")
    if not locations:
        violations.append("At least one selected location is required.")
    if any(not location["available"] for location in locations):
        violations.append("One or more selected locations are unavailable.")
    if tray_capacity and tray_slots > tray_capacity:
        violations.append("Requested tray slots exceed indoor tray capacity.")

    if target_completion is not None:
        longest_lead = max((plant["establishment_weeks"] for plant in plants), default=0)
        projected_completion = target_start + timedelta(weeks=longest_lead)
        if projected_completion > target_completion:
            violations.append("Selected plants are unlikely to establish before the requested completion date.")

    cost_estimate = estimate_plan_cost(plan_input)
    if budget_cap is not None and cost_estimate["total_estimated_cost"] > float(budget_cap):
        violations.append("Estimated cost exceeds the stated budget cap.")

    for plant in plants:
        for location in locations:
            sunlight = (location["sunlight"] or "").lower()
            light_preference = (plant["light_preference"] or "").lower()
            if "shade" in sunlight and "sun" in light_preference:
                warnings.append(
                    f"{plant['name']} may struggle in {location['name']} because the location is shaded."
                )

    return {
        "is_feasible": not violations,
        "hard_constraint_violations": violations,
        "warnings": sorted(set(warnings)),
    }


def build_plan_input(
    *,
    project: GardeningProject,
    brief: ProjectBrief,
    profile: GardenProfile,
    selected_locations: list[dict[str, Any]],
    selected_plants: list[dict[str, Any]],
    propagation_strategy: Optional[dict[str, Any]] = None,
    maintenance_assumptions: Optional[dict[str, Any]] = None,
    resource_assumptions: Optional[dict[str, Any]] = None,
    budget_assumptions: Optional[dict[str, Any]] = None,
    timing_anchors: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "project_id": project.id,
        "target_start": datetime_to_iso(brief.target_start),
        "target_completion": datetime_to_iso(brief.target_completion),
        "budget_cap": brief.budget_cap,
        "tray_slots": project.tray_slots or 0,
        "tray_indoor_capacity": profile.tray_indoor_capacity or 0,
        "selected_locations": selected_locations,
        "selected_plants": selected_plants,
        "propagation_strategy": propagation_strategy or {},
        "maintenance_assumptions": maintenance_assumptions or {},
        "resource_assumptions": resource_assumptions or {},
        "budget_assumptions": budget_assumptions or {},
        "timing_anchors": timing_anchors or {"modes": ["calendar", "event"], "calendar": [], "event": []},
    }


def build_execution_spec_payload(proposal: ProjectProposal, brief: ProjectBrief) -> dict[str, Any]:
    timeline = proposal.timeline_estimate or {}
    normalized_plants = [_normalize_plant(plant) for plant in proposal.selected_plants or []]
    categories = [
        {
            "name": plant["name"],
            "annual": plant["annual"],
            "edible": plant["edible"],
            "task_profile": plant["task_profile"],
        }
        for plant in normalized_plants
    ]
    return {
        "selected_plants": normalized_plants,
        "selected_locations": [_normalize_location(location) for location in proposal.selected_locations or []],
        "propagation_strategy": proposal.propagation_strategy or {},
        "timing_windows": {
            "planning_start": timeline.get("planning_start"),
            "expected_first_action_date": timeline.get("expected_first_action_date"),
            "expected_establishment_date": timeline.get("expected_establishment_date"),
            "expected_completion_date": timeline.get("expected_completion_date"),
            "maintenance_mode_date": timeline.get("maintenance_mode_date"),
        },
        "maintenance_assumptions": proposal.maintenance_assumptions or {},
        "resource_assumptions": proposal.resource_assumptions or {},
        "budget_assumptions": proposal.budget_assumptions or {},
        "preferred_completion_target": brief.target_completion,
        "plant_categories": categories,
        "timing_anchors": proposal.timing_anchors or {"modes": ["calendar", "event"], "calendar": [], "event": []},
    }


def _milestone_tasks(execution_spec: dict[str, Any]) -> list[dict[str, Any]]:
    timeline = execution_spec["timing_windows"]
    first_action = timeline.get("expected_first_action_date")
    establish = timeline.get("expected_establishment_date")
    completion = timeline.get("expected_completion_date")
    tasks = []
    for plant in execution_spec["selected_plants"]:
        prefix = plant["name"]
        if plant["propagation_method"] in {"seed", "cutting", "propagation"}:
            tasks.append({
                "id": f"{prefix}-sow",
                "title": f"Sow {prefix}",
                "parent": "Propagation",
                "scheduled_date": first_action,
            })
            tasks.append({
                "id": f"{prefix}-pot-up",
                "title": f"Pot up {prefix} to red cups",
                "parent": "Propagation",
                "scheduled_date": establish,
            })
        else:
            tasks.append({
                "id": f"{prefix}-acquire",
                "title": f"Acquire {prefix} starts",
                "parent": "Setup",
                "scheduled_date": first_action,
            })
        tasks.append({
            "id": f"{prefix}-transplant",
            "title": f"Transplant {prefix} to final location",
            "parent": "Establishment",
            "scheduled_date": establish,
        })
        tasks.append({
            "id": f"{prefix}-harvest-check",
            "title": f"Check first harvest window for {prefix}",
            "parent": "Maintenance mode",
            "scheduled_date": completion,
        })
    return tasks


def _dependency_links(tasks: list[dict[str, Any]]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    tasks_by_prefix: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        prefix = task["id"].split("-")[0]
        tasks_by_prefix.setdefault(prefix, []).append(task)
    for group in tasks_by_prefix.values():
        ordered = group
        for previous, current in zip(ordered, ordered[1:]):
            links.append({"blocking_task_id": previous["id"], "blocked_task_id": current["id"]})
    return links


def _recurring_rules(execution_spec: dict[str, Any]) -> list[dict[str, Any]]:
    maintenance_mode_date = execution_spec["timing_windows"].get("maintenance_mode_date")
    rules = []
    for plant in execution_spec["selected_plants"]:
        name = plant["name"]
        task_profile = plant["task_profile"]
        watering_every_days = 2 if task_profile in {"fruiting_vine", "fruiting_bush"} else 3
        rules.append({
            "series_key": f"{name}-watering",
            "title": f"Water {name}",
            "cadence": f"every {watering_every_days} days",
            "start_condition": {"type": "calendar", "date": maintenance_mode_date},
            "end_condition": {"type": "season_end"},
            "sample_next_due_date": maintenance_mode_date,
        })
        rules.append({
            "series_key": f"{name}-inspection",
            "title": f"Inspect {name} for pests",
            "cadence": "weekly",
            "start_condition": {"type": "calendar", "date": maintenance_mode_date},
            "end_condition": {"type": "season_end"},
            "sample_next_due_date": maintenance_mode_date,
        })
    return rules


def generate_schedule_preview(execution_spec: dict[str, Any]) -> dict[str, Any]:
    milestone_tasks = _milestone_tasks(execution_spec)
    dependency_links = _dependency_links(milestone_tasks)
    recurring_rules = _recurring_rules(execution_spec)
    tree = {
        "Setup": [task for task in milestone_tasks if task["parent"] == "Setup"],
        "Propagation": [task for task in milestone_tasks if task["parent"] == "Propagation"],
        "Establishment": [task for task in milestone_tasks if task["parent"] == "Establishment"],
        "Maintenance mode": [task for task in milestone_tasks if task["parent"] == "Maintenance mode"],
    }
    return {
        "milestone_tasks": milestone_tasks,
        "dependency_links": dependency_links,
        "recurring_rules": recurring_rules,
        "tree": tree,
    }


def format_planning_context(context: dict[str, Any]) -> str:
    lines = [
        f"Planning context for project {context['project']['name']} ({context['project']['id']}):",
        "",
        f"Goal: {context['brief']['goal']}",
        f"Desired outcome: {context['brief']['desired_outcome'] or 'not set'}",
        f"Budget cap: ${context['brief']['budget_cap'] if context['brief']['budget_cap'] is not None else 'not set'}",
        f"Target completion: {context['brief']['target_completion'] or 'not set'}",
        "",
        "Candidate locations:",
    ]
    available_locations = context["candidate_locations"] or []
    if available_locations:
        for location in available_locations:
            availability = "available" if location["available"] else "unavailable"
            lines.append(
                f"- {location['name']} ({location['location_type']}) | "
                f"sunlight: {location['sunlight'] or 'unknown'} | "
                f"soil: {location['soil_type'] or 'unknown'} | {availability}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "Candidate plant material:"])
    plants = context["candidate_plant_material"]["plants"]
    batches = context["candidate_plant_material"]["batches"]
    if plants:
        lines.extend(f"- Plant: {plant['name']} {plant.get('variety') or ''} ({plant['status']})".rstrip() for plant in plants)
    if batches:
        lines.extend(f"- Batch: {batch['name']} ({batch['plant_name']})" for batch in batches)
    if not plants and not batches:
        lines.append("- none")
    return "\n".join(lines)


def format_proposal(proposal: ProjectProposal) -> str:
    cost = proposal.cost_estimate or {}
    timeline = proposal.timeline_estimate or {}
    effort = proposal.effort_estimate or {}
    lines = [
        proposal.to_summary(),
        "",
        f"Recommended approach: {proposal.recommended_approach}",
        f"Tradeoffs: {', '.join(proposal.tradeoffs or ['none'])}",
        f"Risks: {', '.join(proposal.risks or ['none'])}",
        f"Completion target: {timeline.get('expected_completion_date', 'not set')}",
        (
            "Effort: "
            f"{effort.get('total_hours', 'not set')} total hours | "
            f"{effort.get('avg_hours_per_week', 'not set')} hrs/week average | "
            f"{effort.get('peak_hours_per_week', 'not set')} hrs/week peak | "
            f"{effort.get('maintenance_hours_per_week', 'not set')} hrs/week maintenance"
        ),
        f"Cost confidence: {cost.get('cost_confidence', 'unknown')}",
        f"Timeline confidence: {timeline.get('timeline_confidence', 'unknown')}",
    ]
    return "\n".join(lines)


def format_schedule_preview(preview: dict[str, Any]) -> str:
    lines = ["Project schedule preview:", ""]
    for section, tasks in preview["tree"].items():
        lines.append(f"{section}:")
        if not tasks:
            lines.append("  - none")
            continue
        for task in tasks:
            lines.append(f"  - {task['scheduled_date']}: {task['title']}")
        lines.append("")

    lines.append("Recurring care rules:")
    if preview["recurring_rules"]:
        for rule in preview["recurring_rules"]:
            lines.append(
                f"  - {rule['title']} | {rule['cadence']} | starts {rule['sample_next_due_date']}"
            )
    else:
        lines.append("  - none")

    lines.append("")
    lines.append("Dependencies:")
    if preview["dependency_links"]:
        for link in preview["dependency_links"]:
            lines.append(f"  - {link['blocking_task_id']} -> {link['blocked_task_id']}")
    else:
        lines.append("  - none")
    return "\n".join(lines)
