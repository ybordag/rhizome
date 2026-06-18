from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.incidents import create_incident_report, draft_treatment_plan
from agent.interactions import (
    build_proposal_review_interaction,
    build_treatment_plan_review_interaction,
    build_triage_view_interaction,
    build_weather_change_review_interaction,
    find_pending_interaction_record,
    record_interaction_summary,
)
from agent.planner import (
    build_execution_spec_payload,
    build_plan_input,
    check_plan_feasibility,
    estimate_plan_cost,
    estimate_plan_effort,
    estimate_plan_timeline,
    get_or_create_brief,
)
from agent.tracker import generate_tasks_for_revision
from agent.triage import build_triage_snapshot
from agent.weather import draft_weather_task_changes, refresh_weather_snapshot
from db.database import SessionLocal, init_db
from db.models import (
    Bed,
    Container,
    GardenProfile,
    GardeningProject,
    IncidentReport,
    InteractionRecord,
    Plant,
    PlantBatch,
    ProjectBrief,
    ProjectContainer,
    ProjectExecutionSpec,
    ProjectPlant,
    ProjectProposal,
    ProjectRevision,
    Task,
    TaskGenerationRun,
    TreatmentPlan,
    TriageSnapshot,
    WeatherSnapshot,
    WeatherTaskChangeSet,
)


USER_ID = 1
PROFILE_LOCATION_LABEL = "Oakland, CA"
PROFILE_LATITUDE = 37.8044
PROFILE_LONGITUDE = -122.2711
NOW = datetime(2026, 4, 12, 9, 0, 0)
DATABASE_PATH = ROOT / "rhizome.db"
CHECKPOINT_PATH = ROOT / "rhizome_checkpoints.db"

BED_DEFINITIONS = [
    {
        "name": "front_bed_left",
        "location": "front",
        "sunlight": "partial sun",
        "soil_type": "hard clay, some amendment",
        "dimensions_sqft": 12.0,
        "notes": "Along the front of the house, left side",
    },
    {
        "name": "front_bed_right",
        "location": "front",
        "sunlight": "partial sun",
        "soil_type": "hard clay, some amendment",
        "dimensions_sqft": 12.0,
        "notes": "Along the front of the house, right side",
    },
    {
        "name": "courtyard_small_bed_1",
        "location": "courtyard",
        "sunlight": "partial sun",
        "soil_type": "hard clay",
        "dimensions_sqft": 4.0,
        "notes": "Very small bed in courtyard",
    },
    {
        "name": "courtyard_small_bed_2",
        "location": "courtyard",
        "sunlight": "partial sun",
        "soil_type": "hard clay",
        "dimensions_sqft": 4.0,
        "notes": "Very small bed in courtyard",
    },
    {
        "name": "courtyard_medium_bed",
        "location": "courtyard",
        "sunlight": "partial to full sun",
        "soil_type": "hard clay, amended",
        "dimensions_sqft": 25.0,
        "notes": "The main usable bed in the courtyard",
    },
    {
        "name": "slope_bed_upper",
        "location": "backyard_slope",
        "sunlight": "full shade",
        "soil_type": "hard clay, slope",
        "dimensions_sqft": 30.0,
        "notes": "Upper slope, heavily shaded by 3 large trees",
    },
    {
        "name": "slope_bed_lower",
        "location": "backyard_slope",
        "sunlight": "partial shade",
        "soil_type": "hard clay, slope",
        "dimensions_sqft": 30.0,
        "notes": "Lower slope, slightly more light than upper",
    },
]

