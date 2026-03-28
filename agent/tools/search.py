# agent/tools/search.py
"""
Search tools for finding garden entities by name, location, or other attributes.
"""
from langchain.tools import tool
from db.database import SessionLocal
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
                Bed.user_id == 1,
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
                Container.user_id == 1,
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
                Plant.user_id == 1,
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
            for p in plants:
                # resolve location name from container or bed
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

                # find which projects this plant is in
                project_links = session.query(ProjectPlant).filter(
                    ProjectPlant.plant_id == p.id,
                    ProjectPlant.removed_at == None
                ).all()
                projects_text = (
                    f"{len(project_links)} project(s)"
                    if project_links else "no projects"
                )

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
            Bed.user_id == 1,
            Bed.location.ilike(loc)
        ).all()
        if beds:
            results.append(f"Beds in {location}:")
            for b in beds:
                results.append(f"  {b.to_summary()}")

        # containers
        containers = session.query(Container).filter(
            Container.user_id == 1,
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
                Plant.user_id == 1,
                Plant.status != "removed",
                (Plant.container_id.in_(container_ids)) |
                (Plant.bed_id.in_(bed_ids))
            ).all()
            if plants:
                results.append(f"\nPlants in {location}:")
                for p in plants:
                    # resolve location name
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
                    results.append(f"  {p.to_summary(location_name=location_name)}")

        if not results:
            return f"Nothing found in '{location}'."
        return "\n".join(results)

    except Exception as e:
        print(f"[DEBUG] Failed to list by location: {e}")
        return f"Failed to list by location: {str(e)}"
    finally:
        session.close()