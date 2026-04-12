# agent/tools/projects.py
"""
Agent tools for managing projects.
Tools must return strings — the LLM reads tool output as text.
"""

from langchain.tools import tool
from agent.activity_log import (
    DEFAULT_ACTOR_LABEL,
    DEFAULT_ACTOR_TYPE,
    record_activity_event,
    record_create_event,
    record_delete_event,
    record_update_event,
    snapshot_model,
)
from db.database import SessionLocal
from db.models import (
    GardenProfile, GardeningProject, Bed, Container, 
    Plant, PlantBatch, ProjectBed, ProjectContainer, ProjectPlant
)
from typing import Optional
from datetime import datetime

VALID_PROJECT_STATUSES = {"planning", "active", "maintaining", "paused", "complete"}


def _validate_project_status(status: str) -> Optional[str]:
    if status not in VALID_PROJECT_STATUSES:
        return (
            f"Invalid status '{status}'. Must be one of: "
            f"{', '.join(sorted(VALID_PROJECT_STATUSES))}."
        )
    return None


def _validate_non_negative_int(field_name: str, value: Optional[int]) -> Optional[str]:
    if value is not None and value < 0:
        return f"{field_name} must be 0 or greater."
    return None


def _validate_non_negative_float(field_name: str, value: Optional[float]) -> Optional[str]:
    if value is not None and value < 0:
        return f"{field_name} must be 0 or greater."
    return None

# ─── Project tools ────────────────────────────────────────────────────────────