CONTAINER_DEFINITIONS = [
    {
        "name": "growbag_1",
        "container_type": "growbag",
        "size_gallons": 15.0,
        "location": "courtyard",
        "is_mobile": True,
        "notes": "Large growbag, good for tomatoes or peppers",
    },
    {
        "name": "growbag_2",
        "container_type": "growbag",
        "size_gallons": 15.0,
        "location": "courtyard",
        "is_mobile": True,
        "notes": "Large growbag, good for tomatoes or peppers",
    },
    {
        "name": "growbag_3",
        "container_type": "growbag",
        "size_gallons": 15.0,
        "location": "courtyard",
        "is_mobile": True,
        "notes": "Large growbag, good for tomatoes or peppers",
    },
    {
        "name": "growbag_4",
        "container_type": "growbag",
        "size_gallons": 15.0,
        "location": "courtyard",
        "is_mobile": True,
        "notes": "Large growbag, good for tomatoes or peppers",
    },
    {
        "name": "growbag_5",
        "container_type": "growbag",
        "size_gallons": 10.0,
        "location": "courtyard",
        "is_mobile": True,
        "notes": "Medium growbag, good for herbs or smaller plants",
    },
    {
        "name": "growbag_6",
        "container_type": "growbag",
        "size_gallons": 10.0,
        "location": "courtyard",
        "is_mobile": True,
        "notes": "Medium growbag, good for herbs or smaller plants",
    },
    {
        "name": "growbag_7",
        "container_type": "growbag",
        "size_gallons": 10.0,
        "location": "courtyard",
        "is_mobile": True,
        "notes": "Medium growbag, good for herbs or smaller plants",
    },
    {
        "name": "pot_large_1",
        "container_type": "pot",
        "size_gallons": 10.0,
        "location": "front",
        "is_mobile": True,
        "notes": "Large ceramic pot, front entrance",
    },
    {
        "name": "pot_large_2",
        "container_type": "pot",
        "size_gallons": 10.0,
        "location": "front",
        "is_mobile": True,
        "notes": "Large ceramic pot, front entrance",
    },
]

REQUIRED_SCHEMA = {
    "garden_profile": {"location_label", "latitude", "longitude"},
    "project_brief": set(),
    "project_proposal": set(),
    "project_revision": set(),
    "project_execution_spec": set(),
    "task": set(),
    "task_series": set(),
    "weather_snapshot": set(),
    "triage_snapshot": set(),
    "interaction_record": set(),
    "incident_report": set(),
    "treatment_plan": set(),
}


def _seed_weather_payload(*, latitude: float, longitude: float, timezone: str) -> dict:
    return {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "daily": {
            "time": [
                "2026-04-12",
                "2026-04-13",
                "2026-04-14",
                "2026-04-15",
                "2026-04-16",
                "2026-04-17",
                "2026-04-18",
            ],
            "temperature_2m_max": [30, 34, 24, 20, 22, 26, 28],
            "temperature_2m_min": [12, 15, 9, 3, 8, 10, 11],
            "precipitation_sum": [0, 0, 18, 22, 1, 0, 0],
            "wind_speed_10m_max": [10, 16, 18, 38, 14, 12, 9],
        },
    }


def _schema_is_stale(db_path: Path) -> tuple[bool, str]:
    if not db_path.exists():
        return False, ""

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table_name, required_columns in REQUIRED_SCHEMA.items():
            if table_name not in tables:
                return True, f"missing table '{table_name}'"
            if required_columns:
                existing_columns = {
                    row[1]
                    for row in conn.execute(f"PRAGMA table_info({table_name})")
                }
                missing = required_columns - existing_columns
                if missing:
                    missing_label = ", ".join(sorted(missing))
                    return True, f"missing column(s) {missing_label} on '{table_name}'"
        return False, ""
    finally:
        conn.close()


