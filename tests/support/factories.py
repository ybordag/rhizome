from __future__ import annotations

from datetime import datetime
from typing import Any

from db.models import (
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
    Task,
    TaskDependency,
    TaskGenerationRun,
    TaskSeries,
)


def _persist(session, obj):
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def make_profile(session, **overrides: Any) -> GardenProfile:
    data = {
        "user_id": 1,
        "climate_zone": "9b",
        "frost_date_last_spring": "January 15",
        "frost_date_first_fall": "November 30",
        "soil_type": "hard clay",
        "tray_capacity": 10,
        "tray_indoor_capacity": 6,
        "hard_constraints": {"pets": "dog"},
        "soft_preferences": {"organic": True},
        "notes": "Established garden profile.",
    }
    data.update(overrides)
    profile = GardenProfile(**data)
    return _persist(session, profile)


def make_project(session, profile: GardenProfile, **overrides: Any) -> GardeningProject:
    data = {
        "user_id": 1,
        "garden_profile_id": profile.id,
        "name": "Tomato Project",
        "goal": "Grow enough tomatoes for sauce.",
        "status": "planning",
        "tray_slots": 4,
        "budget_ceiling": 120.0,
        "approved_plan": {"notes": "Start indoors in February."},
        "negotiation_history": [],
        "iterations": [],
        "notes": "Project notes.",
    }
    data.update(overrides)
    project = GardeningProject(**data)
    return _persist(session, project)


def make_project_brief(session, project: GardeningProject, **overrides: Any) -> ProjectBrief:
    data = {
        "project_id": project.id,
        "status": "ready_for_proposal",
        "goal": project.goal,
        "desired_outcome": "Healthy summer harvest by July.",
        "target_start": datetime(2026, 4, 1),
        "target_completion": datetime(2026, 7, 1),
        "budget_cap": project.budget_ceiling,
        "effort_preference": "medium",
        "propagation_preference": "seed",
        "priority_preferences": ["cost", "yield"],
        "notes": "Planner brief notes.",
    }
    data.update(overrides)
    brief = ProjectBrief(**data)
    return _persist(session, brief)


def make_project_proposal(
    session,
    project: GardeningProject,
    brief: ProjectBrief,
    **overrides: Any,
) -> ProjectProposal:
    data = {
        "project_id": project.id,
        "brief_id": brief.id,
        "version": 1,
        "status": "proposed",
        "title": "Balanced seed-start plan",
        "summary": "Use growbags and seed starts for a July harvest.",
        "recommended_approach": "Seed start tomatoes and direct sow basil.",
        "selected_locations": [{"location_type": "container", "location_id": "c1", "name": "Growbag 1"}],
        "selected_plants": [{"name": "Tomato", "quantity": 2, "propagation_method": "seed"}],
        "material_strategy": {"reuse_existing": True},
        "propagation_strategy": {"primary": "seed"},
        "assumptions": ["Outdoor hardening-off is available."],
        "tradeoffs": ["Lower cost, more labor"],
        "risks": ["Late transplanting shortens the season."],
        "feasibility_notes": ["Fits the current budget."],
        "cost_estimate": {"total_estimated_cost": 50.0, "cost_confidence": "medium"},
        "timeline_estimate": {"expected_completion_date": "2026-07-01", "timeline_confidence": "medium"},
        "effort_estimate": {
            "total_hours": 12.0,
            "avg_hours_per_week": 1.5,
            "peak_hours_per_week": 3.0,
            "maintenance_hours_per_week": 1.0,
        },
        "maintenance_assumptions": {"watering": "every 2 days"},
        "resource_assumptions": {"tray_slots": 4},
        "budget_assumptions": {"contingency": 5.0},
        "timing_anchors": {"modes": ["calendar", "event"], "calendar": [], "event": []},
    }
    data.update(overrides)
    proposal = ProjectProposal(**data)
    return _persist(session, proposal)


def make_project_revision(
    session,
    project: GardeningProject,
    proposal: ProjectProposal,
    **overrides: Any,
) -> ProjectRevision:
    data = {
        "project_id": project.id,
        "source_proposal_id": proposal.id,
        "revision_number": 1,
        "status": "active",
        "approved_plan": {"proposal_id": proposal.id, "title": proposal.title},
    }
    data.update(overrides)
    revision = ProjectRevision(**data)
    return _persist(session, revision)


