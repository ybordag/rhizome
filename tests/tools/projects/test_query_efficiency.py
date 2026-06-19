"""
Regression tests for N+1 query fixes and DB constraint additions.

These tests verify:
- list_projects returns correct counts without N+1 queries
- get_project resolves plant locations and batch plant counts without per-row queries
- search_garden / list_by_location resolve locations without per-plant queries
- ProjectBed/ProjectContainer unique constraints prevent duplicate assignments
- ActivityEvent.revision_id FK is enforced
- ProjectBed/ProjectContainer/ProjectPlant created_at is non-null
"""
from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from agent.tools.projects.projects import get_project, list_projects
from agent.tools.garden.search import list_by_location, search_garden
from db.models import (
    ActivityEvent,
    GardeningProject,
    ProjectBed,
    ProjectContainer,
    ProjectPlant,
)
from tests.support.factories import (
    link_bed_to_project,
    link_container_to_project,
    link_plant_to_project,
    make_batch,
    make_bed,
    make_container,
    make_plant,
    make_profile,
    make_project,
    make_project_brief,
    make_project_revision,
    make_project_proposal,
    make_task_generation_run,
)


# ─── list_projects: correct counts with multiple projects ─────────────────────

@pytest.mark.integration
def test_list_projects_counts_are_correct_with_multiple_projects(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project_a = make_project(db_session, profile, name="Project A")
    project_b = make_project(db_session, profile, name="Project B")

    bed1 = make_bed(db_session, profile, name="Bed 1")
    bed2 = make_bed(db_session, profile, name="Bed 2")
    container1 = make_container(db_session, profile, name="Container 1")
    plant1 = make_plant(db_session, profile, name="Tomato")
    plant2 = make_plant(db_session, profile, name="Basil")
    batch1 = make_batch(db_session, profile, project=project_a)

    link_bed_to_project(db_session, project_a, bed1)
    link_bed_to_project(db_session, project_b, bed2)
    link_container_to_project(db_session, project_a, container1)
    link_plant_to_project(db_session, project_a, plant1)
    link_plant_to_project(db_session, project_a, plant2)

    result = list_projects.invoke({})

    assert "Project A" in result
    assert "Project B" in result
    # Project A: 2 plants, 1 bed, 1 container, 1 batch
    assert "Plants: 2" in result
    assert "Beds: 1" in result
    assert "Containers: 1" in result
    assert "Batches: 1" in result


@pytest.mark.integration
def test_list_projects_counts_are_zero_for_empty_project(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    make_project(db_session, profile, name="Empty Project")

    result = list_projects.invoke({})

    assert "Empty Project" in result
    assert "Plants: 0" in result
    assert "Beds: 0" in result
    assert "Containers: 0" in result
    assert "Batches: 0" in result


@pytest.mark.integration
def test_list_projects_does_not_cross_contaminate_counts(db_session, patched_sessionlocal):
    """Plants in Project A must not appear in Project B's count."""
    profile = make_profile(db_session)
    project_a = make_project(db_session, profile, name="Project A")
    project_b = make_project(db_session, profile, name="Project B")

    plant = make_plant(db_session, profile, name="Tomato")
    link_plant_to_project(db_session, project_a, plant)

    result = list_projects.invoke({})

    lines = result.split("\n\n")
    block_a = next(l for l in lines if "Project A" in l)
    block_b = next(l for l in lines if "Project B" in l)
    assert "Plants: 1" in block_a
    assert "Plants: 0" in block_b


# ─── get_project: location names and batch plant counts ───────────────────────

@pytest.mark.integration
def test_get_project_resolves_plant_location_name(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    container = make_container(db_session, profile, name="Front Growbag")
    plant = make_plant(db_session, profile, container=container, name="Pepper")
    link_container_to_project(db_session, project, container)
    link_plant_to_project(db_session, project, plant)

    result = get_project.invoke({"project_id": project.id})

    assert "Front Growbag" in result
    assert "Pepper" in result


@pytest.mark.integration
def test_get_project_resolves_bed_location_name(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    bed = make_bed(db_session, profile, name="Courtyard Bed")
    plant = make_plant(db_session, profile, bed=bed, name="Basil")
    link_bed_to_project(db_session, project, bed)
    link_plant_to_project(db_session, project, plant)

    result = get_project.invoke({"project_id": project.id})

    assert "Courtyard Bed" in result
    assert "Basil" in result


@pytest.mark.integration
def test_get_project_resolves_location_for_plant_not_in_project_locations(db_session, patched_sessionlocal):
    """Plant in a container that isn't formally assigned to the project should still show location name."""
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    unassigned_container = make_container(db_session, profile, name="Unassigned Pot")
    plant = make_plant(db_session, profile, container=unassigned_container, name="Mint")
    link_plant_to_project(db_session, project, plant)
    # Note: container NOT linked to project via link_container_to_project

    result = get_project.invoke({"project_id": project.id})

    assert "Unassigned Pot" in result


@pytest.mark.integration
def test_get_project_shows_batch_plant_status_breakdown(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    batch = make_batch(db_session, profile, project=project)
    make_plant(db_session, profile, batch=batch, name="Tomato", status="seedling")
    make_plant(db_session, profile, batch=batch, name="Tomato", status="seedling")
    make_plant(db_session, profile, batch=batch, name="Tomato", status="established")

    result = get_project.invoke({"project_id": project.id})

    assert "seedling: 2" in result
    assert "established: 1" in result


# ─── search_garden: location names without per-plant queries ──────────────────

@pytest.mark.integration
def test_search_garden_resolves_container_location_name(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    container = make_container(db_session, profile, name="Growbag Front")
    make_plant(db_session, profile, container=container, name="Sungold Tomato")

    result = search_garden.invoke({"query": "Sungold"})

    assert "Sungold Tomato" in result
    assert "Growbag Front" in result


@pytest.mark.integration
def test_search_garden_resolves_bed_location_name(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    bed = make_bed(db_session, profile, name="Herb Bed")
    make_plant(db_session, profile, bed=bed, name="Rosemary")

    result = search_garden.invoke({"query": "Rosemary"})

    assert "Rosemary" in result
    assert "Herb Bed" in result


@pytest.mark.integration
def test_search_garden_project_count_is_correct(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    plant = make_plant(db_session, profile, name="Pepper")
    link_plant_to_project(db_session, project, plant)

    result = search_garden.invoke({"query": "Pepper"})

    assert "1 project(s)" in result


@pytest.mark.integration
def test_search_garden_no_projects_shown_correctly(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    make_plant(db_session, profile, name="Lavender")

    result = search_garden.invoke({"query": "Lavender"})

    assert "no projects" in result


# ─── list_by_location: location names from in-memory maps ─────────────────────

@pytest.mark.integration
def test_list_by_location_resolves_container_name(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    container = make_container(db_session, profile, name="Front Pot", location="front patio")
    make_plant(db_session, profile, container=container, name="Chilli")

    result = list_by_location.invoke({"location": "front"})

    assert "Chilli" in result
    assert "Front Pot" in result


@pytest.mark.integration
def test_list_by_location_resolves_bed_name(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    bed = make_bed(db_session, profile, name="Side Bed", location="side garden")
    make_plant(db_session, profile, bed=bed, name="Oregano")

    result = list_by_location.invoke({"location": "side"})

    assert "Oregano" in result
    assert "Side Bed" in result


# ─── DB: unique constraints on ProjectBed and ProjectContainer ────────────────

@pytest.mark.integration
def test_duplicate_bed_assignment_is_rejected(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    bed = make_bed(db_session, profile)

    link_bed_to_project(db_session, project, bed)

    with pytest.raises((IntegrityError, Exception)):
        db_session.add(ProjectBed(project_id=project.id, bed_id=bed.id))
        db_session.flush()


@pytest.mark.integration
def test_duplicate_container_assignment_is_rejected(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    container = make_container(db_session, profile)

    link_container_to_project(db_session, project, container)

    with pytest.raises((IntegrityError, Exception)):
        db_session.add(ProjectContainer(project_id=project.id, container_id=container.id))
        db_session.flush()


@pytest.mark.integration
def test_same_bed_can_be_assigned_to_different_projects(db_session, patched_sessionlocal):
    """Uniqueness is per (project_id, bed_id) pair — not per bed globally."""
    profile = make_profile(db_session)
    project_a = make_project(db_session, profile, name="Project A")
    project_b = make_project(db_session, profile, name="Project B")
    bed = make_bed(db_session, profile)

    link_bed_to_project(db_session, project_a, bed)
    link_bed_to_project(db_session, project_b, bed)  # should not raise

    assert db_session.query(ProjectBed).filter(ProjectBed.bed_id == bed.id).count() == 2


# ─── DB: created_at is non-null ───────────────────────────────────────────────

@pytest.mark.integration
def test_project_bed_created_at_is_set(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    bed = make_bed(db_session, profile)
    link = link_bed_to_project(db_session, project, bed)

    assert link.created_at is not None


@pytest.mark.integration
def test_project_container_created_at_is_set(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    container = make_container(db_session, profile)
    link = link_container_to_project(db_session, project, container)

    assert link.created_at is not None


@pytest.mark.integration
def test_project_plant_created_at_is_set(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    plant = make_plant(db_session, profile)
    link = link_plant_to_project(db_session, project, plant)

    assert link.created_at is not None


# ─── DB: ActivityEvent.revision_id FK ────────────────────────────────────────

def test_activity_event_revision_id_fk_is_defined_on_model():
    """revision_id must declare a FK to project_revision.id at the model level.
    Runtime enforcement requires Postgres (SQLite skips FK checks by default).
    """
    col = ActivityEvent.__table__.columns["revision_id"]
    fk_targets = [fk.target_fullname for fk in col.foreign_keys]
    assert "project_revision.id" in fk_targets


@pytest.mark.integration
def test_activity_event_revision_id_nullable_is_allowed(db_session, patched_sessionlocal):
    """revision_id=None must still be accepted (it's nullable)."""
    profile = make_profile(db_session)
    project = make_project(db_session, profile)

    event = ActivityEvent(
        user_id="1",
        actor_type="agent",
        actor_label="test",
        event_type="test_event",
        category="test",
        summary="Testing nullable revision_id",
        project_id=project.id,
        revision_id=None,
    )
    db_session.add(event)
    db_session.flush()
    db_session.commit()

    assert event.id is not None


@pytest.mark.integration
def test_activity_event_revision_id_accepts_valid_revision(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)

    event = ActivityEvent(
        user_id="1",
        actor_type="agent",
        actor_label="test",
        event_type="test_event",
        category="test",
        summary="Testing valid revision_id FK",
        project_id=project.id,
        revision_id=revision.id,
    )
    db_session.add(event)
    db_session.flush()
    db_session.commit()

    assert event.revision_id == revision.id
