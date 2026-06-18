"""
Tests for assign_beds_to_project and assign_containers_to_project.

Covers: happy path, partial success, all-skipped, conflict detection,
already-assigned deduplication, unknown IDs, empty input, activity logging.
"""
from __future__ import annotations

import pytest

from agent.tools.projects import assign_beds_to_project, assign_containers_to_project
from db.models import ActivityEvent, ProjectBed, ProjectContainer
from tests.support.factories import (
    link_bed_to_project,
    link_container_to_project,
    make_bed,
    make_container,
    make_profile,
    make_project,
)


# ─── assign_beds_to_project ───────────────────────────────────────────────────

@pytest.mark.integration
def test_assign_beds_assigns_all_valid(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    bed1 = make_bed(db_session, profile, name="Bed A")
    bed2 = make_bed(db_session, profile, name="Bed B")

    result = assign_beds_to_project.invoke({
        "project_id": project.id,
        "bed_ids": [bed1.id, bed2.id],
    })

    assert "Assigned 2 bed(s)" in result
    assert "Bed A" in result
    assert "Bed B" in result
    assert db_session.query(ProjectBed).filter(ProjectBed.project_id == project.id).count() == 2


@pytest.mark.integration
def test_assign_beds_skips_already_assigned(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    bed = make_bed(db_session, profile, name="Already Here")
    link_bed_to_project(db_session, project, bed)

    result = assign_beds_to_project.invoke({
        "project_id": project.id,
        "bed_ids": [bed.id],
    })

    assert "Assigned 0 bed(s)" in result
    assert "already assigned" in result
    assert db_session.query(ProjectBed).filter(ProjectBed.project_id == project.id).count() == 1


@pytest.mark.integration
def test_assign_beds_skips_conflict_with_other_active_project(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project_a = make_project(db_session, profile, name="Project A", status="active")
    project_b = make_project(db_session, profile, name="Project B")
    bed = make_bed(db_session, profile, name="Contested Bed")
    link_bed_to_project(db_session, project_a, bed)

    result = assign_beds_to_project.invoke({
        "project_id": project_b.id,
        "bed_ids": [bed.id],
    })

    assert "Assigned 0 bed(s)" in result
    assert "Project A" in result
    assert db_session.query(ProjectBed).filter(ProjectBed.project_id == project_b.id).count() == 0


@pytest.mark.integration
def test_assign_beds_partial_success(db_session, patched_sessionlocal):
    """One bed is free, one is conflicted — free one should still be assigned."""
    profile = make_profile(db_session)
    project_a = make_project(db_session, profile, name="Project A", status="active")
    project_b = make_project(db_session, profile, name="Project B")
    free_bed = make_bed(db_session, profile, name="Free Bed")
    contested_bed = make_bed(db_session, profile, name="Contested Bed")
    link_bed_to_project(db_session, project_a, contested_bed)

    result = assign_beds_to_project.invoke({
        "project_id": project_b.id,
        "bed_ids": [free_bed.id, contested_bed.id],
    })

    assert "Assigned 1 bed(s)" in result
    assert "Free Bed" in result
    assert "Contested Bed" in result
    assigned = db_session.query(ProjectBed).filter(ProjectBed.project_id == project_b.id).all()
    assert len(assigned) == 1
    assert assigned[0].bed_id == free_bed.id


@pytest.mark.integration
def test_assign_beds_skips_unknown_id(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)

    result = assign_beds_to_project.invoke({
        "project_id": project.id,
        "bed_ids": ["nonexistent-bed-id"],
    })

    assert "Assigned 0 bed(s)" in result
    assert "not found" in result


@pytest.mark.integration
def test_assign_beds_empty_list(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)

    result = assign_beds_to_project.invoke({
        "project_id": project.id,
        "bed_ids": [],
    })

    assert "No bed IDs provided" in result


@pytest.mark.integration
def test_assign_beds_project_not_found(db_session, patched_sessionlocal):
    result = assign_beds_to_project.invoke({
        "project_id": "nonexistent-project",
        "bed_ids": ["some-bed"],
    })
    assert "No project found" in result


@pytest.mark.integration
def test_assign_beds_records_activity_events(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    bed1 = make_bed(db_session, profile, name="Bed A")
    bed2 = make_bed(db_session, profile, name="Bed B")

    assign_beds_to_project.invoke({
        "project_id": project.id,
        "bed_ids": [bed1.id, bed2.id],
    })

    events = (
        db_session.query(ActivityEvent)
        .filter(ActivityEvent.event_type == "project_bed_assigned")
        .all()
    )
    assert len(events) == 2


@pytest.mark.integration
def test_assign_beds_no_duplicate_db_rows_on_repeat_call(db_session, patched_sessionlocal):
    """Calling bulk assign twice with the same IDs should leave exactly one row per bed."""
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    bed = make_bed(db_session, profile, name="Bed A")

    assign_beds_to_project.invoke({"project_id": project.id, "bed_ids": [bed.id]})
    assign_beds_to_project.invoke({"project_id": project.id, "bed_ids": [bed.id]})

    assert db_session.query(ProjectBed).filter(ProjectBed.project_id == project.id).count() == 1


# ─── assign_containers_to_project ─────────────────────────────────────────────

@pytest.mark.integration
def test_assign_containers_assigns_all_valid(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    c1 = make_container(db_session, profile, name="Growbag 1")
    c2 = make_container(db_session, profile, name="Growbag 2")

    result = assign_containers_to_project.invoke({
        "project_id": project.id,
        "container_ids": [c1.id, c2.id],
    })

    assert "Assigned 2 container(s)" in result
    assert "Growbag 1" in result
    assert "Growbag 2" in result
    assert db_session.query(ProjectContainer).filter(ProjectContainer.project_id == project.id).count() == 2


@pytest.mark.integration
def test_assign_containers_skips_already_assigned(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    container = make_container(db_session, profile, name="Already Here")
    link_container_to_project(db_session, project, container)

    result = assign_containers_to_project.invoke({
        "project_id": project.id,
        "container_ids": [container.id],
    })

    assert "Assigned 0 container(s)" in result
    assert "already assigned" in result
    assert db_session.query(ProjectContainer).filter(ProjectContainer.project_id == project.id).count() == 1


@pytest.mark.integration
def test_assign_containers_skips_conflict_with_other_active_project(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project_a = make_project(db_session, profile, name="Project A", status="active")
    project_b = make_project(db_session, profile, name="Project B")
    container = make_container(db_session, profile, name="Contested Growbag")
    link_container_to_project(db_session, project_a, container)

    result = assign_containers_to_project.invoke({
        "project_id": project_b.id,
        "container_ids": [container.id],
    })

    assert "Assigned 0 container(s)" in result
    assert "Project A" in result
    assert db_session.query(ProjectContainer).filter(ProjectContainer.project_id == project_b.id).count() == 0


@pytest.mark.integration
def test_assign_containers_partial_success(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project_a = make_project(db_session, profile, name="Project A", status="active")
    project_b = make_project(db_session, profile, name="Project B")
    free = make_container(db_session, profile, name="Free Pot")
    contested = make_container(db_session, profile, name="Contested Pot")
    link_container_to_project(db_session, project_a, contested)

    result = assign_containers_to_project.invoke({
        "project_id": project_b.id,
        "container_ids": [free.id, contested.id],
    })

    assert "Assigned 1 container(s)" in result
    assigned = db_session.query(ProjectContainer).filter(ProjectContainer.project_id == project_b.id).all()
    assert len(assigned) == 1
    assert assigned[0].container_id == free.id


@pytest.mark.integration
def test_assign_containers_skips_unknown_id(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)

    result = assign_containers_to_project.invoke({
        "project_id": project.id,
        "container_ids": ["nonexistent-container-id"],
    })

    assert "Assigned 0 container(s)" in result
    assert "not found" in result


@pytest.mark.integration
def test_assign_containers_empty_list(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)

    result = assign_containers_to_project.invoke({
        "project_id": project.id,
        "container_ids": [],
    })

    assert "No container IDs provided" in result


@pytest.mark.integration
def test_assign_containers_project_not_found(db_session, patched_sessionlocal):
    result = assign_containers_to_project.invoke({
        "project_id": "nonexistent-project",
        "container_ids": ["some-container"],
    })
    assert "No project found" in result


@pytest.mark.integration
def test_assign_containers_records_activity_events(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    c1 = make_container(db_session, profile, name="Pot 1")
    c2 = make_container(db_session, profile, name="Pot 2")

    assign_containers_to_project.invoke({
        "project_id": project.id,
        "container_ids": [c1.id, c2.id],
    })

    events = (
        db_session.query(ActivityEvent)
        .filter(ActivityEvent.event_type == "project_container_assigned")
        .all()
    )
    assert len(events) == 2


@pytest.mark.integration
def test_assign_containers_no_duplicate_db_rows_on_repeat_call(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    container = make_container(db_session, profile, name="Pot A")

    assign_containers_to_project.invoke({"project_id": project.id, "container_ids": [container.id]})
    assign_containers_to_project.invoke({"project_id": project.id, "container_ids": [container.id]})

    assert db_session.query(ProjectContainer).filter(ProjectContainer.project_id == project.id).count() == 1


# ─── Completed-project conflict exemption ─────────────────────────────────────

@pytest.mark.integration
def test_assign_beds_does_not_conflict_with_completed_project(db_session, patched_sessionlocal):
    """A bed assigned to a completed/paused project should not block reassignment."""
    profile = make_profile(db_session)
    old_project = make_project(db_session, profile, name="Old Project", status="complete")
    new_project = make_project(db_session, profile, name="New Project")
    bed = make_bed(db_session, profile, name="Reused Bed")
    link_bed_to_project(db_session, old_project, bed)

    result = assign_beds_to_project.invoke({
        "project_id": new_project.id,
        "bed_ids": [bed.id],
    })

    assert "Assigned 1 bed(s)" in result


@pytest.mark.integration
def test_assign_containers_does_not_conflict_with_completed_project(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    old_project = make_project(db_session, profile, name="Old Project", status="complete")
    new_project = make_project(db_session, profile, name="New Project")
    container = make_container(db_session, profile, name="Reused Pot")
    link_container_to_project(db_session, old_project, container)

    result = assign_containers_to_project.invoke({
        "project_id": new_project.id,
        "container_ids": [container.id],
    })

    assert "Assigned 1 container(s)" in result
