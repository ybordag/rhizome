"""
Agent tools for managing plants.
Tools must return strings — the LLM reads tool output as text.
"""
from langchain.tools import tool
from typing import Optional
from datetime import datetime
from db.database import SessionLocal
from db.models import GardenProfile, GardeningProject, Bed, Container, Plant, PlantBatch, ProjectPlant

# ─── Plant tools ──────────────────────────────────────────────────────────────

@tool
def add_plant(
    name: str,
    batch_id: Optional[str] = None,   # ← add this parameter
    variety: Optional[str] = None,
    quantity: int = 1,
    source: Optional[str] = None,
    propagated_from: Optional[str] = None,
    container_id: Optional[str] = None,
    bed_id: Optional[str] = None,
    status: Optional[str] = None,            # ← explicit, no default
    sow_date: Optional[str] = None,
    red_cup_date: Optional[str] = None,
    transplant_date: Optional[str] = None,
    is_flowering: Optional[bool] = None,     # ← missing from original
    is_fruiting: Optional[bool] = None,      # ← missing from original
    fertilizing_schedule: Optional[str] = None,
    last_fertilized_at: Optional[str] = None, # ← missing from original
    special_instructions: Optional[str] = None,
    notes: Optional[str] = None
) -> str:
    """
    Add a plant to the garden. Use this for both new plants being started
    now AND for recording existing plants with history.

    batch_id: if this plant belongs to an existing batch — for example
    adding one more cutting to a batch you already created — provide the
    batch id here. Use list_batches to find the batch id. If starting a
    new group of the same plant type, use batch_add_plant_type instead
    which creates the batch and plants together.

    Status should reflect the plant's actual current state:
    - 'planned': not yet started
    - 'germinating': seeds sown, not yet sprouted
    - 'seedling': sprouted, in seed tray
    - 'established': transplanted and growing well
    - 'producing': actively flowering or fruiting
    - 'dormant': alive but not actively growing
    - 'removed': no longer in the garden

    If status is not provided, it is inferred:
    - no dates provided → 'planned'
    - sow_date provided, no transplant_date → 'seedling'
    - transplant_date provided → 'established'

    Source: 'seed', 'cutting', 'propagation', 'transplant', 'existing'

    Date defaults (only when not explicitly provided and status
    cannot tell us otherwise):
    - source='seed' and status is 'seedling' or not set → sow_date defaults to today
    - source in ('cutting','propagation','transplant') and no transplant_date
      → transplant_date defaults to today

    All dates in ISO format e.g. '2026-02-15'.
    """
    session = SessionLocal()
    try:
        profile = session.query(GardenProfile).filter(
            GardenProfile.user_id == 1
        ).first()
        if not profile:
            return "Error: no garden profile found."

        now = datetime.utcnow()

        # parse explicit dates
        parsed_sow = datetime.fromisoformat(sow_date) if sow_date else None
        parsed_red_cup = datetime.fromisoformat(red_cup_date) if red_cup_date else None
        parsed_transplant = datetime.fromisoformat(transplant_date) if transplant_date else None
        parsed_last_fertilized = datetime.fromisoformat(last_fertilized_at) if last_fertilized_at else None

        # infer status from available data if not explicitly provided
        inferred_status = status
        if inferred_status is None:
            if parsed_transplant is not None:
                inferred_status = "established"
            elif parsed_sow is not None:
                inferred_status = "seedling"
            else:
                inferred_status = "planned"

        # apply date defaults only for new plants with no history
        # don't override explicit dates or contradict provided status
        if parsed_sow is None and source == "seed" and (inferred_status == "germinating" or inferred_status == "seedling"):
            parsed_sow = now
        if parsed_transplant is None and source in ("cutting", "propagation", "transplant") and inferred_status in ("planned", "established"):
            parsed_transplant = now

        plant = Plant(
            user_id=1,
            garden_profile_id=profile.id,
            batch_id=batch_id,
            name=name,
            variety=variety,
            quantity=quantity,
            source=source,
            propagated_from=propagated_from,
            container_id=container_id,
            bed_id=bed_id,
            status=inferred_status,
            sow_date=parsed_sow,
            red_cup_date=parsed_red_cup,
            transplant_date=parsed_transplant,
            is_flowering=is_flowering or False,
            is_fruiting=is_fruiting or False,
            fertilizing_schedule=fertilizing_schedule,
            last_fertilized_at=parsed_last_fertilized,
            special_instructions=special_instructions,
            notes=notes
        )
        session.add(plant)
        session.commit()
        return (
            f"Added {quantity}x {name} {variety or ''} to your garden "
            f"with id {plant.id} (status: {inferred_status})."
        )
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to add plant: {e}")
        return f"Failed to add plant: {str(e)}"
    finally:
        session.close()