@tool
def create_project(
    name: str,
    goal: str,
    tray_slots: int,
    budget_ceiling: float,
    notes: Optional[str] = None
) -> str:
    """
    Create a new gardening project. Use this when the user expresses intent
    to start a new gardening goal — for example 'I want to grow basil this
    summer' or 'let's plan a cottage garden for the front bed'. The project
    starts in 'planning' status. Returns the new project's ID on success.
    """
    session = SessionLocal()
    try:
        error = _validate_non_negative_int("tray_slots", tray_slots)
        if error:
            return error
        error = _validate_non_negative_float("budget_ceiling", budget_ceiling)
        if error:
            return error

        # look up the garden profile for this user
        profile = session.query(GardenProfile).filter(
            GardenProfile.user_id == 1
        ).first()

        if not profile:
            return "Error: no garden profile found. Please set up your garden profile first."

        project = GardeningProject(
            user_id=1,
            garden_profile_id=profile.id,   # ← was missing
            name=name,
            goal=goal,
            status="planning",
            tray_slots=tray_slots,
            budget_ceiling=budget_ceiling,
            notes=notes,
            negotiation_history=[],
            iterations=[],
        )
        session.add(project)
        session.flush()
        record_create_event(
            session,
            event_type="project_created",
            category="project",
            summary=f"Created project '{project.name}'.",
            obj=project,
            project_id=project.id,
            subjects=[
                {"subject_type": "project", "subject_id": project.id, "role": "primary"},
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        session.commit()
        return f"Project '{name}' created successfully with id {project.id}."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to create project: {e}")   # prints to terminal
        return f"Failed to create project: {str(e)}"  # LLM sees this
    finally:
        session.close()


@tool
def update_project(
    project_id: str,
    name: Optional[str] = None,
    goal: Optional[str] = None,
    status: Optional[str] = None,
    tray_slots: Optional[int] = None,
    budget_ceiling: Optional[float] = None,
    notes: Optional[str] = None
) -> str:
    """
    Update an existing gardening project. Use this when the user wants to
    change a project's details — for example updating the goal, adjusting
    the budget, or changing the status (e.g. from 'planning' to 'active',
    or 'active' to 'paused'). Only updates fields that are provided.
    Valid statuses: 'planning', 'active', 'maintaining', 'paused', 'complete'.
    """
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id
        ).first()

        if not project:
            return f"No project found with id {project_id}."

        before = snapshot_model(project)
        old_status = project.status

        # only update fields that were explicitly provided
        if name is not None:
            project.name = name
        if goal is not None:
            project.goal = goal
        if status is not None:
            error = _validate_project_status(status)
            if error:
                return error
            project.status = status
        if tray_slots is not None:
            error = _validate_non_negative_int("tray_slots", tray_slots)
            if error:
                return error
            project.tray_slots = tray_slots
        if budget_ceiling is not None:
            error = _validate_non_negative_float("budget_ceiling", budget_ceiling)
            if error:
                return error
            project.budget_ceiling = budget_ceiling
        if notes is not None:
            project.notes = notes

        changed_event_type = "project_status_changed" if status is not None and status != old_status else "project_updated"
        changed_summary = (
            f"Project '{project.name}' status changed from {old_status} to {project.status}."
            if changed_event_type == "project_status_changed"
            else f"Updated project '{project.name}'."
        )
        record_update_event(
            session,
            event_type=changed_event_type,
            category="project",
            summary=changed_summary,
            before=before,
            obj=project,
            project_id=project.id,
            subjects=[
                {"subject_type": "project", "subject_id": project.id, "role": "primary"},
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        session.commit()
        return f"Project '{project.name}' updated successfully."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to update project: {str(e)}")
        return f"Failed to update project: {str(e)}"
    finally:
        session.close()


@tool
def get_project(project_id: str) -> str:
    """
    Get full details of a specific project including its assigned beds,
    containers, and plants. Use this when the user asks about a specific
    project in detail — for example 'what's in the tomato project?',
    'which containers are assigned to the cottage garden?', or 'show me
    everything about project X'. Use list_projects first to find the
    project ID if you don't have it.
    """
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id
        ).first()
        if not project:
            return f"No project found with id {project_id}."

        beds = (
            session.query(Bed)
            .join(ProjectBed, Bed.id == ProjectBed.bed_id)
            .filter(ProjectBed.project_id == project_id)
            .all()
        )

        containers = (
            session.query(Container)
            .join(ProjectContainer, Container.id == ProjectContainer.container_id)
            .filter(ProjectContainer.project_id == project_id)
            .all()
        )

        plants = (
            session.query(Plant)
            .join(ProjectPlant, Plant.id == ProjectPlant.plant_id)
            .filter(
                ProjectPlant.project_id == project_id,
                ProjectPlant.removed_at == None
            )
            .all()
        )

        batches = session.query(PlantBatch).filter(
            PlantBatch.project_id == project_id
        ).all()

        lines = [project.to_detailed(
            plant_count=len(plants),
            bed_count=len(beds),
            container_count=len(containers),
            batch_count=len(batches)          # ← add this
        )]

        lines += ["", "Beds:"]
        lines += [f"  {b.to_detailed()}" for b in beds] or ["  none"]

        lines += ["", "Containers:"]
        lines += [f"  {c.to_detailed()}" for c in containers] or ["  none"]

        lines += ["", "Plants:"]
        for p in plants:
            location_name = None
            if p.container_id:
                container = session.query(Container).filter(
                    Container.id == p.container_id
                ).first()
                location_name = container.name if container else None
            elif p.bed_id:
                bed = session.query(Bed).filter(
                    Bed.id == p.bed_id
                ).first()
                location_name = bed.name if bed else None
            lines.append(f"  {p.to_detailed(location_name=location_name)}")

        if not plants:
            lines.append("  none")

        lines += ["", "Batches:"]
        if batches:
            for b in batches:
                plants_in_batch = session.query(Plant).filter(
                    Plant.batch_id == b.id
                ).all()
                count_dict = {}
                for p in plants_in_batch:
                    count_dict[p.status] = count_dict.get(p.status, 0) + 1
                status_summary = " | ".join(
                    f"{s}: {c}" for s, c in sorted(count_dict.items())
                ) or "none recorded"
                lines.append(
                    f"  {b.to_detailed()}\n"
                    f"    Plant status breakdown: {status_summary}"
                )
        else:
            lines.append("  none")

        return "\n".join(lines)

    except Exception as e:
        print(f"[DEBUG] Failed to get project: {e}")
        return f"Failed to get project: {str(e)}"
    finally:
        session.close()


@tool
def list_projects(status: Optional[str] = None) -> str:
    """
    List all gardening projects. Use this when the user asks what projects
    exist, what they are working on, or wants an overview of their garden
    plans. Optionally filter by status — for example status='active' returns
    only currently active projects.
    """
    session = SessionLocal()
    try:
        if status:
            error = _validate_project_status(status)
            if error:
                return error

        query = session.query(GardeningProject).filter(
            GardeningProject.user_id == 1
        )
        if status:
            query = query.filter(GardeningProject.status == status)

        projects = query.all()

        if not projects:
            return "No projects found."

        result = []
        for p in projects:
            plant_count = session.query(Plant).join(
                ProjectPlant, Plant.id == ProjectPlant.plant_id
            ).filter(
                ProjectPlant.project_id == p.id,
                ProjectPlant.removed_at == None
            ).count()
            bed_count = session.query(ProjectBed).filter(
                ProjectBed.project_id == p.id
            ).count()
            container_count = session.query(ProjectContainer).filter(
                ProjectContainer.project_id == p.id
            ).count()
            batch_count = session.query(PlantBatch).filter(
                PlantBatch.project_id == p.id
            ).count()
            result.append(p.to_summary(
                plant_count=plant_count,
                bed_count=bed_count,
                container_count=container_count,
                batch_count=batch_count
            ))
        return "\n\n".join(result)
    except Exception as e:
        print(f"[DEBUG] Failed to list projects: {str(e)}")
        return f"Failed to list projects: {str(e)}"
    finally:
        session.close()

# ─── Bed and Container Assignment tools ────────────────────────────────────────────────────────────

@tool
def assign_bed_to_project(project_id: str, bed_id: str) -> str:
    """
    Assign a bed to a project to indicate that project is using that bed.
    Use this when a project is being planned or started and the user
    confirms which beds it will use. Also use to check for conflicts —
    if a bed is already assigned to another active project this will
    flag it.
    """
    session = SessionLocal()
    try:

        # verify both exist
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id
        ).first()
        if not project:
            return f"No project found with id {project_id}."

        bed = session.query(Bed).filter(Bed.id == bed_id).first()
        if not bed:
            return f"No bed found with id {bed_id}."

        # check if bed is already assigned to another active project
        existing = (
            session.query(ProjectBed)
            .join(GardeningProject, ProjectBed.project_id == GardeningProject.id)
            .filter(
                ProjectBed.bed_id == bed_id,
                GardeningProject.status.in_(["planning", "active"]),
                GardeningProject.id != project_id
            )
            .first()
        )
        if existing:
            conflicting = session.query(GardeningProject).filter(
                GardeningProject.id == existing.project_id
            ).first()
            return (
                f"Bed '{bed.name}' is already assigned to active project "
                f"'{conflicting.name}'. Resolve this conflict before "
                f"assigning it to '{project.name}'."
            )

        # check not already assigned to this project
        already = session.query(ProjectBed).filter(
            ProjectBed.project_id == project_id,
            ProjectBed.bed_id == bed_id
        ).first()
        if already:
            return f"Bed '{bed.name}' is already assigned to '{project.name}'."

        session.add(ProjectBed(project_id=project_id, bed_id=bed_id))
        record_activity_event(
            session,
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
            event_type="project_bed_assigned",
            category="project",
            summary=f"Assigned bed '{bed.name}' to project '{project.name}'.",
            project_id=project.id,
            subjects=[
                {"subject_type": "project", "subject_id": project.id, "role": "primary"},
                {"subject_type": "bed", "subject_id": bed.id, "role": "affected"},
            ],
        )
        session.commit()
        return f"Bed '{bed.name}' assigned to project '{project.name}'."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to assign bed: {e}")
        return f"Failed to assign bed: {str(e)}"
    finally:
        session.close()


@tool
def assign_container_to_project(project_id: str, container_id: str) -> str:
    """
    Assign a container to a project to indicate that project is using it.
    Use this when a project is being planned or started and the user
    confirms which containers it will use. Flags conflicts if the container
    is already assigned to another active project.
    """
    session = SessionLocal()
    try:

        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id
        ).first()
        if not project:
            return f"No project found with id {project_id}."

        container = session.query(Container).filter(
            Container.id == container_id
        ).first()
        if not container:
            return f"No container found with id {container_id}."

        # check if already assigned to another active project
        existing = (
            session.query(ProjectContainer)
            .join(GardeningProject, ProjectContainer.project_id == GardeningProject.id)
            .filter(
                ProjectContainer.container_id == container_id,
                GardeningProject.status.in_(["planning", "active"]),
                GardeningProject.id != project_id
            )
            .first()
        )
        if existing:
            conflicting = session.query(GardeningProject).filter(
                GardeningProject.id == existing.project_id
            ).first()
            return (
                f"Container '{container.name}' is already assigned to active "
                f"project '{conflicting.name}'. Resolve this conflict before "
                f"assigning it to '{project.name}'."
            )

        already = session.query(ProjectContainer).filter(
            ProjectContainer.project_id == project_id,
            ProjectContainer.container_id == container_id
        ).first()
        if already:
            return f"Container '{container.name}' is already assigned to '{project.name}'."

        session.add(ProjectContainer(project_id=project_id, container_id=container_id))
        record_activity_event(
            session,
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
            event_type="project_container_assigned",
            category="project",
            summary=f"Assigned container '{container.name}' to project '{project.name}'.",
            project_id=project.id,
            subjects=[
                {"subject_type": "project", "subject_id": project.id, "role": "primary"},
                {"subject_type": "container", "subject_id": container.id, "role": "affected"},
            ],
        )
        session.commit()
        return f"Container '{container.name}' assigned to project '{project.name}'."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to assign container: {e}")
        return f"Failed to assign container: {str(e)}"
    finally:
        session.close()


