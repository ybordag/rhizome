import pytest

from agent.tools.search import list_by_location, search_garden
from tests.support.factories import (
    link_plant_to_project,
    make_bed,
    make_container,
    make_plant,
    make_project,
)


@pytest.mark.integration
def test_search_garden_finds_matching_entities(db_session, patched_sessionlocal, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile, name="Tomato Sprint")
    container = make_container(db_session, seed_garden_profile, name="Tomato Pot", location="front")
    plant = make_plant(db_session, seed_garden_profile, container=container, name="Tomato", variety="Sungold", status="established")
    link_plant_to_project(db_session, project, plant)

    result = search_garden.invoke({"query": "Tomato"})

    assert "Found" in result
    assert "Tomato Pot" in result
    assert "Tomato" in result
    assert "In: 1 project(s)" in result


@pytest.mark.integration
def test_list_by_location_groups_beds_containers_and_plants(db_session, patched_sessionlocal, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile, location="courtyard", name="Courtyard Bed")
    container = make_container(db_session, seed_garden_profile, location="courtyard", name="Courtyard Pot")
    make_plant(db_session, seed_garden_profile, bed=bed, name="Rosemary", status="established")
    make_plant(db_session, seed_garden_profile, container=container, name="Basil", status="established")

    result = list_by_location.invoke({"location": "courtyard"})

    assert "Beds in courtyard:" in result
    assert "Containers in courtyard:" in result
    assert "Plants in courtyard:" in result
    assert "Courtyard Bed" in result
    assert "Courtyard Pot" in result
    assert "Rosemary" in result
    assert "Basil" in result