def make_project_execution_spec(
    session,
    project: GardeningProject,
    revision: ProjectRevision,
    **overrides: Any,
) -> ProjectExecutionSpec:
    data = {
        "project_id": project.id,
        "revision_id": revision.id,
        "status": "active",
        "selected_plants": [
            {
                "name": "Tomato",
                "quantity": 2,
                "propagation_method": "seed",
                "task_profile": "fruiting_vine",
                "maintenance_hours_per_week": 1.5,
                "event_triggers": [],
            }
        ],
        "selected_locations": [{"location_type": "container", "location_id": "c1", "name": "Growbag 1"}],
        "propagation_strategy": {"primary": "seed"},
        "timing_windows": {
            "planning_start": "2026-04-01",
            "expected_first_action_date": "2026-04-01",
            "expected_establishment_date": "2026-05-20",
            "expected_completion_date": "2026-07-01",
            "maintenance_mode_date": "2026-06-01",
        },
        "maintenance_assumptions": {"watering": "every 2 days"},
        "resource_assumptions": {"tray_slots": 4},
        "budget_assumptions": {"contingency": 5.0},
        "preferred_completion_target": datetime(2026, 7, 1),
        "plant_categories": [{"name": "Tomato", "annual": True, "edible": True}],
        "timing_anchors": {"modes": ["calendar", "event"], "calendar": [], "event": []},
    }
    data.update(overrides)
    spec = ProjectExecutionSpec(**data)
    return _persist(session, spec)


def make_task_generation_run(
    session,
    project: GardeningProject,
    revision: ProjectRevision,
    **overrides: Any,
) -> TaskGenerationRun:
    data = {
        "project_id": project.id,
        "revision_id": revision.id,
        "run_type": "initial",
        "status": "complete",
        "source_event_id": None,
        "summary": f"Generated tasks for {project.name}.",
        "run_metadata": {"reason": "test"},
    }
    data.update(overrides)
    run = TaskGenerationRun(**data)
    return _persist(session, run)


def make_task(
    session,
    project: GardeningProject,
    revision: ProjectRevision,
    generation_run: TaskGenerationRun,
    **overrides: Any,
) -> Task:
    data = {
        "project_id": project.id,
        "revision_id": revision.id,
        "generation_run_id": generation_run.id,
        "parent_task_id": None,
        "series_id": None,
        "source_type": "generated",
        "generator_key": "test.task",
        "title": "Test task",
        "description": "Test task description.",
        "type": "milestone",
        "status": "pending",
        "scheduled_date": datetime(2026, 4, 15),
        "earliest_start": datetime(2026, 4, 14),
        "window_start": datetime(2026, 4, 14),
        "window_end": datetime(2026, 4, 16),
        "deadline": datetime(2026, 4, 16),
        "completed_at": None,
        "deferred_until": None,
        "estimated_minutes": 30,
        "actual_minutes": None,
        "reversible": True,
        "what_happens_if_skipped": "The task will be missed.",
        "what_happens_if_delayed": "Follow-on work may slip.",
        "notes": "Task notes.",
        "event_anchor_type": None,
        "event_anchor_subject_type": None,
        "event_anchor_subject_id": None,
        "event_anchor_offset_days": None,
        "is_user_modified": False,
    }
    data.update(overrides)
    task = Task(**data)
    return _persist(session, task)


def make_task_series(
    session,
    project: GardeningProject,
    revision: ProjectRevision,
    generation_run: TaskGenerationRun,
    **overrides: Any,
) -> TaskSeries:
    data = {
        "project_id": project.id,
        "revision_id": revision.id,
        "generation_run_id": generation_run.id,
        "parent_task_id": None,
        "source_type": "generated",
        "generator_key": "test.series",
        "title": "Water tomatoes",
        "description": "Recurring watering rule.",
        "type": "maintenance",
        "cadence": "every 2 days",
        "cadence_days": 2,
        "start_condition": {"type": "calendar", "date": "2026-04-15"},
        "end_condition": {"type": "season_end"},
        "linked_subjects": [{"subject_type": "project", "subject_id": project.id, "role": "affected"}],
        "default_estimated_minutes": 10,
        "next_generation_date": datetime(2026, 4, 15),
        "active": True,
    }
    data.update(overrides)
    series = TaskSeries(**data)
    return _persist(session, series)