@tool
def update_plant(
    plant_id: str,
    status: Optional[str] = None,
    is_flowering: Optional[bool] = None,
    is_fruiting: Optional[bool] = None,
    last_fertilized_at: Optional[str] = None,  # ISO date string e.g. "2026-03-15"
    fertilizing_schedule: Optional[str] = None,
    special_instructions: Optional[str] = None,
    notes: Optional[str] = None
) -> str:
    """
    Update a plant's current status or care information. Use this when the
    user reports a change — for example 'my tomatoes started flowering',
    'I just fertilized the basil', or 'the pepper plant isn't doing well'.
    Valid statuses: 'planned', 'germinating', 'seedling', 'established',
    'producing', 'dormant', 'removed'.
    """
    session = SessionLocal()
    try:
        plant = session.query(Plant).filter(Plant.id == plant_id).first()
        if not plant:
            return f"No plant found with id {plant_id}."

        if status is not None:
            plant.status = status
        if is_flowering is not None:
            plant.is_flowering = is_flowering
        if is_fruiting is not None:
            plant.is_fruiting = is_fruiting
        if last_fertilized_at is not None:
            plant.last_fertilized_at = datetime.fromisoformat(last_fertilized_at)
        if fertilizing_schedule is not None:
            plant.fertilizing_schedule = fertilizing_schedule
        if special_instructions is not None:
            plant.special_instructions = special_instructions
        if notes is not None:
            plant.notes = notes

        session.commit()
        return f"Plant '{plant.name}' updated successfully."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to update plant: {str(e)}")
        return f"Failed to update plant: {str(e)}"
    finally:
        session.close()


@tool
def remove_plant(plant_id: str, reason: Optional[str] = None) -> str:
    """
    Mark a plant as removed from the garden. Use this when the user says a
    plant died, was pulled out, or is no longer in the garden. This sets the
    status to 'removed' rather than deleting the record — the history is
    preserved for future reference. Provide a reason when known — it is
    recorded on the plant and in the batch log.
    """
    session = SessionLocal()
    try:
        plant = session.query(Plant).filter(Plant.id == plant_id).first()
        if not plant:
            return f"No plant found with id {plant_id}."

        now = datetime.utcnow()
        timestamp = now.strftime("%B %d, %Y")

        # close out active project links
        active_links = session.query(ProjectPlant).filter(
            ProjectPlant.plant_id == plant_id,
            ProjectPlant.removed_at == None
        ).all()
        for link in active_links:
            link.removed_at = now
            link.notes = f"{link.notes or ''}\nAuto-decoupled: plant removed from garden".strip()

        # record reason on the plant before updating status
        if reason:
            plant.notes = f"{plant.notes or ''}\n{timestamp}: Removed — {reason}".strip()

        plant.status = "removed"

        # update batch log after plant notes are finalized
        if plant.batch_id:
            batch = session.query(PlantBatch).filter(
                PlantBatch.id == plant.batch_id
            ).first()
            if batch:
                batch_entry = (
                    f"{timestamp}: 1 plant removed"
                    + (f" — {reason}" if reason else "")
                    + "."
                )
                batch.notes = f"{batch.notes or ''}\n{batch_entry}".strip()

        session.commit()

        if active_links:
            return (
                f"Plant '{plant.name}' marked as removed and decoupled "
                f"from {len(active_links)} project(s)."
                + (f" Reason: {reason}" if reason else "")
            )
        return (
            f"Plant '{plant.name}' marked as removed."
            + (f" Reason: {reason}" if reason else "")
        )
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to remove plant: {e}")
        return f"Failed to remove plant: {str(e)}"
    finally:
        session.close()


