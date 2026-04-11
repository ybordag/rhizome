import pytest

from agent.tools.projects import (
    add_plant_to_project,
    assign_bed_to_project,
    assign_container_to_project,
    create_project,
    delete_project,
    get_project,
    list_projects,
    remove_plant_from_project,
    update_project,
)
from db.models import GardeningProject, PlantBatch, ProjectBed, ProjectContainer, ProjectPlant
from tests.support.factories import (
    link_bed_to_project,
    link_container_to_project,
    link_plant_to_project,
    make_batch,
    make_bed,
    make_container,
    make_plant,
    make_project,
)


@pytest.mark.integration
def test_create_project_persists_valid_project(db_session, patched_sessionlocal, seed_garden_profile):
    result = create_project.invoke(
        {
            "name": "Cottage Border",
            "goal": "Fill the front border with flowers.",
            "tray_slots": 6,
            "budget_ceiling": 80.0,
            "notes": "Start from seed where possible.",
        }
    )

    db_session.expire_all()
    project = db_session.query(GardeningProject).filter(GardeningProject.name == "Cottage Border").one()

    assert "Project 'Cottage Border' created successfully" in result
    assert project.goal == "Fill the front border with flowers."
    assert project.status == "planning"


@pytest.mark.integration
def test_update_project_mutates_requested_fields_only(db_session, patched_sessionlocal, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)

    result = update_project.invoke(
        {
            "project_id": project.id,
            "status": "active",
            "tray_slots": 10,
            "notes": "Started seeds.",
        }
    )

    db_session.expire_all()
    updated = db_session.query(GardeningProject).filter(GardeningProject.id == project.id).one()
    assert result == f"Project '{project.name}' updated successfully."
    assert updated.status == "active"
    assert updated.tray_slots == 10
    assert updated.budget_ceiling == 120.0
    assert updated.notes == "Started seeds."


@pytest.mark.integration
def test_list_projects_filters_by_status(db_session, patched_sessionlocal, seed_garden_profile):
    make_project(db_session, seed_garden_profile, name="Active One", status="active")
    make_project(db_session, seed_garden_profile, name="Paused One", status="paused")

    result = list_projects.invoke({"status": "active"})

    assert "Active One" in result
    assert "Paused One" not in result


@pytest.mark.integration
def test_get_project_includes_linked_resources(db_session, patched_sessionlocal, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    bed = make_bed(db_session, seed_garden_profile)
    container = make_container(db_session, seed_garden_profile)
    batch = make_batch(db_session, seed_garden_profile, project=project)
    plant = make_plant(db_session, seed_garden_profile, batch=batch, container=container)
    link_bed_to_project(db_session, project, bed)
    link_container_to_project(db_session, project, container)
    link_plant_to_project(db_session, project, plant)

    result = get_project.invoke({"project_id": project.id})

    assert project.name in result
    assert "Beds:" in result and bed.name in result
    assert "Containers:" in result and container.name in result
    assert "Plants:" in result and plant.name in result
    assert "Batches:" in result and batch.name in result
    assert "Plant status breakdown:" in result


@pytest.mark.integration
def test_assignment_tools_create_join_rows(db_session, patched_sessionlocal, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    bed = make_bed(db_session, seed_garden_profile)
    container = make_container(db_session, seed_garden_profile)
    plant = make_plant(db_session, seed_garden_profile, bed=bed)

    bed_result = assign_bed_to_project.invoke({"project_id": project.id, "bed_id": bed.id})
    container_result = assign_container_to_project.invoke({"project_id": project.id, "container_id": container.id})
    plant_result = add_plant_to_project.invoke({"project_id": project.id, "plant_id": plant.id, "notes": "Key plant"})

    db_session.expire_all()
    assert bed_result == f"Bed '{bed.name}' assigned to project '{project.name}'."
    assert container_result == f"Container '{container.name}' assigned to project '{project.name}'."
    assert plant_result == f"'{plant.name}' added to project '{project.name}'."
    assert db_session.query(ProjectBed).filter(ProjectBed.project_id == project.id, ProjectBed.bed_id == bed.id).one()
    assert db_session.query(ProjectContainer).filter(ProjectContainer.project_id == project.id, ProjectContainer.container_id == container.id).one()
    assert db_session.query(ProjectPlant).filter(ProjectPlant.project_id == project.id, ProjectPlant.plant_id == plant.id).one()


@pytest.mark.integration
def test_remove_plant_from_project_closes_link(db_session, patched_sessionlocal, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    plant = make_plant(db_session, seed_garden_profile)
    link = link_plant_to_project(db_session, project, plant)

    result = remove_plant_from_project.invoke({"project_id": project.id, "plant_id": plant.id, "reason": "done for season"})

    db_session.expire_all()
    refreshed = db_session.query(ProjectPlant).filter(ProjectPlant.id == link.id).one()
    assert result == "Plant decoupled from project. It remains in your garden."
    assert refreshed.removed_at is not None
    assert "done for season" in refreshed.notes


@pytest.mark.integration
def test_delete_project_removes_project_and_preserves_batches(db_session, patched_sessionlocal, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    bed = make_bed(db_session, seed_garden_profile)
    container = make_container(db_session, seed_garden_profile)
    batch = make_batch(db_session, seed_garden_profile, project=project)
    plant = make_plant(db_session, seed_garden_profile, batch=batch)
    link_bed_to_project(db_session, project, bed)
    link_container_to_project(db_session, project, container)
    link_plant_to_project(db_session, project, plant)
    project_name = project.name
    project_id = project.id

    result = delete_project.invoke({"project_id": project_id})

    db_session.expire_all()
    assert f"Project '{project_name}' permanently deleted." in result
    assert db_session.query(GardeningProject).filter(GardeningProject.id == project_id).first() is None
    assert db_session.query(ProjectPlant).filter(ProjectPlant.project_id == project_id).count() == 0
    assert db_session.query(ProjectBed).filter(ProjectBed.project_id == project_id).count() == 0
    assert db_session.query(ProjectContainer).filter(ProjectContainer.project_id == project_id).count() == 0
    assert db_session.query(PlantBatch).filter(PlantBatch.id == batch.id).one().project_id is None


@pytest.mark.integration
def test_project_validation_errors_return_clear_messages(db_session, patched_sessionlocal, seed_garden_profile):
    negative = create_project.invoke(
        {
            "name": "Bad Project",
            "goal": "Bad numbers.",
            "tray_slots": -1,
            "budget_ceiling": 10.0,
        }
    )
    project = make_project(db_session, seed_garden_profile)
    invalid_status = update_project.invoke({"project_id": project.id, "status": "donezo"})

    assert negative == "tray_slots must be 0 or greater."
    assert "Invalid status 'donezo'" in invalid_status