@tool
def unassign_bed_from_project(project_id: str, bed_id: str) -> str:
    """
    Remove a bed assignment from a project. Use this when a bed is no
    longer being used by a project — for example when a project is
    complete or the plan has changed.
    """
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id
        ).first()
        bed = session.query(Bed).filter(Bed.id == bed_id).first()
        row = session.query(ProjectBed).filter(
            ProjectBed.project_id == project_id,
            ProjectBed.bed_id == bed_id
        ).first()
        if not row:
            return "That bed is not assigned to this project."
        session.delete(row)
        if project and bed:
            record_activity_event(
                session,
                actor_type=DEFAULT_ACTOR_TYPE,
                actor_label=DEFAULT_ACTOR_LABEL,
                event_type="project_bed_unassigned",
                category="project",
                summary=f"Unassigned bed '{bed.name}' from project '{project.name}'.",
                project_id=project.id,
                subjects=[
                    {"subject_type": "project", "subject_id": project.id, "role": "primary"},
                    {"subject_type": "bed", "subject_id": bed.id, "role": "affected"},
                ],
            )
        session.commit()
        return "Bed unassigned from project."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to unassign bed: {e}")
        return f"Failed to unassign bed: {str(e)}"
    finally:
        session.close()


@tool
def unassign_container_from_project(project_id: str, container_id: str) -> str:
    """
    Remove a container assignment from a project. Use this when a container
    is no longer being used by a project.
    """
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id
        ).first()
        container = session.query(Container).filter(
            Container.id == container_id
        ).first()
        row = session.query(ProjectContainer).filter(
            ProjectContainer.project_id == project_id,
            ProjectContainer.container_id == container_id
        ).first()
        if not row:
            return "That container is not assigned to this project."
        session.delete(row)
        if project and container:
            record_activity_event(
                session,
                actor_type=DEFAULT_ACTOR_TYPE,
                actor_label=DEFAULT_ACTOR_LABEL,
                event_type="project_container_unassigned",
                category="project",
                summary=f"Unassigned container '{container.name}' from project '{project.name}'.",
                project_id=project.id,
                subjects=[
                    {"subject_type": "project", "subject_id": project.id, "role": "primary"},
                    {"subject_type": "container", "subject_id": container.id, "role": "affected"},
                ],
            )
        session.commit()
        return "Container unassigned from project."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to unassign container: {e}")
        return f"Failed to unassign container: {str(e)}"
    finally:
        session.close()