@tool
def list_plants(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    batch_id: Optional[str] = None
) -> str:
    """
    List plants in the garden. Use this when the user asks what plants are
    in a project, what is currently growing, or wants to check the status
    of specific plants. Filter by project_id to see plants in a specific
    project, by status to see e.g. all 'established' plants, or by batch_id
    to see all plants from a specific batch — useful for tracking how a
    sowing is progressing. Use list_batches to find batch IDs.
    """
    session = SessionLocal()
    try:
        query = session.query(Plant).filter(Plant.user_id == 1)

        if project_id:
            query = query.join(
                ProjectPlant, Plant.id == ProjectPlant.plant_id
            ).filter(
                ProjectPlant.project_id == project_id,
                ProjectPlant.removed_at == None
            )

        if batch_id:
            query = query.filter(Plant.batch_id == batch_id)

        if status:
            query = query.filter(Plant.status == status)

        # exclude removed plants by default unless explicitly requested
        if status != "removed":
            query = query.filter(Plant.status != "removed")

        plants = query.all()

        if not plants:
            return "No plants found."

        result = []
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
            result.append(p.to_summary(location_name=location_name))

        return "\n\n".join(result)

    except Exception as e:
        print(f"[DEBUG] Failed to list plants: {str(e)}")
        return f"Failed to list plants: {str(e)}"
    finally:
        session.close()


# ─── Batch tools ──────────────────────────────────────────────────────────────

