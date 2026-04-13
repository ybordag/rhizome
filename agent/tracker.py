from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from agent.activity_log import (
    DEFAULT_ACTOR_LABEL,
    DEFAULT_ACTOR_TYPE,
    record_activity_event,
    record_create_event,
    record_update_event,
    snapshot_model,
)
from agent.planner import DEFAULT_PLANT_RULES
from db.models import (
    ActivityEvent,
    ActivitySubject,
    GardeningProject,
    ProjectExecutionSpec,
    ProjectRevision,
    Task,
    TaskDependency,
    TaskGenerationRun,
    TaskSeries,
)


VALID_TASK_SOURCE_TYPES = {"generated", "manual", "generated_override"}
VALID_TASK_TYPES = {"milestone", "maintenance", "emergency", "opportunistic"}
VALID_TASK_STATUSES = {"pending", "in_progress", "done", "skipped", "deferred", "blocked", "superseded"}
VALID_TASK_RUN_TYPES = {"initial", "regeneration", "event_followup"}
VALID_TASK_RUN_STATUSES = {"complete", "superseded", "failed"}

SECTION_LABELS = [
    "Setup",
    "Propagation",
    "Establishment",
    "Ongoing care",
    "Maintenance mode / harvest",
]
ROLLING_TASK_HORIZON_DAYS = 14


