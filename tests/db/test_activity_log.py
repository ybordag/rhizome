from datetime import datetime

import pytest

from agent.activity_log import (
    compute_changed_fields,
    record_activity_event,
    record_create_event,
    snapshot_model,
)
from db.models import ActivityEvent, ActivitySubject
from tests.support.factories import make_batch, make_bed, make_container, make_plant, make_project


@pytest.mark.unit
def test_snapshot_model_serializes_supported_entities(db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    bed = make_bed(db_session, seed_garden_profile)
    container = make_container(db_session, seed_garden_profile)
    batch = make_batch(db_session, seed_garden_profile, project=project)
    plant = make_plant(db_session, seed_garden_profile, batch=batch, container=container)

    assert snapshot_model(project)["name"] == project.name
    assert snapshot_model(bed)["soil_type"] == bed.soil_type
    assert snapshot_model(container)["location"] == container.location
    assert snapshot_model(batch)["project_id"] == project.id
    assert snapshot_model(plant)["sow_date"] == plant.sow_date.isoformat()


@pytest.mark.unit
def test_compute_changed_fields_only_returns_modified_keys():
    before = {"name": "Tomato", "status": "seedling", "count": 1}
    after = {"name": "Tomato", "status": "established", "count": 1, "notes": "Moved"}

    assert compute_changed_fields(before, after) == ["notes", "status"]


@pytest.mark.integration
def test_activity_event_and_subjects_can_be_created(db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    bed = make_bed(db_session, seed_garden_profile)

    event = record_activity_event(
        db_session,
        actor_type="agent",
        actor_label="rhizome_tool",
        event_type="project_bed_assigned",
        category="project",
        summary="Assigned bed to project.",
        project_id=project.id,
        subjects=[
            {"subject_type": "project", "subject_id": project.id, "role": "primary"},
            {"subject_type": "bed", "subject_id": bed.id, "role": "affected"},
        ],
    )
    db_session.commit()

    stored = db_session.query(ActivityEvent).filter(ActivityEvent.id == event.id).one()
    subjects = db_session.query(ActivitySubject).filter(ActivitySubject.event_id == event.id).all()

    assert stored.event_type == "project_bed_assigned"
    assert len(subjects) == 2


@pytest.mark.integration
def test_record_create_event_captures_after_snapshot(db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile, name="History Project")

    event = record_create_event(
        db_session,
        event_type="project_created",
        category="project",
        summary="Created project.",
        obj=project,
        project_id=project.id,
        subjects=[{"subject_type": "project", "subject_id": project.id, "role": "primary"}],
    )
    db_session.commit()

    stored = db_session.query(ActivityEvent).filter(ActivityEvent.id == event.id).one()
    assert stored.event_metadata["after"]["name"] == "History Project"