# ─── Plant Assignment tools ────────────────────────────────────────────────────────────

@tool
def add_plant_to_project(project_id: str, plant_id: str, notes: Optional[str] = None) -> str:
    """
    Add an existing plant to a project. Use this when the user wants to
    include a plant that already exists in their garden in a project —
    for example 'add my established rose to the slope renovation project'
    or 'include the courtyard lavender in the cottage garden project'.
    """
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id
        ).first()
        if not project:
            return f"No project found with id {project_id}."

        plant = session.query(Plant).filter(Plant.id == plant_id).first()
        if not plant:
            return f"No plant found with id {plant_id}."

        # check not already actively coupled
        existing = session.query(ProjectPlant).filter(
            ProjectPlant.project_id == project_id,
            ProjectPlant.plant_id == plant_id,
            ProjectPlant.removed_at == None
        ).first()
        if existing:
            return f"'{plant.name}' is already active in project '{project.name}'."

        session.add(ProjectPlant(
            project_id=project_id,
            plant_id=plant_id,
            notes=notes
        ))
        record_activity_event(
            session,
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
            event_type="project_plant_added",
            category="project",
            summary=f"Added plant '{plant.name}' to project '{project.name}'.",
            notes=notes,
            project_id=project.id,
            subjects=[
                {"subject_type": "project", "subject_id": project.id, "role": "primary"},
                {"subject_type": "plant", "subject_id": plant.id, "role": "affected"},
            ],
            metadata={"reason": notes} if notes else None,
        )
        session.commit()
        return f"'{plant.name}' added to project '{project.name}'."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to add plant to project: {e}")
        return f"Failed to add plant to project: {str(e)}"
    finally:
        session.close()