def _parse_date_value(value: Optional[Any]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError(f"Unsupported datetime value: {value!r}")


def _date_only_iso(value: Optional[datetime]) -> str:
    return value.date().isoformat() if value else "not set"


def _plant_rule(name: str) -> dict[str, Any]:
    return DEFAULT_PLANT_RULES.get(
        name.lower(),
        {
            "lead_weeks": 6,
            "establishment_weeks": 9,
            "maintenance_hours_per_week": 0.75,
            "seed_unit_cost": 0.5,
            "start_unit_cost": 4.0,
            "support_cost": 2.0,
            "task_profile": "general",
        },
    )


def _normalize_plant(plant: dict[str, Any]) -> dict[str, Any]:
    rule = _plant_rule(str(plant.get("name") or ""))
    return {
        "name": plant.get("name") or "Unnamed plant",
        "quantity": int(plant.get("quantity", 1) or 1),
        "propagation_method": plant.get("propagation_method") or plant.get("source") or "seed",
        "task_profile": plant.get("task_profile") or rule["task_profile"],
        "event_triggers": list(plant.get("event_triggers") or []),
        "maintenance_hours_per_week": float(
            plant.get("maintenance_hours_per_week", rule["maintenance_hours_per_week"])
            or rule["maintenance_hours_per_week"]
        ),
    }


def _normalize_location(location: dict[str, Any]) -> dict[str, Any]:
    return {
        "location_type": location.get("location_type") or location.get("type") or "container",
        "location_id": location.get("location_id") or location.get("id") or "unknown-location",
        "name": location.get("name") or "Unnamed location",
        "available": location.get("available", True),
        "sunlight": location.get("sunlight") or "unknown",
        "soil_type": location.get("soil_type") or "unknown",
    }


def _execution_spec_dict(spec: ProjectExecutionSpec) -> dict[str, Any]:
    return {
        "project_id": spec.project_id,
        "revision_id": spec.revision_id,
        "selected_plants": [_normalize_plant(plant) for plant in (spec.selected_plants or [])],
        "selected_locations": [_normalize_location(location) for location in (spec.selected_locations or [])],
        "propagation_strategy": spec.propagation_strategy or {},
        "timing_windows": spec.timing_windows or {},
        "maintenance_assumptions": spec.maintenance_assumptions or {},
        "resource_assumptions": spec.resource_assumptions or {},
        "budget_assumptions": spec.budget_assumptions or {},
        "preferred_completion_target": spec.preferred_completion_target,
        "plant_categories": spec.plant_categories or [],
        "timing_anchors": spec.timing_anchors or {"modes": ["calendar", "event"], "calendar": [], "event": []},
    }


def _task_subject(task_id: str, role: str = "primary") -> dict[str, str]:
    return {"subject_type": "task", "subject_id": task_id, "role": role}


def _series_subject(series_id: str, role: str = "primary") -> dict[str, str]:
    return {"subject_type": "task_series", "subject_id": series_id, "role": role}


def _run_subject(run_id: str, role: str = "primary") -> dict[str, str]:
    return {"subject_type": "task_generation_run", "subject_id": run_id, "role": role}


def _select_project(session, project_id: str) -> GardeningProject:
    project = session.query(GardeningProject).filter(GardeningProject.id == project_id).first()
    if not project:
        raise ValueError(f"No project found with id {project_id}.")
    return project


def _select_revision_and_spec(
    session,
    *,
    project_id: str,
    revision_id: Optional[str] = None,
) -> tuple[ProjectRevision, ProjectExecutionSpec]:
    if revision_id:
        revision = (
            session.query(ProjectRevision)
            .filter(ProjectRevision.id == revision_id, ProjectRevision.project_id == project_id)
            .first()
        )
    else:
        revision = (
            session.query(ProjectRevision)
            .filter(ProjectRevision.project_id == project_id, ProjectRevision.status == "active")
            .order_by(ProjectRevision.revision_number.desc())
            .first()
        )
    if not revision:
        raise ValueError(f"No accepted revision found for project {project_id}.")

    spec = (
        session.query(ProjectExecutionSpec)
        .filter(
            ProjectExecutionSpec.project_id == project_id,
            ProjectExecutionSpec.revision_id == revision.id,
            ProjectExecutionSpec.status == "active",
        )
        .order_by(ProjectExecutionSpec.updated_at.desc())
        .first()
    )
    if not spec:
        raise ValueError(f"No active execution spec found for revision {revision.id}.")
    return revision, spec


def _section_key(label: str) -> str:
    return label.lower().replace(" ", "_").replace("/", "_")


def _is_section_task(task: Task) -> bool:
    return task.generator_key.startswith("section.")


def _event_anchor_label(event_type: str) -> str:
    return event_type.replace("_", " ")


def _find_trigger_event(
    session,
    *,
    project_id: str,
    event_type: str,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
) -> Optional[ActivityEvent]:
    query = session.query(ActivityEvent).filter(
        ActivityEvent.project_id == project_id,
        ActivityEvent.event_type == event_type,
    )
    if subject_type and subject_id:
        query = (
            query.join(ActivitySubject, ActivityEvent.id == ActivitySubject.event_id)
            .filter(
                ActivitySubject.subject_type == subject_type,
                ActivitySubject.subject_id == subject_id,
            )
        )
    return query.order_by(ActivityEvent.created_at.desc()).first()


def _timeline_dates(execution_spec: dict[str, Any]) -> dict[str, datetime]:
    windows = execution_spec.get("timing_windows") or {}
    now = datetime.utcnow()
    planning_start = _parse_date_value(windows.get("planning_start")) or now
    first_action = _parse_date_value(windows.get("expected_first_action_date")) or planning_start
    establishment = _parse_date_value(windows.get("expected_establishment_date")) or (first_action + timedelta(days=21))
    maintenance = _parse_date_value(windows.get("maintenance_mode_date")) or establishment
    completion = _parse_date_value(windows.get("expected_completion_date")) or (maintenance + timedelta(days=30))
    return {
        "planning_start": planning_start,
        "first_action": first_action,
        "establishment": establishment,
        "maintenance": maintenance,
        "completion": completion,
    }


def _task_blueprints(
    session,
    *,
    project_id: str,
    execution_spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, Any]]]:
    dates = _timeline_dates(execution_spec)
    tasks: list[dict[str, Any]] = []
    dependencies: list[dict[str, str]] = []
    recurring_rules: list[dict[str, Any]] = []

    for location in execution_spec["selected_locations"]:
        linked_subjects = [{"subject_type": "project", "subject_id": project_id, "role": "affected"}]
        if location["location_type"] in {"bed", "container"} and location["location_id"] != "unknown-location":
            linked_subjects.append(
                {
                    "subject_type": location["location_type"],
                    "subject_id": location["location_id"],
                    "role": "primary",
                }
            )
        key = f"prepare.{location['location_type']}.{location['location_id']}"
        tasks.append(
            {
                "generator_key": key,
                "title": f"Prepare {location['name']}",
                "description": f"Prepare {location['name']} for planting.",
                "section": "Setup",
                "type": "milestone",
                "scheduled_date": dates["first_action"],
                "earliest_start": dates["planning_start"],
                "window_start": dates["planning_start"],
                "window_end": dates["first_action"],
                "deadline": dates["first_action"],
                "estimated_minutes": 45,
                "reversible": True,
                "what_happens_if_skipped": "The final planting location may not be ready on time.",
                "what_happens_if_delayed": "Transplant timing may slip and compress the schedule.",
                "notes": f"Location type: {location['location_type']}.",
                "linked_subjects": linked_subjects,
            }
        )

    for plant in execution_spec["selected_plants"]:
        name = plant["name"]
        propagation = plant["propagation_method"]
        plant_key = name.lower().replace(" ", "_")
        task_profile = plant["task_profile"]
        trigger_map = {trigger.get("event_type"): trigger for trigger in plant.get("event_triggers", [])}
        location_subjects = [{"subject_type": "project", "subject_id": project_id, "role": "affected"}]
        for location in execution_spec["selected_locations"]:
            if location["location_type"] in {"bed", "container"} and location["location_id"] != "unknown-location":
                location_subjects.append(
                    {
                        "subject_type": location["location_type"],
                        "subject_id": location["location_id"],
                        "role": "affected",
                    }
                )

        if propagation in {"seed", "cutting", "propagation"}:
            tasks.append(
                {
                    "generator_key": f"{plant_key}.sow",
                    "title": f"Sow {name}",
                    "description": f"Start {name} from {propagation}.",
                    "section": "Propagation",
                    "type": "milestone",
                    "scheduled_date": dates["first_action"],
                    "earliest_start": dates["planning_start"],
                    "window_start": dates["planning_start"],
                    "window_end": dates["first_action"] + timedelta(days=2),
                    "deadline": dates["first_action"] + timedelta(days=2),
                    "estimated_minutes": 20,
                    "reversible": True,
                    "what_happens_if_skipped": f"{name} will not enter the propagation pipeline.",
                    "what_happens_if_delayed": f"{name} may miss the target completion window.",
                    "notes": "Seed/cutting propagation milestone.",
                    "linked_subjects": location_subjects,
                }
            )
            tasks.append(
                {
                    "generator_key": f"{plant_key}.pot_up",
                    "title": f"Pot up {name} to red cups",
                    "description": f"Move {name} into larger interim containers.",
                    "section": "Propagation",
                    "type": "milestone",
                    "scheduled_date": dates["first_action"] + timedelta(days=14),
                    "earliest_start": dates["first_action"] + timedelta(days=10),
                    "window_start": dates["first_action"] + timedelta(days=10),
                    "window_end": dates["first_action"] + timedelta(days=18),
                    "deadline": dates["first_action"] + timedelta(days=18),
                    "estimated_minutes": 25,
                    "reversible": True,
                    "what_happens_if_skipped": "Seedlings may become root-bound before transplanting.",
                    "what_happens_if_delayed": "The transplant schedule may tighten.",
                    "notes": "Intermediate propagation milestone.",
                    "linked_subjects": location_subjects,
                }
            )
        else:
            tasks.append(
                {
                    "generator_key": f"{plant_key}.acquire_starts",
                    "title": f"Acquire {name} starts",
                    "description": f"Buy or source {name} starts.",
                    "section": "Setup",
                    "type": "milestone",
                    "scheduled_date": dates["first_action"],
                    "earliest_start": dates["planning_start"],
                    "window_start": dates["planning_start"],
                    "window_end": dates["first_action"] + timedelta(days=3),
                    "deadline": dates["first_action"] + timedelta(days=3),
                    "estimated_minutes": 30,
                    "reversible": True,
                    "what_happens_if_skipped": f"{name} will not be available to transplant.",
                    "what_happens_if_delayed": "The establishment timeline may slip.",
                    "notes": "Nursery/transplant acquisition milestone.",
                    "linked_subjects": location_subjects,
                }
            )

        germinated_trigger = trigger_map.get("plant_germinated")
        if germinated_trigger:
            offset_days = int(germinated_trigger.get("offset_days", 14) or 14)
            event = _find_trigger_event(
                session,
                project_id=project_id,
                event_type="plant_germinated",
                subject_type=germinated_trigger.get("subject_type"),
                subject_id=germinated_trigger.get("subject_id"),
            )
            scheduled = event.created_at + timedelta(days=offset_days) if event else None
            tasks.append(
                {
                    "generator_key": f"{plant_key}.event_transplant",
                    "title": f"Transplant {name} to final location",
                    "description": f"Transplant {name} once germination is established.",
                    "section": "Establishment",
                    "type": "milestone",
                    "scheduled_date": scheduled or dates["establishment"],
                    "earliest_start": scheduled or dates["establishment"],
                    "window_start": scheduled or dates["establishment"],
                    "window_end": (scheduled or dates["establishment"]) + timedelta(days=2)
                    if (scheduled or dates["establishment"])
                    else None,
                    "deadline": (scheduled or dates["establishment"]) + timedelta(days=2)
                    if (scheduled or dates["establishment"])
                    else None,
                    "estimated_minutes": 30,
                    "reversible": False,
                    "what_happens_if_skipped": f"{name} may not establish in its final location.",
                    "what_happens_if_delayed": "The harvest window may move later into the season.",
                    "notes": f"Anchored to plant_germinated + {offset_days} days.",
                    "linked_subjects": location_subjects,
                    "event_anchor_type": "plant_germinated",
                    "event_anchor_subject_type": germinated_trigger.get("subject_type"),
                    "event_anchor_subject_id": germinated_trigger.get("subject_id"),
                    "event_anchor_offset_days": offset_days,
                    "status": "pending" if event else "blocked",
                }
            )
        else:
            tasks.append(
                {
                    "generator_key": f"{plant_key}.transplant",
                    "title": f"Transplant {name} to final location",
                    "description": f"Move {name} into its final location.",
                    "section": "Establishment",
                    "type": "milestone",
                    "scheduled_date": dates["establishment"],
                    "earliest_start": dates["establishment"] - timedelta(days=2),
                    "window_start": dates["establishment"] - timedelta(days=2),
                    "window_end": dates["establishment"] + timedelta(days=3),
                    "deadline": dates["establishment"] + timedelta(days=3),
                    "estimated_minutes": 30,
                    "reversible": False,
                    "what_happens_if_skipped": f"{name} may never establish outdoors.",
                    "what_happens_if_delayed": "The establishment and harvest windows may slip.",
                    "notes": "Calendar-anchored transplant milestone.",
                    "linked_subjects": location_subjects,
                }
            )

        if task_profile in {"fruiting_vine", "fruiting_bush"}:
            tasks.append(
                {
                    "generator_key": f"{plant_key}.supports",
                    "title": f"Install supports for {name}",
                    "description": f"Set up trellis or supports for {name}.",
                    "section": "Establishment",
                    "type": "milestone",
                    "scheduled_date": dates["establishment"] + timedelta(days=1),
                    "earliest_start": dates["establishment"],
                    "window_start": dates["establishment"],
                    "window_end": dates["establishment"] + timedelta(days=5),
                    "deadline": dates["establishment"] + timedelta(days=5),
                    "estimated_minutes": 35,
                    "reversible": True,
                    "what_happens_if_skipped": f"{name} may sprawl or break under growth.",
                    "what_happens_if_delayed": "Later support installation can damage roots or stems.",
                    "notes": "Support installation milestone.",
                    "linked_subjects": location_subjects,
                }
            )

        transplanted_trigger = trigger_map.get("plant_transplanted")
        if transplanted_trigger:
            offset_days = int(transplanted_trigger.get("offset_days", 14) or 14)
            event = _find_trigger_event(
                session,
                project_id=project_id,
                event_type="plant_transplanted",
                subject_type=transplanted_trigger.get("subject_type"),
                subject_id=transplanted_trigger.get("subject_id"),
            )
            scheduled = event.created_at + timedelta(days=offset_days) if event else None
            tasks.append(
                {
                    "generator_key": f"{plant_key}.followup_fertilize",
                    "title": f"Fertilize {name} after transplant",
                    "description": f"Apply the first post-transplant feed to {name}.",
                    "section": "Ongoing care",
                    "type": "maintenance",
                    "scheduled_date": scheduled,
                    "earliest_start": scheduled,
                    "window_start": scheduled,
                    "window_end": scheduled + timedelta(days=2) if scheduled else None,
                    "deadline": scheduled + timedelta(days=2) if scheduled else None,
                    "estimated_minutes": 15,
                    "reversible": True,
                    "what_happens_if_skipped": f"{name} may establish more slowly after transplant.",
                    "what_happens_if_delayed": "Early nutrient support may arrive late.",
                    "notes": f"Anchored to plant_transplanted + {offset_days} days.",
                    "linked_subjects": location_subjects,
                    "event_anchor_type": "plant_transplanted",
                    "event_anchor_subject_type": transplanted_trigger.get("subject_type"),
                    "event_anchor_subject_id": transplanted_trigger.get("subject_id"),
                    "event_anchor_offset_days": offset_days,
                    "status": "pending" if event else "blocked",
                }
            )

        tasks.append(
            {
                "generator_key": f"{plant_key}.harvest_window",
                "title": f"Check first harvest window for {name}",
                "description": f"Review whether {name} has entered a productive phase.",
                "section": "Maintenance mode / harvest",
                "type": "milestone",
                "scheduled_date": dates["completion"],
                "earliest_start": dates["completion"] - timedelta(days=2),
                "window_start": dates["completion"] - timedelta(days=2),
                "window_end": dates["completion"] + timedelta(days=7),
                "deadline": dates["completion"] + timedelta(days=7),
                "estimated_minutes": 15,
                "reversible": True,
                "what_happens_if_skipped": "The first harvest window may be missed.",
                "what_happens_if_delayed": "Quality checks and harvest planning may slide.",
                "notes": "Harvest readiness checkpoint.",
                "linked_subjects": location_subjects,
            }
        )

        care_start = dates["maintenance"]
        watering_days = 2 if task_profile in {"fruiting_vine", "fruiting_bush"} else 3
        recurring_rules.append(
            {
                "generator_key": f"{plant_key}.watering",
                "title": f"Water {name}",
                "description": f"Check moisture and water {name}.",
                "type": "maintenance",
                "cadence": f"every {watering_days} days",
                "cadence_days": watering_days,
                "start_condition": {"type": "calendar", "date": care_start.date().isoformat()},
                "end_condition": {"type": "season_end"},
                "linked_subjects": location_subjects,
                "default_estimated_minutes": 10,
                "next_generation_date": care_start,
            }
        )
        recurring_rules.append(
            {
                "generator_key": f"{plant_key}.inspection",
                "title": f"Inspect {name} for pests",
                "description": f"Inspect {name} for pests or disease pressure.",
                "type": "maintenance",
                "cadence": "weekly",
                "cadence_days": 7,
                "start_condition": {"type": "calendar", "date": care_start.date().isoformat()},
                "end_condition": {"type": "season_end"},
                "linked_subjects": location_subjects,
                "default_estimated_minutes": 10,
                "next_generation_date": care_start,
            }
        )
        recurring_rules.append(
            {
                "generator_key": f"{plant_key}.fertilizing",
                "title": f"Fertilize {name}",
                "description": f"Feed {name} according to the care plan.",
                "type": "maintenance",
                "cadence": "every 14 days",
                "cadence_days": 14,
                "start_condition": {"type": "calendar", "date": care_start.date().isoformat()},
                "end_condition": {"type": "season_end"},
                "linked_subjects": location_subjects,
                "default_estimated_minutes": 12,
                "next_generation_date": care_start,
            }
        )
        if task_profile == "fruiting_vine":
            recurring_rules.append(
                {
                    "generator_key": f"{plant_key}.pruning",
                    "title": f"Prune {name}",
                    "description": f"Prune or manage growth habit for {name}.",
                    "type": "maintenance",
                    "cadence": "weekly",
                    "cadence_days": 7,
                    "start_condition": {"type": "calendar", "date": care_start.date().isoformat()},
                    "end_condition": {"type": "season_end"},
                    "linked_subjects": location_subjects,
                    "default_estimated_minutes": 12,
                    "next_generation_date": care_start,
                }
            )

        prepare_keys = [
            f"prepare.{location['location_type']}.{location['location_id']}"
            for location in execution_spec["selected_locations"]
        ]
        transplant_key = f"{plant_key}.event_transplant" if germinated_trigger else f"{plant_key}.transplant"
        if propagation in {"seed", "cutting", "propagation"}:
            dependencies.append({"blocking_task_id": f"{plant_key}.sow", "blocked_task_id": f"{plant_key}.pot_up"})
            dependencies.append({"blocking_task_id": f"{plant_key}.pot_up", "blocked_task_id": transplant_key})
        else:
            dependencies.append(
                {"blocking_task_id": f"{plant_key}.acquire_starts", "blocked_task_id": transplant_key}
            )
        for prepare_key in prepare_keys:
            dependencies.append({"blocking_task_id": prepare_key, "blocked_task_id": transplant_key})
        if task_profile in {"fruiting_vine", "fruiting_bush"}:
            dependencies.append({"blocking_task_id": transplant_key, "blocked_task_id": f"{plant_key}.supports"})
            dependencies.append(
                {"blocking_task_id": f"{plant_key}.supports", "blocked_task_id": f"{plant_key}.harvest_window"}
            )
        else:
            dependencies.append({"blocking_task_id": transplant_key, "blocked_task_id": f"{plant_key}.harvest_window"})
        if transplanted_trigger:
            dependencies.append(
                {"blocking_task_id": transplant_key, "blocked_task_id": f"{plant_key}.followup_fertilize"}
            )

    return tasks, dependencies, recurring_rules


