import pytest

from agent.tools.activity import (
    get_batch_activity,
    get_bed_activity,
    get_container_activity,
    get_plant_activity,
    get_project_activity,
    list_recent_activity,
)
from agent.tools.beds_containers import add_container, update_bed, update_container
from agent.tools.plants import add_plant, batch_add_plant_type, remove_plant, update_plant
from agent.tools.projects import (
    add_plant_to_project,
    assign_bed_to_project,
    create_project,
    update_project,
)
from db.models import ActivityEvent, ActivitySubject
from tests.support.factories import make_bed, make_container, make_plant, make_project


@pytest.mark.integration
def test_create_project_writes_project_created_event(db_session, patched_sessionlocal, seed_garden_profile):
    result = create_project.invoke(
        {
            "name": "History Cottage",
            "goal": "Track project events.",
            "tray_slots": 3,
            "budget_ceiling": 40.0,
        }
    )

    event = db_session.query(ActivityEvent).filter(ActivityEvent.event_type == "project_created").one()
    subject = db_session.query(ActivitySubject).filter(ActivitySubject.event_id == event.id).one()

    assert "created successfully" in result
    assert event.summary == "Created project 'History Cottage'."
    assert subject.subject_type == "project"


@pytest.mark.integration
def test_update_project_status_writes_status_event(db_session, patched_sessionlocal, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)

    update_project.invoke({"project_id": project.id, "status": "active"})

    event = db_session.query(ActivityEvent).filter(ActivityEvent.event_type == "project_status_changed").one()

    assert event.summary == f"Project '{project.name}' status changed from planning to active."
    assert event.event_metadata["changed_fields"] == ["status"]


@pytest.mark.integration
def test_container_create_and_move_write_events(db_session, patched_sessionlocal, seed_garden_profile):
    add_container.invoke(
        {
            "name": "History Pot",
            "container_type": "pot",
            "size_gallons": 7.0,
            "location": "patio",
        }
    )
    container = make_container(db_session, seed_garden_profile, name="Move Pot", location="patio")

    update_container.invoke({"container_id": container.id, "location": "front"})

    created = db_session.query(ActivityEvent).filter(ActivityEvent.event_type == "container_created").all()
    moved = db_session.query(ActivityEvent).filter(ActivityEvent.event_type == "container_moved").one()

    assert any(event.summary == "Created container 'History Pot'." for event in created)
    assert moved.summary == "Moved container 'Move Pot' from patio to front."


@pytest.mark.integration
def test_bed_and_plant_semantic_events_are_written(db_session, patched_sessionlocal, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    update_bed.invoke({"bed_id": bed.id, "soil_type": "amended loam"})

    add_plant.invoke(
        {
            "name": "Basil",
            "source": "seed",
            "sow_date": "2026-02-10",
        }
    )
    plant = make_plant(db_session, seed_garden_profile, name="Pepper")
    update_plant.invoke({"plant_id": plant.id, "last_fertilized_at": "2026-03-20"})
    remove_plant.invoke({"plant_id": plant.id, "reason": "failed"})

    assert db_session.query(ActivityEvent).filter(ActivityEvent.event_type == "bed_updated").count() == 1
    assert db_session.query(ActivityEvent).filter(ActivityEvent.event_type == "plant_sown").count() >= 1
    assert db_session.query(ActivityEvent).filter(ActivityEvent.event_type == "plant_fertilized").count() >= 1
    assert db_session.query(ActivityEvent).filter(ActivityEvent.event_type == "plant_removed").count() >= 1


@pytest.mark.integration
def test_assignment_and_batch_events_are_queryable(db_session, patched_sessionlocal, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    bed = make_bed(db_session, seed_garden_profile)
    assign_bed_to_project.invoke({"project_id": project.id, "bed_id": bed.id})

    batch_add_plant_type.invoke(
        {
            "name": "Cosmos",
            "quantity": 2,
            "project_id": project.id,
            "source": "seed",
            "sow_date": "2026-02-14",
            "batch_name": "History Batch",
        }
    )

    batch_event = db_session.query(ActivityEvent).filter(ActivityEvent.event_type == "batch_created").one()

    project_history = get_project_activity.invoke({"project_id": project.id})
    bed_history = get_bed_activity.invoke({"bed_id": bed.id})
    batch_history = get_batch_activity.invoke(
        {
            "batch_id": batch_event.event_metadata["after"]["id"],
        }
    )

    assert "project_bed_assigned" in project_history
    assert "batch_created" in project_history
    assert "project_bed_assigned" in bed_history
    assert "batch_created" in batch_history


@pytest.mark.integration
def test_object_history_and_recent_activity_queries_work(db_session, patched_sessionlocal, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    container = make_container(db_session, seed_garden_profile)
    plant = make_plant(db_session, seed_garden_profile, container=container)
    add_plant_to_project.invoke({"project_id": project.id, "plant_id": plant.id})

    plant_history = get_plant_activity.invoke({"plant_id": plant.id})
    container_history = get_container_activity.invoke({"container_id": container.id})
    recent_activity = list_recent_activity.invoke({"project_id": project.id, "limit": 10})

    assert "Recent activity for plant" in plant_history
    assert "project_plant_added" in plant_history
    assert "Recent activity for container" in container_history
    assert "No activity found." not in recent_activity


@pytest.mark.integration
def test_failed_write_does_not_persist_activity_event(db_session, patched_sessionlocal, seed_garden_profile):
    result = create_project.invoke(
        {
            "name": "Bad Project",
            "goal": "Should fail.",
            "tray_slots": -1,
            "budget_ceiling": 25.0,
        }
    )

    assert result == "tray_slots must be 0 or greater."
    assert db_session.query(ActivityEvent).count() == 0
