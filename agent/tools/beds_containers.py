"""
Agent tools for managing beds and containers.
Tools must return strings — the LLM reads tool output as text.
"""

from langchain.tools import tool
from agent.activity_log import (
    DEFAULT_ACTOR_LABEL,
    DEFAULT_ACTOR_TYPE,
    record_create_event,
    record_delete_event,
    record_update_event,
    snapshot_model,
)
from db.database import SessionLocal
from db.models import GardenProfile, Plant, Bed, Container, ProjectBed, ProjectContainer
from typing import Optional

VALID_CONTAINER_TYPES = {"growbag", "pot", "paper_bag", "raised_bed"}


def _validate_positive_float(field_name: str, value: Optional[float]) -> Optional[str]:
    if value is not None and value <= 0:
        return f"{field_name} must be greater than 0."
    return None


def _validate_container_type(container_type: str) -> Optional[str]:
    if container_type not in VALID_CONTAINER_TYPES:
        return (
            f"Invalid container_type '{container_type}'. Must be one of: "
            f"{', '.join(sorted(VALID_CONTAINER_TYPES))}."
        )
    return None


# ─── Bed tools ────────────────────────────────────────────────────────────

@tool
def update_bed(
    bed_id: str,
    soil_type: Optional[str] = None,
    sunlight: Optional[str] = None,
    dimensions_sqft: Optional[float] = None,
    location: Optional[str] = None,
    notes: Optional[str] = None
) -> str:
    """
    Update a bed's current conditions. Use this when the user makes changes
    to a bed — for example 'I amended the courtyard bed with compost',
    'I added a drip line to the slope bed', or 'the front bed gets more
    shade now that the neighbour's tree has grown'. Keeping bed conditions
    current ensures planting advice reflects reality.
    """
    session = SessionLocal()
    try:
        bed = session.query(Bed).filter(Bed.id == bed_id).first()
        if not bed:
            return f"No bed found with id {bed_id}."

        before = snapshot_model(bed)

        if soil_type is not None:
            bed.soil_type = soil_type
        if sunlight is not None:
            bed.sunlight = sunlight
        if dimensions_sqft is not None:
            error = _validate_positive_float("dimensions_sqft", dimensions_sqft)
            if error:
                return error
            bed.dimensions_sqft = dimensions_sqft
        if location is not None:
            bed.location = location
        if notes is not None:
            bed.notes = notes

        record_update_event(
            session,
            event_type="bed_updated",
            category="bed",
            summary=f"Updated bed '{bed.name}'.",
            before=before,
            obj=bed,
            subjects=[
                {"subject_type": "bed", "subject_id": bed.id, "role": "primary"},
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        session.commit()
        return f"Bed '{bed.name}' updated successfully."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to update bed: {e}")
        return f"Failed to update bed: {str(e)}"
    finally:
        session.close()


@tool
def list_beds() -> str:
    """
    List all beds in the garden with their IDs, locations, and sunlight
    conditions. Use this before adding a plant to a bed, or when the user
    asks about available bed space.
    """
    session = SessionLocal()
    try:
        beds = session.query(Bed).filter(Bed.user_id == 1).all()
        if not beds:
            return "No beds found."
        results = []
        for b in beds:
            results.append(b.to_summary())
        return "\n\n".join(results)
    except Exception as e:
        print(f"[DEBUG] Failed to list beds: {str(e)}")
        return f"Failed to list beds: {str(e)}"
    finally:
        session.close()


# ─── Container tools ────────────────────────────────────────────────────────────

@tool
def add_container(
    name: str,
    container_type: str,
    size_gallons: float,
    location: str,
    is_mobile: bool = True,
    notes: Optional[str] = None
) -> str:
    """
    Add a new container to the garden. Use this when the user acquires a new
    pot, growbag, or other container — for example 'I just got two new 15
    gallon cloth growbags' or 'I'm using a paper grocery bag in the courtyard
    bed'. Container type should be one of: 'growbag', 'pot', 'paper_bag', or
    'raised_bed'.
    """
    session = SessionLocal()
    try:
        error = _validate_container_type(container_type)
        if error:
            return error
        error = _validate_positive_float("size_gallons", size_gallons)
        if error:
            return error

        profile = session.query(GardenProfile).filter(
            GardenProfile.user_id == 1
        ).first()
        if not profile:
            return "Error: no garden profile found."

        container = Container(
            user_id=1,
            garden_profile_id=profile.id,
            name=name,
            container_type=container_type,
            size_gallons=size_gallons,
            location=location,
            is_mobile=is_mobile,
            notes=notes
        )
        session.add(container)
        session.flush()
        record_create_event(
            session,
            event_type="container_created",
            category="container",
            summary=f"Created container '{container.name}'.",
            obj=container,
            subjects=[
                {"subject_type": "container", "subject_id": container.id, "role": "primary"},
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        session.commit()
        return f"Container '{name}' added successfully with id {container.id}."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to add container: {e}")
        return f"Failed to add container: {str(e)}"
    finally:
        session.close()


@tool
def update_container(
    container_id: str,
    location: Optional[str] = None,
    notes: Optional[str] = None
) -> str:
    """
    Update a container's current location or notes. Use this when the user
    moves a container to a different part of the garden — for example
    'I moved growbag_1 to the front bed area for more sun'.
    """
    session = SessionLocal()
    try:
        container = session.query(Container).filter(
            Container.id == container_id
        ).first()
        if not container:
            return f"No container found with id {container_id}."
        before = snapshot_model(container)
        old_location = container.location
        if location is not None:
            container.location = location
        if notes is not None:
            container.notes = notes
        event_type = "container_moved" if location is not None and location != old_location else "container_updated"
        summary = (
            f"Moved container '{container.name}' from {old_location or 'unknown'} to {container.location or 'unknown'}."
            if event_type == "container_moved"
            else f"Updated container '{container.name}'."
        )
        record_update_event(
            session,
            event_type=event_type,
            category="container",
            summary=summary,
            before=before,
            obj=container,
            subjects=[
                {"subject_type": "container", "subject_id": container.id, "role": "primary"},
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        session.commit()
        return f"Container '{container.name}' updated successfully."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to update container: {e}")
        return f"Failed to update container: {str(e)}"
    finally:
        session.close()


@tool
def remove_container(container_id: str, reason: Optional[str] = None) -> str:
    """
    Remove a container from the garden. Use this when a container is no longer
    in use — for example a cloth growbag has degraded, a paper bag has
    composted into the bed, or a pot has been given away. This is a hard
    delete since containers are physical objects that genuinely leave the
    garden, unlike plants where history matters.
    """
    session = SessionLocal()
    try:
        container = session.query(Container).filter(
            Container.id == container_id
        ).first()
        if not container:
            return f"No container found with id {container_id}."

        # check if any active plants are still assigned to this container
        active_plants = session.query(Plant).filter(
            Plant.container_id == container_id,
            Plant.status != "removed"
        ).all()
        if active_plants:
            plant_names = ", ".join(p.name for p in active_plants)
            return (
                f"Cannot remove container '{container.name}' — it still has "
                f"active plants: {plant_names}. Please reassign or remove "
                f"those plants first."
            )

        # remove any project links first
        session.query(ProjectContainer).filter(
            ProjectContainer.container_id == container_id
        ).delete()

        name = container.name
        before = snapshot_model(container)
        record_delete_event(
            session,
            event_type="container_removed",
            category="container",
            summary=f"Removed container '{name}' from the garden.",
            before=before,
            metadata={"reason": reason} if reason else None,
            subjects=[
                {"subject_type": "container", "subject_id": container.id, "role": "primary"},
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        session.delete(container)
        session.commit()
        reason_text = f" Reason: {reason}." if reason else ""
        return f"Container '{name}' removed from the garden.{reason_text}"
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to remove container: {e}")
        return f"Failed to remove container: {str(e)}"
    finally:
        session.close()


@tool
def list_containers() -> str:
    """
    List all containers (pots, growbags) in the garden with their IDs,
    locations, and sizes. Use this before assigning a plant to a container,
    or when the user asks about available container space.
    """
    session = SessionLocal()
    try:
        containers = session.query(Container).filter(Container.user_id == 1).all()
        if not containers:
            return "No containers found."
        result = []
        for c in containers:
            result.append(c.to_summary())
        return "\n\n".join(result)
    except Exception as e:
        print(f"[DEBUG] Failed to list containers: {str(e)}")
        return f"Failed to list containers: {str(e)}"
    finally:
        session.close()


# ─── Container tools ────────────────────────────────────────────────────────────

@tool
def delete_bed(bed_id: str) -> str:
    """
    Permanently delete a bed record. Use this only to correct mistakes —
    for example if a bed was created in error or as a duplicate. For beds
    that are being removed from the garden entirely, this is also
    appropriate since beds don't have the same historical value as plants.

    Cannot be deleted if plants are currently assigned to it — reassign
    or remove those plants first.
    This cannot be undone. Always confirm with the user before calling this.
    """
    session = SessionLocal()
    try:
        bed = session.query(Bed).filter(Bed.id == bed_id).first()
        if not bed:
            return f"No bed found with id {bed_id}."

        before = snapshot_model(bed)

        # check for active plants
        active_plants = session.query(Plant).filter(
            Plant.bed_id == bed_id,
            Plant.status != "removed"
        ).all()
        if active_plants:
            names = ", ".join(p.name for p in active_plants)
            return (
                f"Cannot delete bed '{bed.name}' — it still has active "
                f"plants: {names}. Reassign or remove those plants first."
            )

        # remove project bed assignments
        session.query(ProjectBed).filter(
            ProjectBed.bed_id == bed_id
        ).delete()

        name = bed.name
        record_delete_event(
            session,
            event_type="bed_deleted",
            category="bed",
            summary=f"Deleted bed '{name}'.",
            before=before,
            subjects=[
                {"subject_type": "bed", "subject_id": bed.id, "role": "primary"},
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        session.delete(bed)
        session.commit()
        return f"Bed '{name}' permanently deleted."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to delete bed: {e}")
        return f"Failed to delete bed: {str(e)}"
    finally:
        session.close()