def _create_generation_run(
    session,
    *,
    project_id: str,
    revision_id: str,
    run_type: str,
    summary: str,
    metadata: Optional[dict[str, Any]] = None,
    source_event_id: Optional[str] = None,
) -> TaskGenerationRun:
    run = TaskGenerationRun(
        project_id=project_id,
        revision_id=revision_id,
        run_type=run_type,
        status="complete",
        source_event_id=source_event_id,
        summary=summary,
        run_metadata=metadata or {},
    )
    session.add(run)
    session.flush()
    record_create_event(
        session,
        event_type="task_generation_run_created",
        category="task",
        summary=summary,
        obj=run,
        project_id=project_id,
        revision_id=revision_id,
        metadata={"run_type": run_type},
        subjects=[
            {"subject_type": "project", "subject_id": project_id, "role": "affected"},
            _run_subject(run.id),
        ],
    )
    return run


def _create_task(
    session,
    *,
    project_id: str,
    revision_id: str,
    generation_run_id: str,
    parent_task_id: Optional[str],
    series_id: Optional[str],
    source_type: str,
    generator_key: str,
    title: str,
    description: Optional[str],
    task_type: str,
    status: str,
    scheduled_date: Optional[datetime],
    earliest_start: Optional[datetime],
    window_start: Optional[datetime],
    window_end: Optional[datetime],
    deadline: Optional[datetime],
    estimated_minutes: int,
    reversible: bool,
    what_happens_if_skipped: Optional[str],
    what_happens_if_delayed: Optional[str],
    notes: Optional[str],
    linked_subjects: Optional[list[dict[str, Any]]] = None,
    event_anchor_type: Optional[str] = None,
    event_anchor_subject_type: Optional[str] = None,
    event_anchor_subject_id: Optional[str] = None,
    event_anchor_offset_days: Optional[int] = None,
) -> Task:
    task = Task(
        project_id=project_id,
        revision_id=revision_id,
        generation_run_id=generation_run_id,
        parent_task_id=parent_task_id,
        series_id=series_id,
        source_type=source_type,
        generator_key=generator_key,
        title=title,
        description=description,
        type=task_type,
        status=status,
        scheduled_date=scheduled_date,
        earliest_start=earliest_start,
        window_start=window_start,
        window_end=window_end,
        deadline=deadline,
        estimated_minutes=estimated_minutes,
        reversible=reversible,
        what_happens_if_skipped=what_happens_if_skipped,
        what_happens_if_delayed=what_happens_if_delayed,
        notes=notes,
        linked_subjects=linked_subjects or [],
        event_anchor_type=event_anchor_type,
        event_anchor_subject_type=event_anchor_subject_type,
        event_anchor_subject_id=event_anchor_subject_id,
        event_anchor_offset_days=event_anchor_offset_days,
    )
    session.add(task)
    session.flush()
    record_create_event(
        session,
        event_type="task_created",
        category="task",
        summary=f"Created task '{task.title}'.",
        obj=task,
        project_id=project_id,
        revision_id=revision_id,
        subjects=[
            {"subject_type": "project", "subject_id": project_id, "role": "affected"},
            _task_subject(task.id),
        ],
    )
    if task.status == "blocked":
        record_activity_event(
            session,
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
            event_type="task_blocked",
            category="task",
            summary=f"Task '{task.title}' is blocked pending prerequisite work or an anchor event.",
            project_id=project_id,
            revision_id=revision_id,
            metadata={"task_id": task.id, "generator_key": task.generator_key},
            subjects=[
                {"subject_type": "project", "subject_id": project_id, "role": "affected"},
                _task_subject(task.id),
            ],
        )
    return task


