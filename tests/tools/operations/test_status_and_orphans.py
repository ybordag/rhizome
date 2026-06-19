"""
Tests for:
- Invalid status transition guards on complete_task, skip_task, defer_task, start_task
- Orphaned records after delete_project, delete_bed, remove_container
"""
from __future__ import annotations

import pytest

from agent.tools.garden.beds_containers import delete_bed, remove_container
from agent.tools.projects.projects import delete_project
from agent.tools.projects.tracker import (
    complete_task,
    defer_task,
    skip_task,
    start_task,
)
from db.models import (
    GardeningProject,
    Plant,
    PlantBatch,
    ProjectBed,
    ProjectContainer,
    ProjectPlant,
    Task,
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
    make_project_execution_spec,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_generation_run,
)
from tests.tools.projects.test_task_tracker_tools import _accept_plan
from agent.tools.projects.tracker import generate_project_tasks


# ─── Status transition guards ─────────────────────────────────────────────────

def _setup(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    return project, revision, run


# complete_task guards

@pytest.mark.integration
def test_complete_task_rejects_already_done(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.done", status="done")

    result = complete_task.invoke({"task_id": task.id})
    assert "cannot be completed" in result
    assert "done" in result


@pytest.mark.integration
def test_complete_task_rejects_skipped(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.skip", status="skipped")

    result = complete_task.invoke({"task_id": task.id})
    assert "cannot be completed" in result


@pytest.mark.integration
def test_complete_task_rejects_superseded(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.sup", status="superseded")

    result = complete_task.invoke({"task_id": task.id})
    assert "cannot be completed" in result


@pytest.mark.integration
def test_complete_task_accepts_pending(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.pend", status="pending")

    result = complete_task.invoke({"task_id": task.id})
    assert "Completed task" in result


@pytest.mark.integration
def test_complete_task_accepts_deferred(db_session, patched_sessionlocal):
    """Completing a deferred task is valid — user decided to do it anyway."""
    project, revision, run = _setup(db_session)
    from datetime import date
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.defd", status="deferred",
                     deferred_until=None)

    result = complete_task.invoke({"task_id": task.id})
    assert "Completed task" in result


# skip_task guards

@pytest.mark.integration
def test_skip_task_rejects_done(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.skip_done", status="done")

    result = skip_task.invoke({"task_id": task.id, "reason": "already done"})
    assert "cannot be skipped" in result


@pytest.mark.integration
def test_skip_task_rejects_superseded(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.skip_sup", status="superseded")

    result = skip_task.invoke({"task_id": task.id, "reason": "superseded"})
    assert "cannot be skipped" in result


@pytest.mark.integration
def test_skip_task_accepts_pending(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.skip_ok", status="pending")

    result = skip_task.invoke({"task_id": task.id, "reason": "not needed this season"})
    assert "Skipped task" in result


@pytest.mark.integration
def test_skip_task_accepts_blocked(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.skip_blk", status="blocked")

    result = skip_task.invoke({"task_id": task.id, "reason": "skipping blocked task"})
    assert "Skipped task" in result


# defer_task guards

@pytest.mark.integration
def test_defer_task_rejects_done(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.def_done", status="done")

    result = defer_task.invoke({"task_id": task.id, "deferred_until": "2026-06-01"})
    assert "cannot be deferred" in result


@pytest.mark.integration
def test_defer_task_rejects_superseded(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.def_sup", status="superseded")

    result = defer_task.invoke({"task_id": task.id, "deferred_until": "2026-06-01"})
    assert "cannot be deferred" in result


@pytest.mark.integration
def test_defer_task_accepts_pending(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.def_ok", status="pending")

    result = defer_task.invoke({"task_id": task.id, "deferred_until": "2026-06-01"})
    assert "Deferred task" in result


# start_task existing guards still work

@pytest.mark.integration
def test_start_task_rejects_done(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.start_done", status="done")

    result = start_task.invoke({"task_id": task.id})
    assert "cannot be started" in result


@pytest.mark.integration
def test_start_task_rejects_skipped(db_session, patched_sessionlocal):
    project, revision, run = _setup(db_session)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.start_skip", status="skipped")

    result = start_task.invoke({"task_id": task.id})
    assert "cannot be started" in result


# ─── Orphaned records after delete ────────────────────────────────────────────

@pytest.mark.integration
def test_delete_project_plants_remain_unlinked(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    plant = make_plant(db_session, profile, name="Tomato")
    link_plant_to_project(db_session, project, plant)

    result = delete_project.invoke({"project_id": project.id})

    assert "permanently deleted" in result
    # Plant survives
    assert db_session.query(Plant).filter(Plant.id == plant.id).first() is not None
    # ProjectPlant link is gone
    assert db_session.query(ProjectPlant).filter(ProjectPlant.project_id == project.id).count() == 0


@pytest.mark.integration
def test_delete_project_batches_survive_with_cleared_project_id(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    batch = make_batch(db_session, profile, project=project)

    delete_project.invoke({"project_id": project.id})

    db_session.expire_all()
    refreshed = db_session.query(PlantBatch).filter(PlantBatch.id == batch.id).first()
    assert refreshed is not None
    assert refreshed.project_id is None


@pytest.mark.integration
def test_delete_project_bed_and_container_links_removed(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    bed = make_bed(db_session, profile)
    container = make_container(db_session, profile)
    link_bed_to_project(db_session, project, bed)
    link_container_to_project(db_session, project, container)

    delete_project.invoke({"project_id": project.id})

    assert db_session.query(ProjectBed).filter(ProjectBed.project_id == project.id).count() == 0
    assert db_session.query(ProjectContainer).filter(ProjectContainer.project_id == project.id).count() == 0


@pytest.mark.integration
def test_delete_project_blocked_by_active_tasks(db_session, patched_sessionlocal):
    """delete_project must be blocked if non-superseded tasks exist."""
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="nursery")
    generate_project_tasks.invoke({"project_id": project.id})

    result = delete_project.invoke({"project_id": project.id})

    assert "Cannot delete" in result
    assert "active task" in result
    # Project still exists
    assert db_session.query(GardeningProject).filter(GardeningProject.id == project.id).first() is not None


@pytest.mark.integration
def test_delete_project_succeeds_when_all_tasks_superseded(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="nursery")
    generate_project_tasks.invoke({"project_id": project.id})

    # Supersede all tasks via regeneration
    from agent.tools.projects.tracker import regenerate_project_tasks
    regenerate_project_tasks.invoke({"project_id": project.id, "reason": "test cleanup"})

    # Now supersede the new tasks too (mark directly)
    db_session.query(Task).filter(
        Task.project_id == project.id,
        Task.status != "superseded",
    ).update({"status": "superseded"})
    db_session.commit()

    result = delete_project.invoke({"project_id": project.id})
    assert "permanently deleted" in result


@pytest.mark.integration
def test_remove_container_blocked_by_active_plants(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    container = make_container(db_session, profile, name="Occupied Pot")
    make_plant(db_session, profile, container=container, name="Tomato", status="established")

    result = remove_container.invoke({"container_id": container.id})

    assert "Cannot remove container" in result
    assert "Tomato" in result


@pytest.mark.integration
def test_remove_container_succeeds_when_plants_removed(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    container = make_container(db_session, profile, name="Empty Pot")
    make_plant(db_session, profile, container=container, name="Tomato", status="removed")

    result = remove_container.invoke({"container_id": container.id})

    assert "removed from the garden" in result


@pytest.mark.integration
def test_remove_container_cleans_up_project_links(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    container = make_container(db_session, profile, name="Growbag")
    link_container_to_project(db_session, project, container)

    result = remove_container.invoke({"container_id": container.id})

    assert "removed from the garden" in result
    assert db_session.query(ProjectContainer).filter(
        ProjectContainer.container_id == container.id
    ).count() == 0


@pytest.mark.integration
def test_delete_bed_blocked_by_active_plants(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    bed = make_bed(db_session, profile, name="Occupied Bed")
    make_plant(db_session, profile, bed=bed, name="Basil", status="established")

    result = delete_bed.invoke({"bed_id": bed.id})

    assert "Cannot delete bed" in result
    assert "Basil" in result


@pytest.mark.integration
def test_delete_bed_succeeds_when_plants_removed(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    bed = make_bed(db_session, profile, name="Clear Bed")
    make_plant(db_session, profile, bed=bed, name="Basil", status="removed")

    result = delete_bed.invoke({"bed_id": bed.id})

    assert "deleted" in result.lower()