@tool
def batch_add_plant_type(
    name: str,
    quantity: int,
    project_id: Optional[str] = None,
    variety: Optional[str] = None,
    source: Optional[str] = None,
    propagated_from: Optional[str] = None,
    container_id: Optional[str] = None,
    bed_id: Optional[str] = None,
    status: Optional[str] = None,
    sow_date: Optional[str] = None,
    red_cup_date: Optional[str] = None,
    transplant_date: Optional[str] = None,
    is_flowering: Optional[bool] = None,
    is_fruiting: Optional[bool] = None,
    fertilizing_schedule: Optional[str] = None,
    last_fertilized_at: Optional[str] = None,
    special_instructions: Optional[str] = None,
    supplier: Optional[str] = None,           # ← renamed from seed_supplier
    supplier_reference: Optional[str] = None, # ← renamed from seed_lot
    grow_light: Optional[str] = None,         # ← renamed from grow_light_id
    tray: Optional[str] = None,               # ← renamed from tray_id
    batch_name: Optional[str] = None,
    notes: Optional[str] = None
) -> str:
    """
    Add multiple individual plant records of the same type in one operation.
    Use this when starting any batch of the same plant — seeds sown in trays,
    cuttings taken from a parent plant, or a 6-pack of pansies from the
    nursery. Each plant gets its own record for individual tracking.

    source: 'seed', 'cutting', 'propagation', 'transplant', 'existing'
    supplier: where they came from — seed company, nursery name, friend's
    garden, etc.
    supplier_reference: seed lot number, nursery receipt, variety tag, etc.
    grow_light: free text label for which grow light fixture e.g. 'light_1'
    tray: free text label for which physical tray e.g. 'tray_A'

    sow_date for seeds, or acquisition date for nursery transplants.
    All dates in ISO format e.g. '2026-02-15'.
    """
    session = SessionLocal()
    try:
        profile = session.query(GardenProfile).filter(
            GardenProfile.user_id == 1
        ).first()
        if not profile:
            return "Error: no garden profile found."

        if project_id:
            project = session.query(GardeningProject).filter(
                GardeningProject.id == project_id
            ).first()
            if not project:
                return f"No project found with id {project_id}."

        now = datetime.utcnow()

        parsed_sow = datetime.fromisoformat(sow_date) if sow_date else None
        parsed_red_cup = datetime.fromisoformat(red_cup_date) if red_cup_date else None
        parsed_transplant = datetime.fromisoformat(transplant_date) if transplant_date else None
        parsed_last_fertilized = datetime.fromisoformat(last_fertilized_at) if last_fertilized_at else None

        inferred_status = status
        if inferred_status is None:
            if parsed_transplant is not None:
                inferred_status = "established"
            elif parsed_sow is not None:
                inferred_status = "seedling"
            else:
                inferred_status = "planned"

        if parsed_sow is None and source == "seed" and inferred_status in ("germinating", "seedling"):
            parsed_sow = now
        if parsed_transplant is None and source in ("cutting", "propagation", "transplant") and inferred_status in ("planned", "established"):
            parsed_transplant = now

        # create batch record
        batch = PlantBatch(
            user_id=1,
            garden_profile_id=profile.id,
            project_id=project_id,
            name=batch_name or f"{name} {variety or ''} {now.strftime('%B %Y')}".strip(),
            plant_name=name,
            variety=variety,
            quantity_sown=quantity,
            sow_date=parsed_sow or parsed_transplant,
            source=source,
            supplier=supplier,
            supplier_reference=supplier_reference,
            grow_light=grow_light,
            tray=tray,
            notes=notes
        )
        session.add(batch)
        session.flush()

        # create individual plant records
        created = []
        for _ in range(quantity):
            plant = Plant(
                user_id=1,
                garden_profile_id=profile.id,
                batch_id=batch.id,
                name=name,
                variety=variety,
                quantity=1,
                source=source,
                propagated_from=propagated_from,
                container_id=container_id,
                bed_id=bed_id,
                status=inferred_status,
                sow_date=parsed_sow,
                red_cup_date=parsed_red_cup,
                transplant_date=parsed_transplant,
                is_flowering=is_flowering or False,
                is_fruiting=is_fruiting or False,
                fertilizing_schedule=fertilizing_schedule,
                last_fertilized_at=parsed_last_fertilized,
                special_instructions=special_instructions,
                notes=notes
            )
            session.add(plant)
            created.append(plant)

        session.flush()

        if project_id:
            for plant in created:
                session.add(ProjectPlant(
                    project_id=project_id,
                    plant_id=plant.id
                ))

        session.commit()

        action = "acquired" if source in ("transplant", "existing") else "sown"
        return (
            f"Created batch '{batch.name}' (id: {batch.id}) and added "
            f"{quantity} {name} {variety or ''} plants "
            f"(status: {inferred_status}, {action} today)."
            + (f" Linked to project." if project_id else "")
        )
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to batch add plant type: {e}")
        return f"Failed to batch add plant type: {str(e)}"
    finally:
        session.close()