def _create_series(
    session,
    *,
    project_id: str,
    revision_id: str,
    generation_run_id: str,
    parent_task_id: Optional[str],
    source_type: str,
    generator_key: str,
    title: str,
    description: Optional[str],
    series_type: str,
    cadence: str,
    cadence_days: Optional[int],
    start_condition: dict[str, Any],
    end_condition: dict[str, Any],
    linked_subjects: list[dict[str, Any]],
    default_estimated_minutes: int,
    next_generation_date: Optional[datetime],
) -> TaskSeries:
    series = TaskSeries(
        project_id=project_id,
        revision_id=revision_id,
        generation_run_id=generation_run_id,
        parent_task_id=parent_task_id,
        source_type=source_type,
        generator_key=generator_key,
        title=title,
        description=description,
        type=series_type,
        cadence=cadence,
        cadence_days=cadence_days,
        start_condition=start_condition,
        end_condition=end_condition,
        linked_subjects=linked_subjects,
        default_estimated_minutes=default_estimated_minutes,
        next_generation_date=next_generation_date,
        active=True,
    )
    session.add(series)
    session.flush()
    record_create_event(
        session,
        event_type="task_series_created",
        category="task",
        summary=f"Created recurring task series '{series.title}'.",
        obj=series,
        project_id=project_id,
        revision_id=revision_id,
        subjects=[
            {"subject_type": "project", "subject_id": project_id, "role": "affected"},
            _series_subject(series.id),
        ],
    )
    return series