@tool
def remove_plant_from_project(project_id: str, plant_id: str, reason: Optional[str] = None) -> str:
    """
    Decouple a plant from a project without removing it from the garden.
    Use this when a plant is no longer part of a project but still exists
    — for example 'the basil has finished, remove it from the summer
    project' or 'I want to move the rose to a different project'.
    The plant remains in the garden and can be added to another project.
    """
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id
        ).first()
        plant = session.query(Plant).filter(Plant.id == plant_id).first()

        link = session.query(ProjectPlant).filter(
            ProjectPlant.project_id == project_id,
            ProjectPlant.plant_id == plant_id,
            ProjectPlant.removed_at == None
        ).first()
        if not link:
            return "That plant is not currently active in this project."

        link.removed_at = datetime.utcnow()
        if reason:
            link.notes = f"{link.notes or ''}\nRemoved: {reason}".strip()
        if project and plant:
            record_activity_event(
                session,
                actor_type=DEFAULT_ACTOR_TYPE,
                actor_label=DEFAULT_ACTOR_LABEL,
                event_type="project_plant_removed",
                category="project",
                summary=f"Removed plant '{plant.name}' from project '{project.name}'.",
                project_id=project.id,
                subjects=[
                    {"subject_type": "project", "subject_id": project.id, "role": "primary"},
                    {"subject_type": "plant", "subject_id": plant.id, "role": "affected"},
                ],
                metadata={"reason": reason} if reason else None,
            )
        session.commit()
        return "Plant decoupled from project. It remains in your garden."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to remove plant from project: {e}")
        return f"Failed to remove plant from project: {str(e)}"
    finally:
        session.close()


# ─── Delete tool ────────────────────────────────────────────────────────────

@tool
def delete_project(project_id: str) -> str:
    """
    IMPORTANT: Always confirm with the user before calling this tool.
    Describe what will be deleted and wait for explicit confirmation.
    
    Permanently delete a project record. Use this only to correct mistakes
    — for example if a project was created in error or as a duplicate. For
    projects that are finished, use update_project with status='complete'
    instead which preserves the history.
    
    This will also delete all ProjectPlant, ProjectBed, ProjectContainer,
    and PlantBatch links associated with this project. Plants themselves
    are NOT deleted — they remain in the garden unlinked.
    This cannot be undone. Always confirm with the user before calling this.
    """
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id
        ).first()
        if not project:
            return f"No project found with id {project_id}."

        before = snapshot_model(project)

        # unlink plants from project
        links = session.query(ProjectPlant).filter(
            ProjectPlant.project_id == project_id
        ).all()
        for link in links:
            session.delete(link)

        # remove bed assignments
        session.query(ProjectBed).filter(
            ProjectBed.project_id == project_id
        ).delete()

        # remove container assignments
        session.query(ProjectContainer).filter(
            ProjectContainer.project_id == project_id
        ).delete()

        # unlink batches — keep batch records but clear project_id
        batches = session.query(PlantBatch).filter(
            PlantBatch.project_id == project_id
        ).all()
        for batch in batches:
            batch.project_id = None

        name = project.name
        link_count = len(links)
        batch_count = len(batches)
        record_delete_event(
            session,
            event_type="project_deleted",
            category="project",
            summary=(
                f"Deleted project '{name}'. "
                f"Removed {link_count} plant links and unlinked {batch_count} batches."
            ),
            before=before,
            project_id=project.id,
            metadata={
                "link_count": link_count,
                "batch_count": batch_count,
            },
            subjects=[
                {"subject_type": "project", "subject_id": project.id, "role": "primary"},
            ],
            actor_type=DEFAULT_ACTOR_TYPE,
            actor_label=DEFAULT_ACTOR_LABEL,
        )
        session.delete(project)
        session.commit()
        return (
            f"Project '{name}' permanently deleted. "
            f"{len(links)} plant links, bed and container assignments removed. "
            f"{len(batches)} batches unlinked but preserved."
        )
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to delete project: {e}")
        return f"Failed to delete project: {str(e)}"
    finally:
        session.close()