@tool
def batch_update_plants(
    name: str,
    project_id: Optional[str] = None,
    variety: Optional[str] = None,
    current_status: Optional[str] = None,
    quantity: Optional[int] = None,
    new_status: Optional[str] = None,
    is_flowering: Optional[bool] = None,
    is_fruiting: Optional[bool] = None,
    red_cup_date: Optional[str] = None,
    transplant_date: Optional[str] = None,
    last_fertilized_at: Optional[str] = None,
    fertilizing_schedule: Optional[str] = None,
    special_instructions: Optional[str] = None,
    update_reason: Optional[str] = None,
    notes: Optional[str] = None
) -> str:
    """
    Update all plants of a given name/variety matching optional filters.
    Use this when the user reports a change affecting a whole group — for
    example 'all my Sungold tomatoes are now flowering', 'I just fertilized
    all the basil', or 'move 8 cosmos seedlings to red cups today'.

    Filters: name is required. Narrow with variety, project_id, or
    current_status.

    quantity: if provided, updates only that many plants (oldest first).
    If not provided, updates all matching plants.

    update_reason: optional note about why this update was made — recorded
    on each plant and appended to the batch log.

    Only fields explicitly provided are updated.
    """
    session = SessionLocal()
    try:
        query = session.query(Plant).filter(
            Plant.user_id == 1,
            Plant.name.ilike(f"%{name}%"),
            Plant.status != "removed"
        )
        if variety:
            query = query.filter(Plant.variety.ilike(f"%{variety}%"))
        if current_status:
            query = query.filter(Plant.status == current_status)
        if project_id:
            query = query.join(
                ProjectPlant, Plant.id == ProjectPlant.plant_id
            ).filter(
                ProjectPlant.project_id == project_id,
                ProjectPlant.removed_at == None
            )

        query = query.order_by(Plant.created_at.asc())
        plants = query.all()

        if not plants:
            return (
                f"No plants found matching '{name}'"
                + (f" with status '{current_status}'" if current_status else "")
                + "."
            )

        if quantity is not None:
            if quantity > len(plants):
                return (
                    f"Requested to update {quantity} plants but only "
                    f"{len(plants)} matching plants found. "
                    f"Update all {len(plants)}? If so, call again without quantity."
                )
            plants = plants[:quantity]

        parsed_red_cup = datetime.fromisoformat(red_cup_date) if red_cup_date else None
        parsed_transplant = datetime.fromisoformat(transplant_date) if transplant_date else None
        parsed_last_fertilized = datetime.fromisoformat(last_fertilized_at) if last_fertilized_at else None

        now = datetime.utcnow()
        timestamp = now.strftime("%B %d, %Y")

        # collect unique batch ids affected
        affected_batch_ids = set()

        for plant in plants:
            if new_status is not None:
                plant.status = new_status
            if is_flowering is not None:
                plant.is_flowering = is_flowering
            if is_fruiting is not None:
                plant.is_fruiting = is_fruiting
            if parsed_red_cup is not None:
                plant.red_cup_date = parsed_red_cup
            if parsed_transplant is not None:
                plant.transplant_date = parsed_transplant
            if parsed_last_fertilized is not None:
                plant.last_fertilized_at = parsed_last_fertilized
            if fertilizing_schedule is not None:
                plant.fertilizing_schedule = fertilizing_schedule
            if special_instructions is not None:
                plant.special_instructions = special_instructions
            if notes is not None:
                plant.notes = f"{plant.notes or ''}\n{notes}".strip()
            if update_reason:
                plant.notes = f"{plant.notes or ''}\n{timestamp}: {update_reason}".strip()

            if plant.batch_id:
                affected_batch_ids.add(plant.batch_id)

        # append update summary to each affected batch's notes
        if affected_batch_ids:
            changes = []
            if new_status:
                changes.append(f"status → {new_status}")
            if parsed_red_cup:
                changes.append(f"red cup date → {red_cup_date}")
            if parsed_transplant:
                changes.append(f"transplant date → {transplant_date}")
            if parsed_last_fertilized:
                changes.append(f"fertilized")
            if update_reason:
                changes.append(update_reason)

            batch_log_entry = (
                f"{timestamp}: Updated {len(plants)} plants"
                + (f" — {', '.join(changes)}" if changes else "")
                + "."
            )

            for batch_id in affected_batch_ids:
                batch = session.query(PlantBatch).filter(
                    PlantBatch.id == batch_id
                ).first()
                if batch:
                    batch.notes = f"{batch.notes or ''}\n{batch_log_entry}".strip()

        session.commit()
        return (
            f"Updated {len(plants)} {name} {variety or ''} plants"
            + (f" — {update_reason}" if update_reason else "")
            + "."
        )
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to batch update plants: {e}")
        return f"Failed to batch update plants: {str(e)}"
    finally:
        session.close()