def _link_dependency(session, *, blocking_task_id: str, blocked_task_id: str) -> TaskDependency:
    dependency = TaskDependency(
        blocking_task_id=blocking_task_id,
        blocked_task_id=blocked_task_id,
    )
    session.add(dependency)
    session.flush()
    return dependency


def compute_task_blocked_state(session, task_or_id: Task | str) -> bool:
    task = task_or_id
    if isinstance(task_or_id, str):
        task = session.query(Task).filter(Task.id == task_or_id).first()
    if not task:
        raise ValueError("Task not found.")
    if task.event_anchor_type and task.scheduled_date is None:
        return True
    blockers = (
        session.query(Task)
        .join(TaskDependency, Task.id == TaskDependency.blocking_task_id)
        .filter(TaskDependency.blocked_task_id == task.id)
        .all()
    )
    return any(blocker.status not in {"done", "skipped"} for blocker in blockers)


def compute_task_urgency(task: Task, now: datetime, triggering_events: Optional[list[ActivityEvent]] = None) -> str:
    del triggering_events
    if task.deadline:
        delta = (task.deadline.date() - now.date()).days
        if delta <= 1:
            return "blocker"
    if task.window_end:
        delta = (task.window_end.date() - now.date()).days
        if delta <= 1:
            return "blocker"
        if delta <= 2:
            return "time_sensitive"
        if delta <= 14:
            return "scheduled"
        return "backlog"
    if task.scheduled_date:
        delta = (task.scheduled_date.date() - now.date()).days
        if delta <= 7:
            return "scheduled"
    return "backlog"


