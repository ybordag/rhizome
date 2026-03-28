# agent/tools/__init__.py
from agent.tools.profile import get_garden_profile, update_garden_profile
from agent.tools.projects import (
    create_project, update_project, get_project, list_projects, 
    assign_bed_to_project, assign_container_to_project, 
    unassign_bed_from_project, unassign_container_from_project,
    add_plant_to_project, remove_plant_from_project, delete_project)
from agent.tools.beds_containers import (
    list_beds, update_bed,
    list_containers, add_container, update_container, remove_container,
    delete_bed
)
from agent.tools.plants import (
    add_plant, update_plant, remove_plant, list_plants,
    batch_add_plant_type, batch_update_plants, batch_remove_plants, list_batches,
    delete_plant, delete_batch)
from agent.tools.search import search_garden, list_by_location

tools = [
    get_garden_profile,
    update_garden_profile,
    create_project,
    update_project,
    get_project,
    list_projects,
    assign_bed_to_project,
    assign_container_to_project,
    unassign_bed_from_project,
    unassign_container_from_project,
    add_plant_to_project,
    remove_plant_from_project,
    delete_project,
    list_beds,
    update_bed,
    list_containers,
    add_container,
    update_container,
    remove_container,
    delete_bed,
    add_plant,
    update_plant,
    remove_plant,
    list_plants,
    batch_add_plant_type,
    batch_update_plants,
    batch_remove_plants,
    list_batches,
    delete_plant,
    delete_batch,
    search_garden,
    list_by_location,
]
tools_by_name = {t.name: t for t in tools}