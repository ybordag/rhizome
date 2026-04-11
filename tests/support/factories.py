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
    ProjectContainer,
    ProjectPlant,
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