def list_materializable_series(session, now: datetime, days_ahead: int = ROLLING_TASK_HORIZON_DAYS, project_id: Optional[str] = None) -> list[TaskSeries]:
    horizon = now + timedelta(days=days_ahead)
    query = session.query(TaskSeries).filter(TaskSeries.active.is_(True))
    if project_id:
        query = query.filter(TaskSeries.project_id == project_id)
    series_list = query.order_by(TaskSeries.next_generation_date.asc()).all()
    return [
        series
        for series in series_list
        if series.next_generation_date and series.next_generation_date <= horizon
    ]


def _refresh_task_status_from_dependencies(session, task: Task) -> Optional[str]:
    before = task.status
    is_blocked = compute_task_blocked_state(session, task)
    if task.status in {"done", "skipped", "superseded", "deferred"}:
        return None
    if is_blocked and task.status != "blocked":
        task.status = "blocked"
    elif not is_blocked and task.status == "blocked":
        task.status = "pending"
    return before if before != task.status else None


def _supersede_prior_runs(session, *, project_id: str, revision_id: str, reason: Optional[str] = None) -> None:
    prior_runs = (
        session.query(TaskGenerationRun)
        .filter(TaskGenerationRun.project_id == project_id, TaskGenerationRun.status == "complete")
        .all()
    )
    for run in prior_runs:
        if run.revision_id == revision_id:
            run.status = "superseded"
        else:
            run.status = "superseded"

        active_series = session.query(TaskSeries).filter(TaskSeries.generation_run_id == run.id, TaskSeries.active.is_(True)).all()
        for series in active_series:
            before = snapshot_model(series)
            series.active = False
            record_update_event(
                session,
                event_type="task_series_updated",
                category="task",
                summary=f"Superseded recurring task series '{series.title}'.",
                before=before,
                obj=series,
                project_id=project_id,
                revision_id=series.revision_id,
                metadata={"reason": reason or "regenerated"},
                subjects=[
                    {"subject_type": "project", "subject_id": project_id, "role": "affected"},
                    _series_subject(series.id),
                ],
            )

        supersedable_tasks = (
            session.query(Task)
            .filter(Task.generation_run_id == run.id, Task.status.in_(["pending", "blocked", "deferred"]))
            .all()
        )
        for task in supersedable_tasks:
            if task.is_user_modified:
                continue
            before = snapshot_model(task)
            task.status = "superseded"
            record_update_event(
                session,
                event_type="task_superseded",
                category="task",
                summary=f"Superseded task '{task.title}'.",
                before=before,
                obj=task,
                project_id=project_id,
                revision_id=task.revision_id,
                metadata={"reason": reason or "regenerated"},
                subjects=[
                    {"subject_type": "project", "subject_id": project_id, "role": "affected"},
                    _task_subject(task.id),
                ],
            )


def materialize_task_series(
    session,
    *,
    now: Optional[datetime] = None,
    days_ahead: int = ROLLING_TASK_HORIZON_DAYS,
    project_id: Optional[str] = None,
) -> list[Task]:
    now = now or datetime.utcnow()
    horizon = now + timedelta(days=days_ahead)
    created: list[Task] = []
    series_list = list_materializable_series(session, now, days_ahead, project_id)
    for series in series_list:
        current = series.next_generation_date
        if not current:
            continue
        end_condition_date = None
        if (series.end_condition or {}).get("type") == "calendar":
            end_condition_date = _parse_date_value((series.end_condition or {}).get("date"))
        existing_dates = {
            task.scheduled_date.date()
            for task in session.query(Task)
            .filter(Task.series_id == series.id, Task.status != "superseded")
            .all()
            if task.scheduled_date
        }
        while current and current <= horizon and (end_condition_date is None or current <= end_condition_date):
            if current.date() not in existing_dates:
                created.append(
                    _create_task(
                        session,
                        project_id=series.project_id,
                        revision_id=series.revision_id,
                        generation_run_id=series.generation_run_id,
                        parent_task_id=series.parent_task_id,
                        series_id=series.id,
                        source_type=series.source_type,
                        generator_key=f"{series.generator_key}.{current.date().isoformat()}",
                        title=series.title,
                        description=series.description,
                        task_type=series.type,
                        status="pending",
                        scheduled_date=current,
                        earliest_start=current,
                        window_start=current,
                        window_end=current + timedelta(days=max(series.cadence_days or 1, 1)),
                        deadline=current + timedelta(days=max(series.cadence_days or 1, 1)),
                        estimated_minutes=series.default_estimated_minutes,
                        reversible=True,
                        what_happens_if_skipped="This recurring care interval will be missed.",
                        what_happens_if_delayed="Subsequent recurring care may bunch together or slip.",
                        notes=f"Materialized from recurring series '{series.title}'.",
                        linked_subjects=series.linked_subjects or [],
                    )
                )
            current = current + timedelta(days=series.cadence_days or 1)
        series.next_generation_date = current

    project_counts: dict[str, dict[str, Any]] = {}
    for task in created:
        info = project_counts.setdefault(task.project_id, {"count": 0, "revision_id": task.revision_id})
        info["count"] += 1
    for project_key, info in project_counts.items():
        record_activity_event(
            session,
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
            event_type="task_instances_materialized",
            category="task",
            summary=f"Materialized {info['count']} recurring task instances for project {project_key}.",
            project_id=project_key,
            revision_id=info["revision_id"],
            metadata={"count": info["count"], "days_ahead": days_ahead},
            subjects=[{"subject_type": "project", "subject_id": project_key, "role": "primary"}],
        )
    return created