def _rotate_stale_databases(reason: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    if DATABASE_PATH.exists():
        backup = DATABASE_PATH.with_name(f"rhizome.pre_seed_backup.{timestamp}.db")
        DATABASE_PATH.rename(backup)
        print(f"Archived stale database to {backup.name} ({reason}).")
    if CHECKPOINT_PATH.exists():
        checkpoint_backup = CHECKPOINT_PATH.with_name(f"rhizome_checkpoints.pre_seed_backup.{timestamp}.db")
        CHECKPOINT_PATH.rename(checkpoint_backup)
        print(f"Archived checkpoint database to {checkpoint_backup.name}.")


def _upsert_named_record(session, model, *, profile_id: str, defaults: dict):
    record = (
        session.query(model)
        .filter(model.garden_profile_id == profile_id, model.name == defaults["name"])
        .first()
    )
    created = False
    if not record:
        record = model(user_id=USER_ID, garden_profile_id=profile_id, name=defaults["name"])
        session.add(record)
        created = True
    for field, value in defaults.items():
        setattr(record, field, value)
    return record, created


def _ensure_project_container_link(session, project_id: str, container_id: str) -> bool:
    existing = (
        session.query(ProjectContainer)
        .filter(ProjectContainer.project_id == project_id, ProjectContainer.container_id == container_id)
        .first()
    )
    if existing:
        return False
    session.add(ProjectContainer(project_id=project_id, container_id=container_id))
    return True


def _ensure_project_plant_link(session, project_id: str, plant_id: str) -> bool:
    existing = (
        session.query(ProjectPlant)
        .filter(ProjectPlant.project_id == project_id, ProjectPlant.plant_id == plant_id)
        .first()
    )
    if existing:
        return False
    session.add(ProjectPlant(project_id=project_id, plant_id=plant_id))
    return True


def _ensure_profile(session) -> GardenProfile:
    profile = session.query(GardenProfile).filter(GardenProfile.user_id == USER_ID).first()
    created = False
    if not profile:
        profile = GardenProfile(user_id=USER_ID)
        session.add(profile)
        created = True

    profile.climate_zone = "9b"
    profile.frost_date_last_spring = "January 15"
    profile.frost_date_first_fall = "November 30"
    profile.soil_type = "hard clay in ground beds"
    profile.tray_capacity = 12
    profile.tray_indoor_capacity = 8
    profile.location_label = PROFILE_LOCATION_LABEL
    profile.latitude = PROFILE_LATITUDE
    profile.longitude = PROFILE_LONGITUDE
    profile.hard_constraints = {
        "non_toxic_required": True,
        "reason": "dogs and children",
    }
    profile.soft_preferences = {
        "aesthetic": "cottage garden",
        "organic_preferred": True,
        "growing_goals": ["flowers", "vegetables"],
        "cost_conscious": True,
    }
    profile.notes = (
        "7000 sqft lot, ~1000 sqft active garden.\n"
        "Front: small beds, partial sun, small lawn strip.\n"
        "Courtyard: very small beds + one medium bed, mixed sun.\n"
        "Backyard: slope mostly shaded by 3 large trees.\n"
        "Two-step transplant: seed tray -> red cup water reservoir -> final location.\n"
        "Dogs have access to most of the garden."
    )
    session.flush()
    print("Created garden profile." if created else "Updated garden profile.")
    return profile


def _ensure_beds_and_containers(session, profile: GardenProfile) -> tuple[dict[str, Bed], dict[str, Container]]:
    bed_map: dict[str, Bed] = {}
    container_map: dict[str, Container] = {}

    bed_created = 0
    for definition in BED_DEFINITIONS:
        bed, created = _upsert_named_record(session, Bed, profile_id=profile.id, defaults=definition)
        bed_map[bed.name] = bed
        bed_created += int(created)

    container_created = 0
    for definition in CONTAINER_DEFINITIONS:
        container, created = _upsert_named_record(session, Container, profile_id=profile.id, defaults=definition)
        container_map[container.name] = container
        container_created += int(created)

    session.flush()
    print(f"Beds ensured ({len(bed_map)} total, {bed_created} created).")
    print(f"Containers ensured ({len(container_map)} total, {container_created} created).")
    return bed_map, container_map


def _ensure_project(session, profile: GardenProfile) -> GardeningProject:
    project = (
        session.query(GardeningProject)
        .filter(
            GardeningProject.garden_profile_id == profile.id,
            GardeningProject.name == "Courtyard Tomatoes",
        )
        .first()
    )
    created = False
    if not project:
        project = GardeningProject(user_id=USER_ID, garden_profile_id=profile.id, name="Courtyard Tomatoes")
        session.add(project)
        created = True

    project.goal = "Grow tomatoes from cuttings in the courtyard growbags for summer harvest"
    project.status = "active"
    project.tray_slots = 0
    project.budget_ceiling = 50.0
    project.approved_plan = project.approved_plan or {
        "notes": "Cuttings from a friend's heirloom plant, transplanted to growbags.",
    }
    project.negotiation_history = project.negotiation_history or []
    project.iterations = project.iterations or []
    project.notes = "Tomatoes propagated from cuttings. Currently established and being staked."
    session.flush()
    print("Created example project." if created else "Updated example project.")
    return project


def _ensure_batch_and_plants(
    session,
    *,
    profile: GardenProfile,
    project: GardeningProject,
    container_map: dict[str, Container],
) -> tuple[PlantBatch, list[Plant]]:
    batch = (
        session.query(PlantBatch)
        .filter(
            PlantBatch.garden_profile_id == profile.id,
            PlantBatch.project_id == project.id,
            PlantBatch.name == "Courtyard Tomatoes March 2026",
        )
        .first()
    )
    if not batch:
        batch = PlantBatch(
            user_id=USER_ID,
            garden_profile_id=profile.id,
            project_id=project.id,
            name="Courtyard Tomatoes March 2026",
        )
        session.add(batch)
    batch.plant_name = "Cherry Tomato"
    batch.variety = "Sungold"
    batch.quantity_sown = 2
    batch.source = "cutting"
    batch.sow_date = datetime(2026, 3, 1)
    batch.supplier = "Friend's garden"
    batch.supplier_reference = "Heirloom cutting"
    batch.grow_light = None
    batch.tray = None
    batch.notes = "Cuttings taken from a friend's established heirloom plant."
    session.flush()

    plants: list[Plant] = []
    plant_specs = [
        ("growbag_1", "Doing well, starting to fruit"),
        ("growbag_2", "Doing well, starting to fruit"),
    ]
    for container_name, note in plant_specs:
        container = container_map[container_name]
        plant = (
            session.query(Plant)
            .filter(
                Plant.garden_profile_id == profile.id,
                Plant.batch_id == batch.id,
                Plant.container_id == container.id,
                Plant.name == "Cherry Tomato",
                Plant.variety == "Sungold",
            )
            .first()
        )
        if not plant:
            plant = Plant(
                user_id=USER_ID,
                garden_profile_id=profile.id,
                batch_id=batch.id,
                name="Cherry Tomato",
                variety="Sungold",
                container_id=container.id,
            )
            session.add(plant)
        plant.quantity = 1
        plant.source = "cutting"
        plant.transplant_date = datetime(2026, 3, 1)
        plant.propagated_from = "Friend's heirloom plant"
        plant.status = "established"
        plant.is_flowering = True
        plant.is_fruiting = True
        plant.fertilizing_schedule = "every 2 weeks with liquid tomato feed"
        plant.last_watered_at = datetime(2026, 4, 11)
        plant.last_fertilized_at = datetime(2026, 4, 1)
        plant.last_inspected_at = datetime(2026, 4, 10)
        plant.special_instructions = "Pinch out suckers weekly. Stake as it grows."
        plant.care_state_notes = "Healthy established tomato in active production."
        plant.notes = note
        plants.append(plant)

    session.flush()
    print("Example plant batch and plants ensured.")
    return batch, plants


def _ensure_project_links(
    session,
    *,
    project: GardeningProject,
    container_map: dict[str, Container],
    plants: list[Plant],
) -> None:
    linked_containers = 0
    for name in ("growbag_1", "growbag_2"):
        linked_containers += int(_ensure_project_container_link(session, project.id, container_map[name].id))
    linked_plants = 0
    for plant in plants:
        linked_plants += int(_ensure_project_plant_link(session, project.id, plant.id))
    session.flush()
    print(f"Project links ensured ({linked_containers} container links added, {linked_plants} plant links added).")


def _proposal_payload(
    *,
    project: GardeningProject,
    brief: ProjectBrief,
    profile: GardenProfile,
    title: str,
    summary: str,
    recommended_approach: str,
    selected_locations: list[dict],
    selected_plants: list[dict],
    material_strategy: dict,
    propagation_strategy: dict,
    assumptions: list[str],
    tradeoffs: list[str],
    risks: list[str],
    maintenance_assumptions: dict,
    resource_assumptions: dict,
    budget_assumptions: dict,
    timing_anchors: dict,
) -> dict:
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
    return {
        "title": title,
        "summary": summary,
        "recommended_approach": recommended_approach,
        "selected_locations": selected_locations,
        "selected_plants": selected_plants,
        "material_strategy": material_strategy,
        "propagation_strategy": propagation_strategy,
        "assumptions": assumptions,
        "tradeoffs": tradeoffs,
        "risks": risks,
        "feasibility_notes": feasibility["warnings"] + feasibility["hard_constraint_violations"],
        "cost_estimate": estimate_plan_cost(plan_input),
        "timeline_estimate": estimate_plan_timeline(plan_input),
        "effort_estimate": estimate_plan_effort(plan_input),
        "maintenance_assumptions": maintenance_assumptions,
        "resource_assumptions": resource_assumptions,
        "budget_assumptions": budget_assumptions,
        "timing_anchors": timing_anchors,
    }


def _ensure_proposal(
    session,
    *,
    project: GardeningProject,
    brief: ProjectBrief,
    title: str,
    payload: dict,
    version: int,
    status: str = "proposed",
) -> ProjectProposal:
    proposal = (
        session.query(ProjectProposal)
        .filter(ProjectProposal.project_id == project.id, ProjectProposal.title == title)
        .first()
    )
    if not proposal:
        proposal = ProjectProposal(project_id=project.id, brief_id=brief.id, title=title)
        session.add(proposal)
    proposal.version = version
    proposal.status = status
    proposal.summary = payload["summary"]
    proposal.recommended_approach = payload["recommended_approach"]
    proposal.selected_locations = payload["selected_locations"]
    proposal.selected_plants = payload["selected_plants"]
    proposal.material_strategy = payload["material_strategy"]
    proposal.propagation_strategy = payload["propagation_strategy"]
    proposal.assumptions = payload["assumptions"]
    proposal.tradeoffs = payload["tradeoffs"]
    proposal.risks = payload["risks"]
    proposal.feasibility_notes = payload["feasibility_notes"]
    proposal.cost_estimate = payload["cost_estimate"]
    proposal.timeline_estimate = payload["timeline_estimate"]
    proposal.effort_estimate = payload["effort_estimate"]
    proposal.maintenance_assumptions = payload["maintenance_assumptions"]
    proposal.resource_assumptions = payload["resource_assumptions"]
    proposal.budget_assumptions = payload["budget_assumptions"]
    proposal.timing_anchors = payload["timing_anchors"]
    session.flush()
    return proposal


def _ensure_planner_state(
    session,
    *,
    profile: GardenProfile,
    project: GardeningProject,
    container_map: dict[str, Container],
    plants: list[Plant],
) -> tuple[ProjectBrief, ProjectProposal, ProjectProposal, ProjectRevision, ProjectExecutionSpec]:
    brief, _ = get_or_create_brief(session, project.id)
    brief.goal = project.goal
    brief.desired_outcome = "Keep two productive Sungold tomatoes thriving through summer harvest in the courtyard."
    brief.target_start = datetime(2026, 4, 12)
    brief.target_completion = datetime(2026, 7, 15)
    brief.budget_cap = 65.0
    brief.effort_preference = "moderate"
    brief.propagation_preference = "reuse_existing"
    brief.priority_preferences = ["summer harvest", "low cost", "courtyard focus"]
    brief.notes = "Use existing cuttings where possible and keep weekly work manageable."
    brief.status = "ready_for_proposal"
    session.flush()

    accepted_locations = [
        {
            "location_type": "container",
            "location_id": container_map["growbag_1"].id,
            "name": "growbag_1",
            "sunlight": "partial to full sun",
            "soil_type": "container mix",
            "available": True,
            "estimated_setup_cost": 0.0,
            "material_cost": 5.0,
            "amendment_cost": 6.0,
        },
        {
            "location_type": "container",
            "location_id": container_map["growbag_2"].id,
            "name": "growbag_2",
            "sunlight": "partial to full sun",
            "soil_type": "container mix",
            "available": True,
            "estimated_setup_cost": 0.0,
            "material_cost": 5.0,
            "amendment_cost": 6.0,
        },
    ]
    accepted_plants = [
        {
            "name": "Tomato",
            "variety": "Sungold",
            "quantity": 2,
            "propagation_method": "transplant",
            "unit_cost": 0.0,
            "support_cost": 8.0,
            "maintenance_hours_per_week": 1.5,
            "light_preference": "full sun",
            "soil_preference": "well-drained",
            "task_profile": "fruiting_vine",
            "annual": True,
            "edible": True,
            "event_triggers": [
                {
                    "event_type": "plant_transplanted",
                    "subject_type": "plant",
                    "subject_id": plants[0].id,
                    "offset_days": 14,
                }
            ],
        }
    ]
    accepted_payload = _proposal_payload(
        project=project,
        brief=brief,
        profile=profile,
        title="Courtyard tomato maintenance plan",
        summary="Use the two existing Sungold tomatoes in the courtyard growbags and focus on supports, feeding, watering, and harvest prep.",
        recommended_approach="Keep both plants in place, reinforce supports, and lean on recurring maintenance rather than new propagation.",
        selected_locations=accepted_locations,
        selected_plants=accepted_plants,
        material_strategy={"reuse_existing_containers": True, "buy_new_supports": True},
        propagation_strategy={"mode": "reuse_existing"},
        assumptions=["Existing plants remain healthy enough to carry the summer crop."],
        tradeoffs=["Lower cost and faster timeline, but less flexibility if one plant fails."],
        risks=["Heat stress in the courtyard may increase watering needs."],
        maintenance_assumptions={"watering_frequency": "every 2 days", "feeding_frequency": "every 14 days"},
        resource_assumptions={"available_containers": 2, "available_supports": 2},
        budget_assumptions={"reserve_for_feed_and_ties": 20.0},
        timing_anchors={"modes": ["calendar", "event"], "calendar": [], "event": []},
    )
    accepted_proposal = _ensure_proposal(
        session,
        project=project,
        brief=brief,
        title="Courtyard tomato maintenance plan",
        payload=accepted_payload,
        version=1,
        status="accepted",
    )

    alt_locations = accepted_locations + [
        {
            "location_type": "container",
            "location_id": container_map["growbag_3"].id,
            "name": "growbag_3",
            "sunlight": "partial to full sun",
            "soil_type": "container mix",
            "available": True,
            "estimated_setup_cost": 0.0,
            "material_cost": 6.0,
            "amendment_cost": 6.0,
        }
    ]
    alt_plants = [
        {
            "name": "Tomato",
            "variety": "Sungold",
            "quantity": 3,
            "propagation_method": "start",
            "unit_cost": 4.0,
            "support_cost": 8.0,
            "maintenance_hours_per_week": 2.0,
            "light_preference": "full sun",
            "soil_preference": "well-drained",
            "task_profile": "fruiting_vine",
            "annual": True,
            "edible": True,
            "event_triggers": [],
        }
    ]
    alt_payload = _proposal_payload(
        project=project,
        brief=brief,
        profile=profile,
        title="Expanded tomato fast-track option",
        summary="Add one more growbag and buy starts to push for a larger courtyard harvest.",
        recommended_approach="Use nursery starts for a faster ramp and add a third growbag for more production.",
        selected_locations=alt_locations,
        selected_plants=alt_plants,
        material_strategy={"reuse_existing_containers": True, "buy_new_starts": True},
        propagation_strategy={"mode": "buy_starts"},
        assumptions=["Budget can flex for starts and extra feed."],
        tradeoffs=["Higher cost and workload, but potentially larger harvest."],
        risks=["More frequent watering and support work during heat spikes."],
        maintenance_assumptions={"watering_frequency": "daily during heat", "feeding_frequency": "every 10 days"},
        resource_assumptions={"available_containers": 3, "available_supports": 3},
        budget_assumptions={"reserve_for_starts": 18.0},
        timing_anchors={"modes": ["calendar", "event"], "calendar": [], "event": []},
    )
    proposed_alt = _ensure_proposal(
        session,
        project=project,
        brief=brief,
        title="Expanded tomato fast-track option",
        payload=alt_payload,
        version=2,
        status="proposed",
    )

    revision = (
        session.query(ProjectRevision)
        .filter(ProjectRevision.project_id == project.id, ProjectRevision.status == "active")
        .order_by(ProjectRevision.revision_number.desc())
        .first()
    )
    if not revision:
        revision = ProjectRevision(
            project_id=project.id,
            source_proposal_id=accepted_proposal.id,
            revision_number=1,
            status="active",
            approved_plan={
                "proposal_id": accepted_proposal.id,
                "title": accepted_proposal.title,
                "summary": accepted_proposal.summary,
                "recommended_approach": accepted_proposal.recommended_approach,
                "cost_estimate": accepted_proposal.cost_estimate,
                "timeline_estimate": accepted_proposal.timeline_estimate,
                "effort_estimate": accepted_proposal.effort_estimate,
                "tradeoffs": accepted_proposal.tradeoffs,
                "risks": accepted_proposal.risks,
                "selected_locations": accepted_proposal.selected_locations,
                "selected_plants": accepted_proposal.selected_plants,
            },
            approved_at=NOW,
        )
        session.add(revision)
        session.flush()
    project.approved_plan = revision.approved_plan

    spec = (
        session.query(ProjectExecutionSpec)
        .filter(ProjectExecutionSpec.project_id == project.id, ProjectExecutionSpec.revision_id == revision.id)
        .first()
    )
    if not spec:
        spec_payload = build_execution_spec_payload(accepted_proposal, brief)
        spec = ProjectExecutionSpec(
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
        session.add(spec)
        session.flush()

    print("Planner state ensured (brief, proposals, revision, execution spec).")
    return brief, accepted_proposal, proposed_alt, revision, spec


def _ensure_tasks(session, *, project: GardeningProject, revision: ProjectRevision) -> None:
    existing_run = (
        session.query(TaskGenerationRun)
        .filter(
            TaskGenerationRun.project_id == project.id,
            TaskGenerationRun.revision_id == revision.id,
            TaskGenerationRun.status == "complete",
        )
        .first()
    )
    if existing_run:
        print("Tracker state already exists, skipping task generation.")
        return

    generate_tasks_for_revision(session, project_id=project.id, revision_id=revision.id, run_type="initial")
    print("Generated persistent tasks and recurring task series.")


def _ensure_weather_and_triage(session, *, project: GardeningProject) -> tuple[WeatherSnapshot, WeatherTaskChangeSet, TriageSnapshot]:
    snapshot = session.query(WeatherSnapshot).order_by(WeatherSnapshot.created_at.desc()).first()
    if not snapshot:
        snapshot = refresh_weather_snapshot(session, fetcher=_seed_weather_payload)
        print("Created seeded weather snapshot.")
    else:
        print("Weather snapshot already exists, keeping latest.")

    change_set = (
        session.query(WeatherTaskChangeSet)
        .filter(
            WeatherTaskChangeSet.project_id == project.id,
            WeatherTaskChangeSet.status == "draft",
        )
        .order_by(WeatherTaskChangeSet.created_at.desc())
        .first()
    )
    if not change_set:
        change_set = draft_weather_task_changes(session, project_id=project.id)
        print("Created draft weather task changes.")
    else:
        print("Draft weather task changes already exist.")

    triage = session.query(TriageSnapshot).order_by(TriageSnapshot.created_at.desc()).first()
    if not triage:
        triage = build_triage_snapshot(
            session,
            opener="I only have 20 minutes and low energy, but I can work outside on the tomato project.",
            now=NOW,
        )
        print("Created seeded triage snapshot.")
    else:
        print("Triage snapshot already exists, keeping latest.")

    return snapshot, change_set, triage


def _ensure_incident_state(
    session,
    *,
    project: GardeningProject,
    plants: list[Plant],
    container_map: dict[str, Container],
) -> tuple[IncidentReport, TreatmentPlan]:
    incident = (
        session.query(IncidentReport)
        .filter(
            IncidentReport.project_id == project.id,
            IncidentReport.summary == "Aphids spotted on the courtyard Sungold tomatoes",
        )
        .first()
    )
    if not incident:
        incident = create_incident_report(
            session,
            project_id=project.id,
            incident_type="pest",
            severity="medium",
            summary="Aphids spotted on the courtyard Sungold tomatoes",
            notes="Leaves show curling and sticky residue on one plant.",
            detected_at=NOW,
            subjects=[
                {"subject_type": "plant", "subject_id": plants[0].id, "role": "primary"},
                {"subject_type": "container", "subject_id": container_map["growbag_1"].id, "role": "affected"},
            ],
        )
        print("Created seeded incident report.")
    else:
        print("Incident report already exists.")

    plan = (
        session.query(TreatmentPlan)
        .filter(TreatmentPlan.incident_id == incident.id, TreatmentPlan.status == "draft")
        .order_by(TreatmentPlan.created_at.desc())
        .first()
    )
    if not plan:
        plan = draft_treatment_plan(session, incident.id)
        print("Created draft treatment plan.")
    else:
        print("Draft treatment plan already exists.")
    return incident, plan


def _ensure_interaction_record(session, *, source_type: str, source_id: str, project_id: str | None, builder) -> None:
    existing = find_pending_interaction_record(session, source_type=source_type, source_id=source_id)
    if existing:
        return
    envelope = builder()
    record_interaction_summary(
        session,
        envelope,
        source_type=source_type,
        source_id=source_id,
        project_id=project_id,
    )


def _ensure_interactions(
    session,
    *,
    project: GardeningProject,
    proposal: ProjectProposal,
    treatment_plan: TreatmentPlan,
    change_set: WeatherTaskChangeSet,
    triage: TriageSnapshot,
) -> None:
    _ensure_interaction_record(
        session,
        source_type="planner",
        source_id=proposal.id,
        project_id=project.id,
        builder=lambda: build_proposal_review_interaction(session, project.id, proposal.id),
    )
    _ensure_interaction_record(
        session,
        source_type="incident",
        source_id=treatment_plan.id,
        project_id=project.id,
        builder=lambda: build_treatment_plan_review_interaction(session, treatment_plan.id),
    )
    _ensure_interaction_record(
        session,
        source_type="weather",
        source_id=change_set.id,
        project_id=project.id,
        builder=lambda: build_weather_change_review_interaction(session, change_set.id),
    )
    _ensure_interaction_record(
        session,
        source_type="triage",
        source_id=triage.id,
        project_id=project.id,
        builder=lambda: build_triage_view_interaction(session, triage),
    )
    print(
        "Interaction summaries ensured "
        f"({session.query(InteractionRecord).count()} total records)."
    )


def seed():
    stale, reason = _schema_is_stale(DATABASE_PATH)
    if stale:
        _rotate_stale_databases(reason)
    init_db()
    session = SessionLocal()
    try:
        profile = _ensure_profile(session)
        bed_map, container_map = _ensure_beds_and_containers(session, profile)
        project = _ensure_project(session, profile)
        batch, plants = _ensure_batch_and_plants(
            session,
            profile=profile,
            project=project,
            container_map=container_map,
        )
        _ensure_project_links(
            session,
            project=project,
            container_map=container_map,
            plants=plants,
        )
        brief, accepted_proposal, proposed_alt, revision, spec = _ensure_planner_state(
            session,
            profile=profile,
            project=project,
            container_map=container_map,
            plants=plants,
        )
        _ensure_tasks(session, project=project, revision=revision)
        weather_snapshot, change_set, triage = _ensure_weather_and_triage(session, project=project)
        incident, treatment_plan = _ensure_incident_state(
            session,
            project=project,
            plants=plants,
            container_map=container_map,
        )
        _ensure_interactions(
            session,
            project=project,
            proposal=proposed_alt,
            treatment_plan=treatment_plan,
            change_set=change_set,
            triage=triage,
        )
        session.commit()
        print(
            "Seed complete.\n"
            f"Profile: {profile.id}\n"
            f"Project: {project.id}\n"
            f"Brief: {brief.id}\n"
            f"Accepted proposal: {accepted_proposal.id}\n"
            f"Pending proposal review: {proposed_alt.id}\n"
            f"Revision/spec: {revision.id} / {spec.id}\n"
            f"Tasks: {session.query(Task).filter(Task.project_id == project.id).count()} | "
            f"Triage snapshots: {session.query(TriageSnapshot).count()} | "
            f"Weather snapshots: {session.query(WeatherSnapshot).count()} | "
            f"Incidents: {session.query(IncidentReport).count()} | "
            f"Treatment plans: {session.query(TreatmentPlan).count()}"
        )
        _ = batch
        _ = bed_map
        _ = weather_snapshot
        _ = incident
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed()