@tool
def batch_remove_plants(
    name: str,
    reason: str,
    project_id: Optional[str] = None,
    variety: Optional[str] = None,
    current_status: Optional[str] = None,
    quantity: Optional[int] = None
) -> str:
    """
    Remove a group of plants from the garden. Use this when the user culls
    unhealthy seedlings, removes a batch that didn't make it, or digs up
    a set of plants. Common cases:
    - Culling weak seedlings during tray-to-red-cup transplant
    - Removing a batch that failed to germinate or got root rot
    - Digging up plants at end of season

    reason is required — it is recorded on each plant and appended to
    the batch log so you have a history of what happened to the batch.

    Filters: name required. Narrow with variety, project_id, or
    current_status — for example current_status='seedling' to only
    remove seedlings, not established plants of the same type.

    quantity: if provided, removes only that many plants (oldest records
    first). If not provided, removes all matching plants.

    Soft delete — plants are marked 'removed', not deleted. Project
    links are closed out automatically.
    """
    session = SessionLocal()
    try:
        query = session.query(Plant).filter(
            Plant.user_id == 1,
            Plant.name.ilike(f"%{name}%"),
            Plant.status != "removed"
        )
        if variety:
            query = query.filter(Plant.variety.ilike(f"%{variety}%"))
        if current_status:
            query = query.filter(Plant.status == current_status)
        if project_id:
            query = query.join(
                ProjectPlant, Plant.id == ProjectPlant.plant_id
            ).filter(
                ProjectPlant.project_id == project_id,
                ProjectPlant.removed_at == None
            )

        query = query.order_by(Plant.created_at.asc())
        plants = query.all()

        if not plants:
            return (
                f"No plants found matching '{name}'"
                + (f" with status '{current_status}'" if current_status else "")
                + "."
            )

        if quantity is not None:
            if quantity > len(plants):
                return (
                    f"Requested to remove {quantity} plants but only "
                    f"{len(plants)} matching plants found. "
                    f"Remove all {len(plants)}? If so, call again without quantity."
                )
            plants = plants[:quantity]

        now = datetime.utcnow()
        timestamp = now.strftime("%B %d, %Y")
        affected_batch_ids = set()

        for plant in plants:
            plant.status = "removed"
            plant.notes = f"{plant.notes or ''}\n{timestamp}: Removed — {reason}".strip()

            # close out active project links
            active_links = session.query(ProjectPlant).filter(
                ProjectPlant.plant_id == plant.id,
                ProjectPlant.removed_at == None
            ).all()
            for link in active_links:
                link.removed_at = now
                link.notes = f"{link.notes or ''}\nAuto-decoupled: {reason}".strip()

            if plant.batch_id:
                affected_batch_ids.add(plant.batch_id)

        # append removal summary to each affected batch's notes
        if affected_batch_ids:
            batch_log_entry = (
                f"{timestamp}: Removed {len(plants)} plants — {reason}."
            )
            for batch_id in affected_batch_ids:
                batch = session.query(PlantBatch).filter(
                    PlantBatch.id == batch_id
                ).first()
                if batch:
                    batch.notes = f"{batch.notes or ''}\n{batch_log_entry}".strip()

        session.commit()
        return (
            f"Removed {len(plants)} {name} {variety or ''} plants. "
            f"Reason: {reason}"
        )
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to batch remove plants: {e}")
        return f"Failed to batch remove plants: {str(e)}"
    finally:
        session.close()