def generate_tasks_for_revision(
    session,
    *,
    project_id: str,
    revision_id: Optional[str] = None,
    run_type: str = "initial",
    reason: Optional[str] = None,
    source_event_id: Optional[str] = None,
) -> dict[str, Any]:
    if run_type not in VALID_TASK_RUN_TYPES:
        raise ValueError(f"Invalid run_type '{run_type}'. Must be one of: {', '.join(sorted(VALID_TASK_RUN_TYPES))}.")

    project = _select_project(session, project_id)
    revision, spec = _select_revision_and_spec(session, project_id=project_id, revision_id=revision_id)
    execution_spec = _execution_spec_dict(spec)

    active_same_revision = (
        session.query(TaskGenerationRun)
        .filter(
            TaskGenerationRun.project_id == project_id,
            TaskGenerationRun.revision_id == revision.id,
            TaskGenerationRun.status == "complete",
        )
        .count()
    )
    active_any_run = (
        session.query(TaskGenerationRun)
        .filter(TaskGenerationRun.project_id == project_id, TaskGenerationRun.status == "complete")
        .count()
    )
    if run_type == "initial" and active_same_revision:
        raise ValueError(
            f"Project '{project.name}' already has generated tasks for revision {revision.revision_number}. "
            "Use regenerate_project_tasks to replace them."
        )

    if run_type != "initial" or active_any_run:
        _supersede_prior_runs(session, project_id=project_id, revision_id=revision.id, reason=reason)

    task_blueprints, dependency_blueprints, series_blueprints = _task_blueprints(
        session,
        project_id=project_id,
        execution_spec=execution_spec,
    )
    run = _create_generation_run(
        session,
        project_id=project_id,
        revision_id=revision.id,
        run_type=run_type,
        summary=f"Created task generation run for project '{project.name}' revision {revision.revision_number}.",
        metadata={"reason": reason, "task_count": len(task_blueprints), "series_count": len(series_blueprints)},
        source_event_id=source_event_id,
    )

    section_tasks: dict[str, Task] = {}
    for label in SECTION_LABELS:
        section_tasks[label] = _create_task(
            session,
            project_id=project_id,
            revision_id=revision.id,
            generation_run_id=run.id,
            parent_task_id=None,
            series_id=None,
            source_type="generated",
            generator_key=f"section.{_section_key(label)}",
            title=label,
            description=f"Generated section for {label.lower()} tasks.",
            task_type="milestone",
            status="pending",
            scheduled_date=None,
            earliest_start=None,
            window_start=None,
            window_end=None,
            deadline=None,
            estimated_minutes=0,
            reversible=True,
            what_happens_if_skipped=None,
            what_happens_if_delayed=None,
            notes="Section grouping task.",
            linked_subjects=[{"subject_type": "project", "subject_id": project_id, "role": "affected"}],
        )

    tasks_by_key: dict[str, Task] = {}
    for blueprint in task_blueprints:
        parent_task = section_tasks[blueprint["section"]]
        task = _create_task(
            session,
            project_id=project_id,
            revision_id=revision.id,
            generation_run_id=run.id,
            parent_task_id=parent_task.id,
            series_id=None,
            source_type="generated",
            generator_key=blueprint["generator_key"],
            title=blueprint["title"],
            description=blueprint.get("description"),
            task_type=blueprint["type"],
            status=blueprint.get("status") or "pending",
            scheduled_date=blueprint.get("scheduled_date"),
            earliest_start=blueprint.get("earliest_start"),
            window_start=blueprint.get("window_start"),
            window_end=blueprint.get("window_end"),
            deadline=blueprint.get("deadline"),
            estimated_minutes=int(blueprint.get("estimated_minutes", 0) or 0),
            reversible=bool(blueprint.get("reversible", True)),
            what_happens_if_skipped=blueprint.get("what_happens_if_skipped"),
            what_happens_if_delayed=blueprint.get("what_happens_if_delayed"),
            notes=blueprint.get("notes"),
            linked_subjects=blueprint.get("linked_subjects"),
            event_anchor_type=blueprint.get("event_anchor_type"),
            event_anchor_subject_type=blueprint.get("event_anchor_subject_type"),
            event_anchor_subject_id=blueprint.get("event_anchor_subject_id"),
            event_anchor_offset_days=blueprint.get("event_anchor_offset_days"),
        )
        tasks_by_key[blueprint["generator_key"]] = task

    dependencies: list[TaskDependency] = []
    for link in dependency_blueprints:
        blocking = tasks_by_key.get(link["blocking_task_id"])
        blocked = tasks_by_key.get(link["blocked_task_id"])
        if not blocking or not blocked:
            continue
        dependencies.append(
            _link_dependency(session, blocking_task_id=blocking.id, blocked_task_id=blocked.id)
        )

    for task in tasks_by_key.values():
        previous_status = _refresh_task_status_from_dependencies(session, task)
        if previous_status:
            record_update_event(
                session,
                event_type="task_blocked" if task.status == "blocked" else "task_updated",
                category="task",
                summary=(
                    f"Task '{task.title}' is blocked by prerequisite work."
                    if task.status == "blocked"
                    else f"Updated task '{task.title}'."
                ),
                before={**snapshot_model(task), "status": previous_status},
                obj=task,
                project_id=project_id,
                revision_id=task.revision_id,
                subjects=[
                    {"subject_type": "project", "subject_id": project_id, "role": "affected"},
                    _task_subject(task.id),
                ],
            )

    series_by_key: dict[str, TaskSeries] = {}
    ongoing_parent = section_tasks["Ongoing care"]
    for blueprint in series_blueprints:
        series = _create_series(
            session,
            project_id=project_id,
            revision_id=revision.id,
            generation_run_id=run.id,
            parent_task_id=ongoing_parent.id,
            source_type="generated",
            generator_key=blueprint["generator_key"],
            title=blueprint["title"],
            description=blueprint.get("description"),
            series_type=blueprint["type"],
            cadence=blueprint["cadence"],
            cadence_days=blueprint.get("cadence_days"),
            start_condition=blueprint.get("start_condition") or {},
            end_condition=blueprint.get("end_condition") or {},
            linked_subjects=blueprint.get("linked_subjects") or [],
            default_estimated_minutes=int(blueprint.get("default_estimated_minutes", 0) or 0),
            next_generation_date=blueprint.get("next_generation_date"),
        )
        series_by_key[blueprint["generator_key"]] = series

    materialized = materialize_task_series(
        session,
        now=datetime.utcnow(),
        days_ahead=ROLLING_TASK_HORIZON_DAYS,
        project_id=project_id,
    )
    session.flush()

    return {
        "project": project,
        "revision": revision,
        "execution_spec": spec,
        "generation_run": run,
        "section_tasks": list(section_tasks.values()),
        "milestone_tasks": list(tasks_by_key.values()),
        "dependencies": dependencies,
        "task_series": list(series_by_key.values()),
        "materialized_tasks": materialized,
    }


