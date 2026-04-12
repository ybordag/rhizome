from datetime import datetime, timedelta

import pytest

from agent.tools.activity import (
    get_batch_activity,
    get_bed_activity,
    get_container_activity,
    get_plant_activity,
    get_project_activity,
    list_recent_activity,
)
from agent.tools.beds_containers import add_container, delete_bed, remove_container, update_bed, update_container
from agent.tools.plants import (
    add_plant,
    batch_add_plant_type,
    batch_remove_plants,
    batch_update_plants,
    delete_batch,
    delete_plant,
    remove_plant,
    update_plant,
)
from agent.tools.projects import (
    add_plant_to_project,
    assign_bed_to_project,
    assign_container_to_project,
    create_project,
    delete_project,
    remove_plant_from_project,
    unassign_bed_from_project,
    unassign_container_from_project,
    update_project,
)
from db.models import ActivityEvent, ActivitySubject
from tests.support.factories import make_batch, make_bed, make_container, make_plant, make_project


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
def test_project_activity_event_type_filtering_returns_only_matching_events(
    db_session,
    patched_sessionlocal,
    seed_garden_profile,
):
    project = make_project(db_session, seed_garden_profile)
    bed = make_bed(db_session, seed_garden_profile)
    container = make_container(db_session, seed_garden_profile)

    assign_bed_to_project.invoke({"project_id": project.id, "bed_id": bed.id})
    assign_container_to_project.invoke({"project_id": project.id, "container_id": container.id})

    filtered = get_project_activity.invoke(
        {"project_id": project.id, "event_type": "project_bed_assigned"}
    )

    assert "project_bed_assigned" in filtered
    assert "project_container_assigned" not in filtered


@pytest.mark.integration
def test_activity_feeds_are_newest_first(db_session, patched_sessionlocal, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    older = ActivityEvent(
        actor_type="agent",
        actor_label="rhizome_tool",
        event_type="project_updated",
        category="project",
        summary="Older project update.",
        project_id=project.id,
        created_at=datetime.utcnow() - timedelta(days=2),
        event_metadata={},
    )
    newer = ActivityEvent(
        actor_type="agent",
        actor_label="rhizome_tool",
        event_type="project_status_changed",
        category="project",
        summary="Newer project update.",
        project_id=project.id,
        created_at=datetime.utcnow() - timedelta(days=1),
        event_metadata={},
    )
    db_session.add_all([older, newer])
    db_session.flush()
    db_session.add_all(
        [
            ActivitySubject(event_id=older.id, subject_type="project", subject_id=project.id, role="primary"),
            ActivitySubject(event_id=newer.id, subject_type="project", subject_id=project.id, role="primary"),
        ]
    )
    db_session.commit()

    project_history = get_project_activity.invoke({"project_id": project.id})
    recent_activity = list_recent_activity.invoke({"project_id": project.id, "limit": 10})

    assert project_history.index("Newer project update.") < project_history.index("Older project update.")
    assert recent_activity.index("Newer project update.") < recent_activity.index("Older project update.")


@pytest.mark.integration
def test_unassign_and_delete_tools_write_expected_activity_events(
    db_session,
    patched_sessionlocal,
    seed_garden_profile,
):
    project = make_project(db_session, seed_garden_profile)
    bed = make_bed(db_session, seed_garden_profile)
    container = make_container(db_session, seed_garden_profile)
    plant = make_plant(db_session, seed_garden_profile, name="Cleanup Tomato", status="seedling")
    batch = make_batch(db_session, seed_garden_profile, project=project)

    assign_bed_to_project.invoke({"project_id": project.id, "bed_id": bed.id})
    assign_container_to_project.invoke({"project_id": project.id, "container_id": container.id})
    add_plant_to_project.invoke({"project_id": project.id, "plant_id": plant.id})

    unassign_bed_from_project.invoke({"project_id": project.id, "bed_id": bed.id})
    unassign_container_from_project.invoke({"project_id": project.id, "container_id": container.id})
    remove_plant_from_project.invoke({"project_id": project.id, "plant_id": plant.id, "reason": "season done"})
    delete_project.invoke({"project_id": project.id})
    remove_container.invoke({"container_id": container.id, "reason": "worn out"})
    delete_bed.invoke({"bed_id": bed.id})
    delete_plant.invoke({"plant_id": plant.id})
    delete_batch.invoke({"batch_id": batch.id})

    event_types = {event.event_type for event in db_session.query(ActivityEvent).all()}

    assert "project_bed_unassigned" in event_types
    assert "project_container_unassigned" in event_types
    assert "project_plant_removed" in event_types
    assert "project_deleted" in event_types
    assert "container_removed" in event_types
    assert "bed_deleted" in event_types
    assert "plant_deleted" in event_types
    assert "batch_deleted" in event_types


@pytest.mark.integration
def test_batch_update_and_batch_remove_write_batch_update_events(
    db_session,
    patched_sessionlocal,
    seed_garden_profile,
):
    batch_add_plant_type.invoke(
        {
            "name": "Cosmos",
            "quantity": 3,
            "source": "seed",
            "sow_date": "2026-02-14",
            "batch_name": "Mutable Batch",
        }
    )

    update_result = batch_update_plants.invoke(
        {
            "name": "Cosmos",
            "new_status": "seedling",
            "quantity": 2,
            "update_reason": "potted up",
        }
    )
    remove_result = batch_remove_plants.invoke(
        {
            "name": "Cosmos",
            "reason": "culling weak seedlings",
            "quantity": 1,
        }
    )

    batch_update_events = db_session.query(ActivityEvent).filter(
        ActivityEvent.event_type == "batch_updated"
    ).all()

    assert "Updated 2 Cosmos" in update_result
    assert ("Marked 1 Cosmos" in remove_result) or ("Removed 1 Cosmos" in remove_result)
    assert len(batch_update_events) >= 2


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
