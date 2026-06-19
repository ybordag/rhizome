"""
Tests for Group 1 endpoint additions:
  - #112: Task CRUD (POST, DELETE, GET type/subject filters)
  - #116: Garden detail endpoints (GET beds/{id}, containers/{id}, plants/{id},
          POST beds, plant location filters)
  - #123: Available resources filter + project bed/container lists
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from db.models import Bed, Container, GardeningProject, Plant, ProjectBed, ProjectContainer
from tests.support.factories import (
    make_bed, make_container, make_plant, make_profile, make_project,
    make_project_brief, make_project_proposal, make_project_revision,
    make_task, make_task_generation_run,
)

client = TestClient(app)
USER = "1"


def _uid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# #112 — Task CRUD
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_post_tasks_creates_task(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/tasks?user_id={USER}", json={
        "project_id": project.id,
        "title": "Buy potting mix",
        "type": "maintenance",
        "priority": "normal",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Buy potting mix"
    assert data["type"] == "maintenance"
    assert data["is_user_modified"] is True
    assert data["project_id"] == project.id


@pytest.mark.integration
def test_post_tasks_wrong_project_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/tasks?user_id={USER}", json={
        "project_id": "nonexistent-project",
        "title": "X",
        "type": "maintenance",
    })
    assert resp.status_code == 404


@pytest.mark.integration
def test_delete_task_removes_it(patched_sessionlocal, db_session, seed_garden_profile):
    profile = seed_garden_profile
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.delete", title="Delete me")
    resp = client.delete(f"/internal/data/tasks/{task.id}?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.integration
def test_delete_task_in_progress_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    profile = seed_garden_profile
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    task = make_task(db_session, project=project, revision=revision, generation_run=run,
                     generator_key="test.inprogress", title="In progress task", status="in_progress")
    resp = client.delete(f"/internal/data/tasks/{task.id}?user_id={USER}")
    assert resp.status_code == 400


@pytest.mark.integration
def test_list_tasks_type_filter(patched_sessionlocal, db_session, seed_garden_profile):
    profile = seed_garden_profile
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    make_task(db_session, project=project, revision=revision, generation_run=run,
              generator_key="t.maint", title="Watering", status="pending", type="maintenance")
    make_task(db_session, project=project, revision=revision, generation_run=run,
              generator_key="t.mile", title="Plant tomatoes", status="pending", type="milestone")

    resp = client.get(f"/internal/data/tasks?user_id={USER}&type=maintenance")
    assert resp.status_code == 200
    types = [t["type"] for t in resp.json()]
    assert all(t == "maintenance" for t in types)
    assert "milestone" not in types


# ---------------------------------------------------------------------------
# #116 — Garden detail endpoints
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_bed_detail(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile, name="Test Bed", location="Courtyard")
    resp = client.get(f"/internal/data/garden/beds/{bed.id}?user_id={USER}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == bed.id
    assert data["name"] == "Test Bed"
    assert data["location"] == "Courtyard"


@pytest.mark.integration
def test_get_bed_detail_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    resp = client.get(f"/internal/data/garden/beds/{bed.id}?user_id=other-user")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_container_detail(patched_sessionlocal, db_session, seed_garden_profile):
    container = make_container(db_session, seed_garden_profile, name="My Pot")
    resp = client.get(f"/internal/data/garden/containers/{container.id}?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "My Pot"


@pytest.mark.integration
def test_get_plant_detail(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, name="Basil")
    resp = client.get(f"/internal/data/garden/plants/{plant.id}?user_id={USER}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == plant.id
    assert data["name"] == "Basil"
    # detail view has extra fields
    assert "updated_at" in data


@pytest.mark.integration
def test_post_garden_beds_creates_bed(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/garden/beds?user_id={USER}", json={
        "name": "New Raised Bed",
        "location": "Backyard",
        "sunlight": "Full sun",
        "soil_type": "Amended loam",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "New Raised Bed"
    assert data["location"] == "Backyard"


@pytest.mark.integration
def test_list_plants_bed_id_filter(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    p1 = make_plant(db_session, seed_garden_profile, name="Tomato")
    p1.bed_id = bed.id
    p2 = make_plant(db_session, seed_garden_profile, name="Basil")
    db_session.commit()

    resp = client.get(f"/internal/data/garden/plants?user_id={USER}&bed_id={bed.id}")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "Tomato" in names
    assert "Basil" not in names


@pytest.mark.integration
def test_list_plants_location_filter(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile, location="Courtyard")
    p1 = make_plant(db_session, seed_garden_profile, name="Tomato")
    p1.bed_id = bed.id
    p2 = make_plant(db_session, seed_garden_profile, name="Basil")
    db_session.commit()

    resp = client.get(f"/internal/data/garden/plants?user_id={USER}&location=Courtyard")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "Tomato" in names
    assert "Basil" not in names


# ---------------------------------------------------------------------------
# #123 — Available resources
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_beds_available_filter(patched_sessionlocal, db_session, seed_garden_profile):
    free_bed = make_bed(db_session, seed_garden_profile, name="Free Bed")
    busy_bed = make_bed(db_session, seed_garden_profile, name="Busy Bed")

    active_project = make_project(db_session, seed_garden_profile, name="Active", status="active")
    db_session.add(ProjectBed(project_id=active_project.id, bed_id=busy_bed.id))
    db_session.commit()

    resp = client.get(f"/internal/data/garden/beds?user_id={USER}&available=true")
    assert resp.status_code == 200
    names = [b["name"] for b in resp.json()]
    assert "Free Bed" in names
    assert "Busy Bed" not in names


@pytest.mark.integration
def test_get_containers_available_filter(patched_sessionlocal, db_session, seed_garden_profile):
    free = make_container(db_session, seed_garden_profile, name="Free Pot")
    busy = make_container(db_session, seed_garden_profile, name="Busy Pot")

    active_project = make_project(db_session, seed_garden_profile, name="Active", status="active")
    db_session.add(ProjectContainer(project_id=active_project.id, container_id=busy.id))
    db_session.commit()

    resp = client.get(f"/internal/data/garden/containers?user_id={USER}&available=true")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "Free Pot" in names
    assert "Busy Pot" not in names


@pytest.mark.integration
def test_list_project_beds_includes_availability(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile, name="My Project", status="planning")
    bed = make_bed(db_session, seed_garden_profile, name="My Bed")
    db_session.add(ProjectBed(project_id=project.id, bed_id=bed.id))
    db_session.commit()

    resp = client.get(f"/internal/data/projects/{project.id}/beds?user_id={USER}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "My Bed"
    assert data[0]["available"] is True  # no other active project holds it


@pytest.mark.integration
def test_list_project_containers_returns_list(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile, name="Container Project", status="active")
    container = make_container(db_session, seed_garden_profile, name="My Container")
    db_session.add(ProjectContainer(project_id=project.id, container_id=container.id))
    db_session.commit()

    resp = client.get(f"/internal/data/projects/{project.id}/containers?user_id={USER}")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["name"] == "My Container"