def build_due_task_view(
    session,
    *,
    project_id: Optional[str] = None,
    days_ahead: int = 7,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    now = now or datetime.utcnow()
    horizon = now + timedelta(days=days_ahead)
    query = session.query(Task).filter(Task.status.notin_(["done", "skipped", "superseded"]))
    if project_id:
        query = query.filter(Task.project_id == project_id)

    rows = []
    for task in query.order_by(Task.deadline.asc(), Task.window_end.asc(), Task.scheduled_date.asc()).all():
        if _is_section_task(task):
            continue
        if task.status == "deferred" and task.deferred_until and task.deferred_until > now:
            continue
        blocked = compute_task_blocked_state(session, task)
        due_date = task.deadline or task.window_end or task.scheduled_date or task.deferred_until
        if due_date and due_date > horizon and task.status != "in_progress":
            continue
        urgency = compute_task_urgency(task, now)
        rows.append(
            {
                "task": task,
                "urgency": urgency,
                "blocked": blocked,
                "due_date": due_date,
            }
        )
    return rows


def format_task_list(tasks: list[Task]) -> str:
    if not tasks:
        return "No tasks found."
    lines = ["Project tasks:", ""]
    for task in tasks:
        when = _date_only_iso(task.deadline or task.window_end or task.scheduled_date)
        lines.append(f"- [{task.status}] {task.title} | {when}")
    return "\n".join(lines)


def format_due_tasks(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No due tasks found."
    lines = ["Due tasks:", ""]
    for row in rows:
        task = row["task"]
        blocked_text = " | blocked" if row["blocked"] else ""
        lines.append(
            f"- [{row['urgency']}] {task.title} | due {_date_only_iso(row['due_date'])}{blocked_text}"
        )
    return "\n".join(lines)


def format_task_series(series_list: list[TaskSeries]) -> str:
    if not series_list:
        return "No recurring task series found."
    lines = ["Recurring task series:", ""]
    for series in series_list:
        lines.append(
            f"- {series.title} | {series.cadence} | next {_date_only_iso(series.next_generation_date)} | active={series.active}"
        )
    return "\n".join(lines)


def format_task_detail(session, task: Task) -> str:
    blockers = (
        session.query(Task)
        .join(TaskDependency, Task.id == TaskDependency.blocking_task_id)
        .filter(TaskDependency.blocked_task_id == task.id)
        .all()
    )
    lines = [
        task.to_summary(),
        f"  Description: {task.description or 'none'}",
        f"  Notes: {task.notes or 'none'}",
        f"  Deadline: {_date_only_iso(task.deadline)}",
        f"  Deferred until: {_date_only_iso(task.deferred_until)}",
        f"  Actual minutes: {task.actual_minutes if task.actual_minutes is not None else 'not set'}",
        f"  User modified: {task.is_user_modified}",
    ]
    if blockers:
        lines.append("  Blockers:")
        lines.extend(f"    - {blocker.title} [{blocker.status}]" for blocker in blockers)
    if task.event_anchor_type:
        lines.append(
            "  Event anchor: "
            f"{task.event_anchor_type} + {task.event_anchor_offset_days or 0} days"
        )
    return "\n".join(lines)