def make_task_dependency(
    session,
    blocking_task: Task,
    blocked_task: Task,
    **overrides: Any,
) -> TaskDependency:
    data = {
        "blocking_task_id": blocking_task.id,
        "blocked_task_id": blocked_task.id,
        "dependency_type": "finish_to_start",
    }
    data.update(overrides)
    dependency = TaskDependency(**data)
    return _persist(session, dependency)


def make_bed(session, profile: GardenProfile, **overrides: Any) -> Bed:
    data = {
        "user_id": 1,
        "garden_profile_id": profile.id,
        "name": "Courtyard Bed",
        "location": "courtyard",
        "sunlight": "full sun",
        "soil_type": "loam",
        "dimensions_sqft": 24.0,
        "notes": "Mulched heavily.",
    }
    data.update(overrides)
    bed = Bed(**data)
    return _persist(session, bed)


def make_container(session, profile: GardenProfile, **overrides: Any) -> Container:
    data = {
        "user_id": 1,
        "garden_profile_id": profile.id,
        "name": "Growbag 1",
        "container_type": "growbag",
        "size_gallons": 15.0,
        "location": "front",
        "is_mobile": True,
        "notes": "Black fabric growbag.",
    }
    data.update(overrides)
    container = Container(**data)
    return _persist(session, container)


def make_batch(
    session,
    profile: GardenProfile,
    project: GardeningProject | None = None,
    **overrides: Any,
) -> PlantBatch:
    data = {
        "user_id": 1,
        "garden_profile_id": profile.id,
        "project_id": project.id if project else None,
        "name": "Cosmos Spring 2026",
        "plant_name": "Cosmos",
        "variety": "Apricotta",
        "quantity_sown": 6,
        "source": "seed",
        "sow_date": datetime(2026, 2, 15),
        "supplier": "Baker Creek",
        "supplier_reference": "LOT-42",
        "grow_light": "light_1",
        "tray": "tray_A",
        "notes": "Batch notes.",
    }
    data.update(overrides)
    batch = PlantBatch(**data)
    return _persist(session, batch)


def make_plant(
    session,
    profile: GardenProfile,
    batch: PlantBatch | None = None,
    container: Container | None = None,
    bed: Bed | None = None,
    **overrides: Any,
) -> Plant:
    data = {
        "user_id": 1,
        "garden_profile_id": profile.id,
        "batch_id": batch.id if batch else None,
        "name": "Tomato",
        "variety": "Sungold",
        "quantity": 1,
        "container_id": container.id if container else None,
        "bed_id": bed.id if bed else None,
        "source": "seed",
        "status": "seedling",
        "sow_date": datetime(2026, 2, 15),
        "red_cup_date": datetime(2026, 3, 1),
        "transplant_date": None,
        "is_flowering": False,
        "is_fruiting": False,
        "fertilizing_schedule": "weekly",
        "last_fertilized_at": datetime(2026, 3, 10),
        "special_instructions": "Pinch suckers.",
        "notes": "Plant notes.",
    }
    data.update(overrides)
    plant = Plant(**data)
    return _persist(session, plant)


def link_bed_to_project(session, project: GardeningProject, bed: Bed) -> ProjectBed:
    link = ProjectBed(project_id=project.id, bed_id=bed.id)
    return _persist(session, link)


def link_container_to_project(
    session, project: GardeningProject, container: Container
) -> ProjectContainer:
    link = ProjectContainer(project_id=project.id, container_id=container.id)
    return _persist(session, link)


def link_plant_to_project(
    session,
    project: GardeningProject,
    plant: Plant,
    **overrides: Any,
) -> ProjectPlant:
    link = ProjectPlant(
        project_id=project.id,
        plant_id=plant.id,
        notes=overrides.pop("notes", None),
        removed_at=overrides.pop("removed_at", None),
        **overrides,
    )
    return _persist(session, link)
