"""
Tests for Groups 2 and 3 endpoint additions:
  - #113: Task series create + delete
  - #121: Task dependency CRUD + Gantt include_dependencies
  - #122: Bulk task date update
  - #114: Calendar annotations CRUD
  - #124: Project expenses CRUD + summary
  - #125: Shopping list CRUD + purchase action
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from db.models import GardeningProject, TaskDependency
from tests.support.factories import (
    make_bed, make_profile, make_project, make_project_brief,
    make_project_proposal, make_project_revision,
    make_task, make_task_generation_run,
)

client = TestClient(app)
USER = "1"


def _uid():
    return str(uuid.uuid4())


def _base(db_session):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    return profile, project, revision, run


# ---------------------------------------------------------------------------
# #113 — Task series CRUD
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_create_task_series(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/tasks/series?user_id={USER}", json={
        "project_id": project.id,
        "title_template": "Weekly watering",
        "type": "maintenance",
        "cadence": "weekly",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Weekly watering"
    assert data["cadence"] == "weekly"
    assert data["active"] is True


@pytest.mark.integration
def test_delete_task_series(patched_sessionlocal, db_session, seed_garden_profile):
    profile, project, revision, run = _base(db_session)
    resp = client.post(f"/internal/data/tasks/series?user_id={USER}", json={
        "project_id": project.id,
        "title_template": "To delete",
        "type": "maintenance",
        "cadence": "weekly",
    })
    series_id = resp.json()["id"]

    resp = client.delete(f"/internal/data/tasks/series/{series_id}?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.integration
def test_delete_task_series_with_pending_tasks(patched_sessionlocal, db_session, seed_garden_profile):
    profile, project, revision, run = _base(db_session)
    # Create series
    resp = client.post(f"/internal/data/tasks/series?user_id={USER}", json={
        "project_id": project.id,
        "title_template": "Series with tasks",
        "type": "maintenance",
        "cadence": "daily",
    })
    series_id = resp.json()["id"]
    # Create a pending task linked to it
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="series.task", title="Series task", status="pending",
                     **{"series_id": series_id})

    resp = client.delete(
        f"/internal/data/tasks/series/{series_id}?user_id={USER}&delete_pending_tasks=true")
    assert resp.status_code == 200
    # Pending task should be gone
    from db.models import Task as TaskModel
    assert db_session.query(TaskModel).filter(TaskModel.id == task.id).first() is None


# ---------------------------------------------------------------------------
# #121 — Task dependencies
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_add_task_dependency(patched_sessionlocal, db_session, seed_garden_profile):
    profile, project, revision, run = _base(db_session)
    t1 = make_task(db_session, project=project, revision=revision, generation_run=run,
                   generator_key="dep.t1", title="Prepare soil")
    t2 = make_task(db_session, project=project, revision=revision, generation_run=run,
                   generator_key="dep.t2", title="Plant seeds")

    resp = client.post(f"/internal/data/tasks/{t2.id}/dependencies?user_id={USER}",
                       json={"blocking_task_id": t1.id})
    assert resp.status_code == 200
    assert resp.json()["blocking_task_id"] == t1.id


@pytest.mark.integration
def test_add_task_dependency_cycle_detected(patched_sessionlocal, db_session, seed_garden_profile):
    profile, project, revision, run = _base(db_session)
    t1 = make_task(db_session, project=project, revision=revision, generation_run=run,
                   generator_key="cycle.t1", title="A")
    t2 = make_task(db_session, project=project, revision=revision, generation_run=run,
                   generator_key="cycle.t2", title="B")
    # A → B
    client.post(f"/internal/data/tasks/{t2.id}/dependencies?user_id={USER}",
                json={"blocking_task_id": t1.id})
    # B → A would create A → B → A cycle
    resp = client.post(f"/internal/data/tasks/{t1.id}/dependencies?user_id={USER}",
                       json={"blocking_task_id": t2.id})
    assert resp.status_code == 400


@pytest.mark.integration
def test_delete_task_dependency(patched_sessionlocal, db_session, seed_garden_profile):
    profile, project, revision, run = _base(db_session)
    t1 = make_task(db_session, project=project, revision=revision, generation_run=run,
                   generator_key="del.t1", title="A")
    t2 = make_task(db_session, project=project, revision=revision, generation_run=run,
                   generator_key="del.t2", title="B")
    db_session.add(TaskDependency(blocking_task_id=t1.id, blocked_task_id=t2.id))
    db_session.commit()

    resp = client.delete(
        f"/internal/data/tasks/{t2.id}/dependencies/{t1.id}?user_id={USER}")
    assert resp.status_code == 200


@pytest.mark.integration
def test_project_tasks_include_dependencies(patched_sessionlocal, db_session, seed_garden_profile):
    profile, project, revision, run = _base(db_session)
    t1 = make_task(db_session, project=project, revision=revision, generation_run=run,
                   generator_key="gantt.t1", title="A")
    t2 = make_task(db_session, project=project, revision=revision, generation_run=run,
                   generator_key="gantt.t2", title="B")
    db_session.add(TaskDependency(blocking_task_id=t1.id, blocked_task_id=t2.id))
    db_session.commit()

    resp = client.get(
        f"/internal/data/projects/{project.id}/tasks?user_id={USER}&include_dependencies=true")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks" in data and "edges" in data
    assert len(data["edges"]) == 1
    assert data["edges"][0]["blocking_task_id"] == t1.id


# ---------------------------------------------------------------------------
# #122 — Bulk task date update
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_bulk_update_task_dates(patched_sessionlocal, db_session, seed_garden_profile):
    profile, project, revision, run = _base(db_session)
    t1 = make_task(db_session, project=project, revision=revision, generation_run=run,
                   generator_key="bulk.t1", title="Task 1")
    t2 = make_task(db_session, project=project, revision=revision, generation_run=run,
                   generator_key="bulk.t2", title="Task 2")

    resp = client.patch(
        f"/internal/data/projects/{project.id}/tasks/bulk?user_id={USER}",
        json={"updates": [
            {"task_id": t1.id, "scheduled_date": "2026-08-01"},
            {"task_id": t2.id, "deadline": "2026-08-15"},
        ]})
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 2


@pytest.mark.integration
def test_bulk_update_rejects_done_tasks(patched_sessionlocal, db_session, seed_garden_profile):
    profile, project, revision, run = _base(db_session)
    done = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="bulk.done", title="Done task", status="done")

    resp = client.patch(
        f"/internal/data/projects/{project.id}/tasks/bulk?user_id={USER}",
        json={"updates": [{"task_id": done.id, "scheduled_date": "2026-08-01"}]})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# #114 — Calendar annotations
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_create_and_list_calendar_annotation(patched_sessionlocal, db_session):
    resp = client.post(f"/internal/data/calendar/annotations?user_id={USER}", json={
        "date": "2026-07-15",
        "content": "Tomatoes ready to transplant",
        "category": "observation",
    })
    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-07-15"

    resp = client.get(
        f"/internal/data/calendar/annotations?user_id={USER}&since=2026-07-01&before=2026-07-31")
    assert resp.status_code == 200
    contents = [a["content"] for a in resp.json()]
    assert "Tomatoes ready to transplant" in contents


@pytest.mark.integration
def test_update_calendar_annotation(patched_sessionlocal, db_session):
    resp = client.post(f"/internal/data/calendar/annotations?user_id={USER}", json={
        "date": "2026-07-10",
        "content": "Original",
    })
    ann_id = resp.json()["id"]

    resp = client.patch(f"/internal/data/calendar/annotations/{ann_id}?user_id={USER}",
                        json={"content": "Updated"})
    assert resp.status_code == 200
    assert resp.json()["content"] == "Updated"


@pytest.mark.integration
def test_delete_calendar_annotation(patched_sessionlocal, db_session):
    resp = client.post(f"/internal/data/calendar/annotations?user_id={USER}", json={
        "date": "2026-07-05",
        "content": "To delete",
    })
    ann_id = resp.json()["id"]

    resp = client.delete(f"/internal/data/calendar/annotations/{ann_id}?user_id={USER}")
    assert resp.status_code == 200

    resp = client.get(
        f"/internal/data/calendar/annotations?user_id={USER}&since=2026-07-01&before=2026-07-31")
    assert all(a["id"] != ann_id for a in resp.json())


@pytest.mark.integration
def test_calendar_annotation_wrong_user_returns_404(patched_sessionlocal, db_session):
    resp = client.post(f"/internal/data/calendar/annotations?user_id={USER}", json={
        "date": "2026-07-20",
        "content": "Private note",
    })
    ann_id = resp.json()["id"]

    resp = client.delete(f"/internal/data/calendar/annotations/{ann_id}?user_id=other-user")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# #124 — Project expenses
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_create_and_list_project_expense(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/projects/{project.id}/expenses?user_id={USER}", json={
        "name": "Potting mix (3 bags)",
        "category": "material",
        "estimated_cost": 45.00,
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "Potting mix (3 bags)"

    resp = client.get(f"/internal/data/projects/{project.id}/expenses?user_id={USER}")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.integration
def test_expense_summary(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    client.post(f"/internal/data/projects/{project.id}/expenses?user_id={USER}", json={
        "name": "Seeds", "category": "plant", "estimated_cost": 20.0, "actual_cost": 18.0})
    client.post(f"/internal/data/projects/{project.id}/expenses?user_id={USER}", json={
        "name": "Soil", "category": "material", "estimated_cost": 30.0, "actual_cost": 28.0})

    resp = client.get(f"/internal/data/projects/{project.id}/expenses/summary?user_id={USER}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_estimated"] == 50.0
    assert data["total_actual"] == 46.0
    assert "plant" in data["by_category"]
    assert "material" in data["by_category"]


# ---------------------------------------------------------------------------
# #125 — Shopping list
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_create_and_list_shopping_item(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/shopping?user_id={USER}", json={
        "name": "Organic potting mix",
        "category": "amendment",
        "estimated_cost": 15.0,
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "Organic potting mix"

    resp = client.get(f"/internal/data/shopping?user_id={USER}")
    assert resp.status_code == 200
    names = [i["name"] for i in resp.json()]
    assert "Organic potting mix" in names


@pytest.mark.integration
def test_shopping_item_status_filter(patched_sessionlocal, db_session, seed_garden_profile):
    client.post(f"/internal/data/shopping?user_id={USER}", json={
        "name": "Needed item", "category": "tool"})
    client.post(f"/internal/data/shopping?user_id={USER}", json={
        "name": "Ordered item", "category": "tool"})
    # manually set second to ordered
    resp = client.get(f"/internal/data/shopping?user_id={USER}")
    item_id = next(i["id"] for i in resp.json() if i["name"] == "Ordered item")
    client.patch(f"/internal/data/shopping/{item_id}?user_id={USER}", json={"status": "ordered"})

    resp = client.get(f"/internal/data/shopping?user_id={USER}&status=needed")
    assert all(i["status"] == "needed" for i in resp.json())


@pytest.mark.integration
def test_purchase_shopping_item(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/shopping?user_id={USER}", json={
        "name": "Tomato seeds",
        "category": "seed",
        "project_id": project.id,
        "estimated_cost": 5.0,
    })
    item_id = resp.json()["id"]

    resp = client.post(f"/internal/data/shopping/{item_id}/purchase?user_id={USER}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "purchased"
    assert data["expense_id"] is not None  # expense was created


@pytest.mark.integration
def test_project_shopping_list(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    client.post(f"/internal/data/shopping?user_id={USER}", json={
        "name": "Project item", "category": "tool", "project_id": project.id})
    client.post(f"/internal/data/shopping?user_id={USER}", json={
        "name": "Global item", "category": "tool"})

    resp = client.get(f"/internal/data/projects/{project.id}/shopping?user_id={USER}")
    assert resp.status_code == 200
    names = [i["name"] for i in resp.json()]
    assert "Project item" in names
    assert "Global item" not in names
