import pytest

from agent.tools.beds_containers import (
    add_container,
    delete_bed,
    list_beds,
    list_containers,
    remove_container,
    update_bed,
    update_container,
)
from db.models import Bed, Container
from tests.support.factories import make_bed, make_container


@pytest.mark.integration
def test_update_bed_persists_changes(db_session, patched_sessionlocal, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)

    result = update_bed.invoke(
        {
            "bed_id": bed.id,
            "soil_type": "sandy loam",
            "dimensions_sqft": 18.0,
            "notes": "Added compost.",
        }
    )

    db_session.expire_all()
    updated = db_session.query(Bed).filter(Bed.id == bed.id).one()
    assert result == f"Bed '{bed.name}' updated successfully."
    assert updated.soil_type == "sandy loam"
    assert updated.dimensions_sqft == 18.0
    assert updated.notes == "Added compost."


@pytest.mark.integration
def test_list_beds_returns_seeded_bed(db_session, patched_sessionlocal, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile, name="Front Bed")

    result = list_beds.invoke({})

    assert bed.name in result
    assert "[Bed]" in result


@pytest.mark.integration
def test_add_and_update_container_persist_changes(db_session, patched_sessionlocal, seed_garden_profile):
    create_result = add_container.invoke(
        {
            "name": "Patio Pot",
            "container_type": "pot",
            "size_gallons": 10.0,
            "location": "patio",
            "is_mobile": True,
            "notes": "Terracotta.",
        }
    )

    db_session.expire_all()
    container = db_session.query(Container).filter(Container.name == "Patio Pot").one()
    update_result = update_container.invoke(
        {
            "container_id": container.id,
            "location": "front",
            "notes": "Moved for more sun.",
        }
    )
    db_session.expire_all()
    updated = db_session.query(Container).filter(Container.id == container.id).one()

    assert "added successfully" in create_result
    assert update_result == "Container 'Patio Pot' updated successfully."
    assert updated.location == "front"
    assert updated.notes == "Moved for more sun."


@pytest.mark.integration
def test_list_containers_and_remove_container(db_session, patched_sessionlocal, seed_garden_profile):
    container = make_container(db_session, seed_garden_profile, name="Bag A")
    container_id = container.id

    list_result = list_containers.invoke({})
    remove_result = remove_container.invoke({"container_id": container_id, "reason": "torn"})

    db_session.expire_all()
    assert "Bag A" in list_result
    assert remove_result == "Container 'Bag A' removed from the garden. Reason: torn."
    assert db_session.query(Container).filter(Container.id == container_id).first() is None


@pytest.mark.integration
def test_delete_bed_removes_bed(db_session, patched_sessionlocal, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile, name="Temp Bed")
    bed_id = bed.id

    result = delete_bed.invoke({"bed_id": bed_id})

    db_session.expire_all()
    assert result == "Bed 'Temp Bed' permanently deleted."
    assert db_session.query(Bed).filter(Bed.id == bed_id).first() is None


@pytest.mark.integration
def test_bed_and_container_validation_errors(db_session, patched_sessionlocal, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)

    bad_bed = update_bed.invoke({"bed_id": bed.id, "dimensions_sqft": 0})
    bad_type = add_container.invoke(
        {
            "name": "Weird Bin",
            "container_type": "bucket",
            "size_gallons": 5.0,
            "location": "side yard",
        }
    )
    bad_size = add_container.invoke(
        {
            "name": "Flat Pot",
            "container_type": "pot",
            "size_gallons": 0,
            "location": "side yard",
        }
    )

    assert bad_bed == "dimensions_sqft must be greater than 0."
    assert "Invalid container_type 'bucket'" in bad_type
    assert bad_size == "size_gallons must be greater than 0."