@tool
def list_batches(project_id: Optional[str] = None) -> str:
    """
    List plant batches in the garden. Use this when the user asks about
    their seedling batches, what they have sown or acquired, or wants to
    see growing conditions across batches. Filter by project_id to see
    batches for a specific project.
    """
    session = SessionLocal()
    try:
        query = session.query(PlantBatch).filter(
            PlantBatch.user_id == 1
        )
        if project_id:
            query = query.filter(PlantBatch.project_id == project_id)

        batches = query.order_by(PlantBatch.created_at.desc()).all()

        if not batches:
            return "No batches found."

        result = []
        for b in batches:
            plants = session.query(Plant).filter(Plant.batch_id == b.id).all()
            counts = {}
            for p in plants:
                counts[p.status] = counts.get(p.status, 0) + 1
            status_summary = " | ".join(
                f"{status}: {count}"
                for status, count in sorted(counts.items())
            ) or "none recorded"
            result.append(
                b.to_summary()
                + f"\n  Plant status breakdown: {status_summary}"
            )

        return "\n\n".join(result)
    except Exception as e:
        print(f"[DEBUG] Failed to list batches: {e}")
        return f"Failed to list batches: {str(e)}"
    finally:
        session.close()


@tool
def delete_plant(plant_id: str) -> str:
    """
    IMPORTANT: Always confirm with the user before calling this tool.
    Describe what will be deleted and wait for explicit confirmation.

    Permanently delete a plant record. Use this only to correct mistakes —
    for example if a plant was created in error or as a duplicate. For
    plants that actually died or were removed from the garden, use
    remove_plant instead which preserves the history.
    This cannot be undone.
    """
    session = SessionLocal()
    try:
        plant = session.query(Plant).filter(Plant.id == plant_id).first()
        if not plant:
            return f"No plant found with id {plant_id}."

        # close out project links first
        session.query(ProjectPlant).filter(
            ProjectPlant.plant_id == plant_id
        ).delete()

        # update batch notes if applicable
        if plant.batch_id:
            batch = session.query(PlantBatch).filter(
                PlantBatch.id == plant.batch_id
            ).first()
            if batch:
                timestamp = datetime.utcnow().strftime("%B %d, %Y")
                batch.notes = (
                    f"{batch.notes or ''}\n"
                    f"{timestamp}: 1 plant record deleted (correction)."
                ).strip()
                batch.quantity_sown = max(0, (batch.quantity_sown or 1) - 1)

        name = plant.name
        session.delete(plant)
        session.commit()
        return f"Plant record '{name}' permanently deleted."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to delete plant: {e}")
        return f"Failed to delete plant: {str(e)}"
    finally:
        session.close()


# ─── Delete tools ──────────────────────────────────────────────────────────────

@tool
def delete_batch(batch_id: str, delete_plants: bool = False) -> str:
    """
    IMPORTANT: Always confirm with the user before calling this tool.
    Describe what will be deleted and wait for explicit confirmation.

    Permanently delete a plant batch record. Use this only to correct
    mistakes — for example if a batch was created twice in error.
    
    delete_plants: if True, also permanently deletes all plants linked
    to this batch. If False (default), plants are kept but their
    batch_id is cleared — they become unlinked from any batch.
    This cannot be undone.
    """
    session = SessionLocal()
    try:
        batch = session.query(PlantBatch).filter(
            PlantBatch.id == batch_id
        ).first()
        if not batch:
            return f"No batch found with id {batch_id}."

        plants = session.query(Plant).filter(
            Plant.batch_id == batch_id
        ).all()

        if delete_plants:
            for plant in plants:
                session.query(ProjectPlant).filter(
                    ProjectPlant.plant_id == plant.id
                ).delete()
                session.delete(plant)
            plant_note = f"and {len(plants)} linked plants "
        else:
            # unlink plants from batch rather than deleting them
            for plant in plants:
                plant.batch_id = None
            plant_note = f"({len(plants)} plants unlinked from batch) "

        name = batch.name
        session.delete(batch)
        session.commit()
        return f"Batch '{name}' {plant_note}permanently deleted."
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed to delete batch: {e}")
        return f"Failed to delete batch: {str(e)}"
    finally:
        session.close()