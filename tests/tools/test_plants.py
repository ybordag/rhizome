import pytest

from agent.tools.plants import (
    add_plant,
    batch_add_plant_type,
    batch_remove_plants,
    batch_update_plants,
    list_plants,
    remove_plant,
    update_plant,
)
from db.models import Plant, PlantBatch, ProjectPlant
from tests.support.factories import link_plant_to_project, make_batch, make_bed, make_container, make_plant, make_project


@pytest.mark.integration
def test_add_plant_persists_valid_record(db_session, patched_sessionlocal, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)

    result = add_plant.invoke(
        {
            "name": "Basil",
            "variety": "Genovese",
            "quantity": 2,
            "source": "seed",
            "bed_id": bed.id,
            "status": "seedling",
            "sow_date": "2026-02-10",
            "notes": "Direct sow trial.",
        }
    )

    db_session.expire_all()
    plant = db_session.query(Plant).filter(Plant.name == "Basil").one()

    assert "Added 2x Basil Genovese" in result
    assert plant.quantity == 2
    assert plant.status == "seedling"
    assert plant.bed_id == bed.id


@pytest.mark.integration
def test_update_plant_mutates_status_dates_and_notes(db_session, patched_sessionlocal, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile)

    result = update_plant.invoke(
        {
            "plant_id": plant.id,
            "status": "producing",
            "is_flowering": True,
            "is_fruiting": True,
            "last_fertilized_at": "2026-03-15",
            "notes": "Set fruit this week.",
        }
    )

    db_session.expire_all()
    updated = db_session.query(Plant).filter(Plant.id == plant.id).one()
    assert result == f"Plant '{plant.name}' updated successfully."
    assert updated.status == "producing"
    assert updated.is_flowering is True
    assert updated.is_fruiting is True
    assert updated.last_fertilized_at.date().isoformat() == "2026-03-15"
    assert updated.notes == "Set fruit this week."


@pytest.mark.integration
def test_list_plants_filters_by_status_and_location(db_session, patched_sessionlocal, seed_garden_profile):
    container = make_container(db_session, seed_garden_profile, name="Front Bag")
    make_plant(db_session, seed_garden_profile, container=container, name="Tomato", status="established")
    make_plant(db_session, seed_garden_profile, name="Pepper", status="seedling")

    result = list_plants.invoke({"status": "established"})

    assert "Tomato" in result
    assert "Front Bag" in result
    assert "Pepper" not in result


@pytest.mark.integration
def test_batch_add_creates_batch_plants_and_project_links(db_session, patched_sessionlocal, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)

    result = batch_add_plant_type.invoke(
        {
            "name": "Cosmos",
            "variety": "Apricotta",
            "quantity": 3,
            "project_id": project.id,
            "source": "seed",
            "status": "seedling",
            "sow_date": "2026-02-20",
            "batch_name": "Cosmos Trial",
        }
    )

    db_session.expire_all()
    batch = db_session.query(PlantBatch).filter(PlantBatch.name == "Cosmos Trial").one()
    plants = db_session.query(Plant).filter(Plant.batch_id == batch.id).all()

    assert "Created batch 'Cosmos Trial'" in result
    assert len(plants) == 3
    assert all(p.status == "seedling" for p in plants)
    assert db_session.query(ProjectPlant).filter(ProjectPlant.project_id == project.id).count() == 3


@pytest.mark.integration
def test_batch_update_only_updates_requested_quantity(db_session, patched_sessionlocal, seed_garden_profile):
    batch = make_batch(db_session, seed_garden_profile, plant_name="Lettuce", name="Lettuce Batch")
    make_plant(db_session, seed_garden_profile, batch=batch, name="Lettuce", status="seedling")
    make_plant(db_session, seed_garden_profile, batch=batch, name="Lettuce", status="seedling")
    make_plant(db_session, seed_garden_profile, batch=batch, name="Lettuce", status="seedling")

    result = batch_update_plants.invoke(
        {
            "name": "Lettuce",
            "current_status": "seedling",
            "quantity": 2,
            "new_status": "established",
            "update_reason": "potted up",
        }
    )

    db_session.expire_all()
    established = db_session.query(Plant).filter(Plant.name == "Lettuce", Plant.status == "established").count()
    seedling = db_session.query(Plant).filter(Plant.name == "Lettuce", Plant.status == "seedling").count()
    refreshed_batch = db_session.query(PlantBatch).filter(PlantBatch.id == batch.id).one()

    assert result == "Updated 2 Lettuce  plants — potted up."
    assert established == 2
    assert seedling == 1
    assert "Updated 2 plants" in refreshed_batch.notes


@pytest.mark.integration
def test_batch_remove_only_affects_requested_quantity(db_session, patched_sessionlocal, seed_garden_profile):
    batch = make_batch(db_session, seed_garden_profile, plant_name="Marigold", name="Marigold Batch")
    plants = [
        make_plant(db_session, seed_garden_profile, batch=batch, name="Marigold", status="seedling")
        for _ in range(3)
    ]
    project = make_project(db_session, seed_garden_profile)
    for plant in plants:
        link_plant_to_project(db_session, project, plant)

    result = batch_remove_plants.invoke(
        {
            "name": "Marigold",
            "reason": "culled extras",
            "current_status": "seedling",
            "quantity": 2,
        }
    )

    db_session.expire_all()
    removed = db_session.query(Plant).filter(Plant.name == "Marigold", Plant.status == "removed").count()
    active = db_session.query(Plant).filter(Plant.name == "Marigold", Plant.status != "removed").count()

    assert result == "Removed 2 Marigold  plants. Reason: culled extras"
    assert removed == 2
    assert active == 1


@pytest.mark.integration
def test_remove_plant_marks_removed_and_decouples_projects(db_session, patched_sessionlocal, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, name="Zinnia")
    project = make_project(db_session, seed_garden_profile)
    link = link_plant_to_project(db_session, project, plant)

    result = remove_plant.invoke({"plant_id": plant.id, "reason": "powdery mildew"})

    db_session.expire_all()
    updated = db_session.query(Plant).filter(Plant.id == plant.id).one()
    refreshed_link = db_session.query(ProjectPlant).filter(ProjectPlant.id == link.id).one()

    assert "marked as removed and decoupled from 1 project(s)." in result
    assert updated.status == "removed"
    assert "powdery mildew" in updated.notes
    assert refreshed_link.removed_at is not None


@pytest.mark.integration
def test_plant_validation_errors_are_clear(db_session, patched_sessionlocal, seed_garden_profile):
    container = make_container(db_session, seed_garden_profile)
    bed = make_bed(db_session, seed_garden_profile)
    plant = make_plant(db_session, seed_garden_profile)

    bad_status = add_plant.invoke({"name": "Bad", "status": "thriving"})
    bad_date = add_plant.invoke({"name": "Bad Date", "sow_date": "2026-99-99"})
    bad_quantity = batch_add_plant_type.invoke({"name": "Cosmos", "quantity": 0})
    dual_location = add_plant.invoke({"name": "Split", "container_id": container.id, "bed_id": bed.id})
    bad_update_date = update_plant.invoke({"plant_id": plant.id, "last_fertilized_at": "2026-14-01"})

    assert "Invalid status 'thriving'" in bad_status
    assert bad_date == "Invalid sow_date '2026-99-99'. Use ISO format YYYY-MM-DD."
    assert bad_quantity == "quantity must be at least 1."
    assert dual_location == "A plant cannot be assigned to both a bed and a container in the same tool call."
    assert bad_update_date == "Invalid last_fertilized_at '2026-14-01'. Use ISO format YYYY-MM-DD."
