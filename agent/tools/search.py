# agent/tools/search.py
"""
Search tools for finding garden entities by name, location, or other attributes.
"""
from langchain.tools import tool
from sqlalchemy import func
from db.database import SessionLocal, current_user_id
from db.models import Plant, Bed, Container, ProjectPlant
from typing import Optional

# ─── Search tools ──────────────────────────────────────────────────────────────

@tool
def search_garden(
    query: str,
    entity_type: Optional[str] = None,
    location: Optional[str] = None,
    status: Optional[str] = None
) -> str:
    """
    Search for plants, beds, or containers in the garden by name or
    attributes. Use this when the user asks about a specific thing by
    name — for example 'how is my Sungold tomato doing?', 'what beds
    are in the courtyard?', 'show me all my growbags'.
    entity_type can be 'plant', 'bed', or 'container' to narrow the
    search — leave empty to search all types.
    location filters by area e.g. 'courtyard', 'front', 'backyard_slope'.
    status filters plants by status e.g. 'established', 'flowering'.
    """
    session = SessionLocal()
    try:
        results = []
        search = f"%{query}%"

        # search beds
        if entity_type in (None, "bed"):
            bed_query = session.query(Bed).filter(
                Bed.user_id == current_user_id.get(),
                Bed.name.ilike(search)
            )
            if location:
                bed_query = bed_query.filter(Bed.location.ilike(f"%{location}%"))
            beds = bed_query.all()
            for b in beds:
                results.append(b.to_summary())

        # search containers
        if entity_type in (None, "container"):
            container_query = session.query(Container).filter(
                Container.user_id == current_user_id.get(),
                Container.name.ilike(search)
            )
            if location:
                container_query = container_query.filter(
                    Container.location.ilike(f"%{location}%")
                )
            containers = container_query.all()
            for c in containers:
                results.append(c.to_summary())

        # search plants
        if entity_type in (None, "plant"):
            plant_query = session.query(Plant).filter(
                Plant.user_id == current_user_id.get(),
                Plant.status != "removed",
                (Plant.name.ilike(search) | Plant.variety.ilike(search))
            )
            if location:
                container_ids = [
                    c.id for c in session.query(Container).filter(
                        Container.location.ilike(f"%{location}%")
                    ).all()
                ]
                bed_ids = [
                    b.id for b in session.query(Bed).filter(
                        Bed.location.ilike(f"%{location}%")
                    ).all()
                ]
                plant_query = plant_query.filter(
                    (Plant.container_id.in_(container_ids)) |
                    (Plant.bed_id.in_(bed_ids))
                )
            if status:
                plant_query = plant_query.filter(Plant.status == status)

            plants = plant_query.all()
            if plants:
                plant_container_ids = {p.container_id for p in plants if p.container_id}
                plant_bed_ids = {p.bed_id for p in plants if p.bed_id}
                plant_ids = [p.id for p in plants]

                container_name_map = {
                    c.id: c.name
                    for c in session.query(Container)
                    .filter(Container.id.in_(plant_container_ids))
                    .all()
                } if plant_container_ids else {}

                bed_name_map = {
                    b.id: b.name
                    for b in session.query(Bed)
                    .filter(Bed.id.in_(plant_bed_ids))
                    .all()
                } if plant_bed_ids else {}

                project_link_counts = dict(
                    session.query(ProjectPlant.plant_id, func.count(ProjectPlant.id))
                    .filter(
                        ProjectPlant.plant_id.in_(plant_ids),
                        ProjectPlant.removed_at == None,
                    )
                    .group_by(ProjectPlant.plant_id)
                    .all()
                )

                for p in plants:
                    location_name = (
                        container_name_map.get(p.container_id) if p.container_id
                        else bed_name_map.get(p.bed_id)
                    )
                    count = project_link_counts.get(p.id, 0)
                    projects_text = f"{count} project(s)" if count else "no projects"
                    results.append(
                        p.to_summary(location_name=location_name)
                        + f"\n  In: {projects_text}"
                    )

        if not results:
            return f"No results found for '{query}'."
        return f"Found {len(results)} result(s):\n\n" + "\n\n".join(results)

    except Exception as e:
        print(f"[DEBUG] Failed to search garden: {e}")
        return f"Failed to search: {str(e)}"
    finally:
        session.close()


@tool
def list_by_location(location: str) -> str:
    """
    List all beds, containers, and plants in a specific area of the garden.
    Use this when the user asks about a specific area — for example 'what's
    in the courtyard?', 'show me everything on the slope', 'what do I have
    out front?'. Valid locations include: 'front', 'courtyard',
    'backyard_slope'.
    """
    session = SessionLocal()
    try:
        loc = f"%{location}%"
        results = []

        # beds
        beds = session.query(Bed).filter(
            Bed.user_id == current_user_id.get(),
            Bed.location.ilike(loc)
        ).all()
        if beds:
            results.append(f"Beds in {location}:")
            for b in beds:
                results.append(f"  {b.to_summary()}")

        # containers
        containers = session.query(Container).filter(
            Container.user_id == current_user_id.get(),
            Container.location.ilike(loc)
        ).all()
        if containers:
            results.append(f"\nContainers in {location}:")
            for c in containers:
                results.append(f"  {c.to_summary()}")

        # plants via their container or bed location
        container_ids = [c.id for c in containers]
        bed_ids = [b.id for b in beds]

        if container_ids or bed_ids:
            plants = session.query(Plant).filter(
                Plant.user_id == current_user_id.get(),
                Plant.status != "removed",
                (Plant.container_id.in_(container_ids)) |
                (Plant.bed_id.in_(bed_ids))
            ).all()
            if plants:
                container_name_map = {c.id: c.name for c in containers}
                bed_name_map = {b.id: b.name for b in beds}
                results.append(f"\nPlants in {location}:")
                for p in plants:
                    location_name = (
                        container_name_map.get(p.container_id) if p.container_id
                        else bed_name_map.get(p.bed_id)
                    )
                    results.append(f"  {p.to_summary(location_name=location_name)}")

        if not results:
            return f"Nothing found in '{location}'."
        return "\n".join(results)

    except Exception as e:
        print(f"[DEBUG] Failed to list by location: {e}")
        return f"Failed to list by location: {str(e)}"
    finally:
        session.close()