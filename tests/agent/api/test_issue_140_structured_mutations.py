"""
Tests for #140: the remaining mutation/activity endpoints that still wrapped
LangChain tool prose in {"result": "..."} instead of returning structured
view models — the gaps left over after #133/#136/#138.

Covers: PATCH /garden/profile, PATCH /garden/beds/{id}, POST/PATCH
/garden/containers, POST/PATCH /garden/plants, POST/PATCH
/garden/plants/batch, PATCH /tasks/{id}, PATCH /tasks/series/{id}, and the
activity endpoints (tasks/plants/beds/containers/batches/projects).
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from tests.support.factories import (
    make_bed, make_container, make_plant, make_profile, make_project,
    make_project_brief, make_project_proposal, make_project_revision,
    make_task, make_task_generation_run, make_task_series,
)

client = TestClient(app)
USER = "1"
OTHER_USER = "2"


def _uid():
    return str(uuid.uuid4())


def _base(db_session, profile):
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    return project, revision, run


# ---------------------------------------------------------------------------
# PATCH /garden/profile
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_update_garden_profile_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch(f"/internal/data/garden/profile?user_id={USER}", json={
        "climate_zone": "7b",
        "tray_capacity": 12,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["climate_zone"] == "7b"
    assert body["tray_capacity"] == 12
    assert "result" not in body


# ---------------------------------------------------------------------------
# PATCH /garden/beds/{id}
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_update_bed_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    resp = client.patch(f"/internal/data/garden/beds/{bed.id}?user_id={USER}", json={
        "soil_type": "sandy loam",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == bed.id
    assert body["soil_type"] == "sandy loam"
    assert "result" not in body


@pytest.mark.integration
def test_update_bed_400_on_invalid_dimensions(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    resp = client.patch(f"/internal/data/garden/beds/{bed.id}?user_id={USER}", json={
        "dimensions_sqft": -5,
    })
    assert resp.status_code == 400


@pytest.mark.integration
def test_update_bed_404_for_nonexistent_bed(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch(f"/internal/data/garden/beds/{_uid()}?user_id={USER}", json={"notes": "x"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST/PATCH /garden/containers
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_add_container_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/garden/containers?user_id={USER}", json={
        "name": "Growbag 2",
        "container_type": "growbag",
        "size_gallons": 10.0,
        "location": "back patio",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Growbag 2"
    assert body["container_type"] == "growbag"
    assert "id" in body
    assert "result" not in body


@pytest.mark.integration
def test_add_container_400_on_invalid_type(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/garden/containers?user_id={USER}", json={
        "name": "Mystery box",
        "container_type": "not_a_real_type",
        "size_gallons": 5.0,
        "location": "shed",
    })
    assert resp.status_code == 400


@pytest.mark.integration
def test_update_container_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    container = make_container(db_session, seed_garden_profile)
    resp = client.patch(f"/internal/data/garden/containers/{container.id}?user_id={USER}", json={
        "location": "greenhouse",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == container.id
    assert body["location"] == "greenhouse"


# ---------------------------------------------------------------------------
# POST/PATCH /garden/plants
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_add_plant_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/garden/plants?user_id={USER}", json={
        "name": "Basil",
        "variety": "Genovese",
        "status": "established",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Basil"
    assert body["variety"] == "Genovese"
    assert body["status"] == "established"
    assert "result" not in body


@pytest.mark.integration
def test_add_plant_400_on_conflicting_location(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    container = make_container(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/garden/plants?user_id={USER}", json={
        "name": "Basil",
        "bed_id": bed.id,
        "container_id": container.id,
    })
    assert resp.status_code == 400


@pytest.mark.integration
def test_update_plant_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile)
    resp = client.patch(f"/internal/data/garden/plants/{plant.id}?user_id={USER}", json={
        "status": "producing",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == plant.id
    assert body["status"] == "producing"


@pytest.mark.integration
def test_update_plant_400_on_invalid_status(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile)
    resp = client.patch(f"/internal/data/garden/plants/{plant.id}?user_id={USER}", json={
        "status": "thriving",
    })
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST/PATCH /garden/plants/batch
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_batch_add_plants_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/garden/plants/batch?user_id={USER}", json={
        "name": "Cosmos",
        "variety": "Apricotta",
        "quantity": 4,
        "source": "seed",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["plant_name"] == "Cosmos"
    assert body["quantity_sown"] == 4
    assert len(body["plants"]) == 4
    assert all(p["name"] == "Cosmos" for p in body["plants"])
    assert "result" not in body


@pytest.mark.integration
def test_batch_update_plants_returns_structured_array(patched_sessionlocal, db_session, seed_garden_profile):
    make_plant(db_session, seed_garden_profile, name="Tomato", variety="Sungold", status="seedling")
    make_plant(db_session, seed_garden_profile, name="Tomato", variety="Sungold", status="seedling")
    make_plant(db_session, seed_garden_profile, name="Pepper", variety="Cayenne", status="seedling")

    resp = client.patch(f"/internal/data/garden/plants/batch?user_id={USER}", json={
        "name": "Tomato",
        "variety": "Sungold",
        "new_status": "established",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert all(p["status"] == "established" for p in body)


@pytest.mark.integration
def test_batch_update_plants_400_when_quantity_exceeds_matches(patched_sessionlocal, db_session, seed_garden_profile):
    make_plant(db_session, seed_garden_profile, name="Tomato", status="seedling")
    resp = client.patch(f"/internal/data/garden/plants/batch?user_id={USER}", json={
        "name": "Tomato",
        "quantity": 5,
        "new_status": "established",
    })
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PATCH /tasks/{id}, PATCH /tasks/series/{id}
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_update_task_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    task = make_task(db_session, project, revision, run)
    resp = client.patch(f"/internal/data/tasks/{task.id}?user_id={USER}", json={
        "title": "Water the tomatoes thoroughly",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == task.id
    assert body["title"] == "Water the tomatoes thoroughly"


@pytest.mark.integration
def test_update_task_400_on_invalid_minutes(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    task = make_task(db_session, project, revision, run)
    resp = client.patch(f"/internal/data/tasks/{task.id}?user_id={USER}", json={
        "estimated_minutes": -5,
    })
    assert resp.status_code == 400


@pytest.mark.integration
def test_update_task_404_for_nonexistent_task(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch(f"/internal/data/tasks/{_uid()}?user_id={USER}", json={"title": "x"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_update_task_series_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    series = make_task_series(db_session, project, revision, run)
    resp = client.patch(f"/internal/data/tasks/series/{series.id}?user_id={USER}", json={
        "cadence_days": 1,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == series.id
    assert body["cadence_days"] == 1


@pytest.mark.integration
def test_update_task_series_404_for_other_users_series(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    series = make_task_series(db_session, project, revision, run)
    resp = client.patch(f"/internal/data/tasks/series/{series.id}?user_id={OTHER_USER}", json={
        "title": "Hijacked",
    })
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Activity endpoints
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_task_activity_returns_structured_array(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    task = make_task(db_session, project, revision, run)
    client.patch(f"/internal/data/tasks/{task.id}?user_id={USER}", json={"title": "Renamed"})

    resp = client.get(f"/internal/data/tasks/{task.id}/activity?user_id={USER}")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    assert body[0]["event_type"] == "task_updated"
    assert body[0]["subjects"]


@pytest.mark.integration
def test_get_plant_activity_404_for_nonexistent_plant(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get(f"/internal/data/garden/plants/{_uid()}/activity?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_plant_activity_returns_structured_array(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, status="seedling")
    client.patch(f"/internal/data/garden/plants/{plant.id}?user_id={USER}", json={"status": "established"})

    resp = client.get(f"/internal/data/garden/plants/{plant.id}/activity?user_id={USER}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert body[0]["event_type"] == "plant_status_changed"


@pytest.mark.integration
def test_get_bed_activity_404_for_other_users_bed(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    resp = client.get(f"/internal/data/garden/beds/{bed.id}/activity?user_id={OTHER_USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_bed_activity_returns_structured_array(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    client.patch(f"/internal/data/garden/beds/{bed.id}?user_id={USER}", json={"notes": "Amended."})

    resp = client.get(f"/internal/data/garden/beds/{bed.id}/activity?user_id={USER}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert body[0]["event_type"] == "bed_updated"


@pytest.mark.integration
def test_get_container_activity_returns_structured_array(patched_sessionlocal, db_session, seed_garden_profile):
    container = make_container(db_session, seed_garden_profile, location="front")
    client.patch(f"/internal/data/garden/containers/{container.id}?user_id={USER}", json={"location": "back"})

    resp = client.get(f"/internal/data/garden/containers/{container.id}/activity?user_id={USER}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert body[0]["event_type"] == "container_moved"


@pytest.mark.integration
def test_get_batch_activity_returns_structured_array(patched_sessionlocal, db_session, seed_garden_profile):
    add_resp = client.post(f"/internal/data/garden/plants/batch?user_id={USER}", json={
        "name": "Marigold", "quantity": 2, "source": "seed",
    })
    batch_id = add_resp.json()["batch_id"]

    resp = client.get(f"/internal/data/garden/batches/{batch_id}/activity?user_id={USER}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert "batch_created" in {e["event_type"] for e in body}


@pytest.mark.integration
def test_get_batch_activity_404_for_other_users_batch(patched_sessionlocal, db_session, seed_garden_profile):
    add_resp = client.post(f"/internal/data/garden/plants/batch?user_id={USER}", json={
        "name": "Marigold", "quantity": 1, "source": "seed",
    })
    batch_id = add_resp.json()["batch_id"]

    resp = client.get(f"/internal/data/garden/batches/{batch_id}/activity?user_id={OTHER_USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_project_activity_returns_structured_array(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    task = make_task(db_session, project, revision, run)
    client.patch(f"/internal/data/tasks/{task.id}?user_id={USER}", json={"title": "Renamed"})

    resp = client.get(f"/internal/data/projects/{project.id}/activity?user_id={USER}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert all("event_type" in e for e in body)


@pytest.mark.integration
def test_get_project_activity_404_for_other_users_project(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    resp = client.get(f"/internal/data/projects/{project.id}/activity?user_id={OTHER_USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_project_activity_filters_by_category(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    task = make_task(db_session, project, revision, run)
    client.patch(f"/internal/data/tasks/{task.id}?user_id={USER}", json={"title": "Renamed"})

    resp = client.get(f"/internal/data/projects/{project.id}/activity?user_id={USER}&category=task")
    assert resp.status_code == 200
    body = resp.json()
    assert all(e["category"] == "task" for e in body)


# ---------------------------------------------------------------------------
# Coverage gaps found in the post-implementation audit:
#   - "no garden profile" 404 paths for the create endpoints (distinct from
#     "entity not found" — these hit a different branch in the tool itself)
#   - project_id propagation on batch_add_plants / filtering on batch_update_plants
#   - 400/404 paths on update_task_series that weren't exercised
#   - cross-user vs. nonexistent-id are different code paths for the
#     activity endpoints (ownership check vs. row lookup) and need separate
#     tests rather than treating either as proof of the other
#   - PATCH /tasks/{id} had zero cross-user isolation coverage anywhere in
#     the suite, despite get_task already enforcing it via project ownership
# ---------------------------------------------------------------------------

def _other_user_task(db_session):
    other_profile = make_profile(db_session, user_id=OTHER_USER)
    project = make_project(db_session, other_profile, user_id=OTHER_USER)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    task = make_task(db_session, project, revision, run)
    return project, revision, run, task


@pytest.mark.integration
def test_update_garden_profile_404_when_no_profile(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch(f"/internal/data/garden/profile?user_id={OTHER_USER}", json={"climate_zone": "5a"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_add_container_404_when_no_profile(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/garden/containers?user_id={OTHER_USER}", json={
        "name": "Growbag", "container_type": "growbag", "size_gallons": 5.0, "location": "shed",
    })
    assert resp.status_code == 404


@pytest.mark.integration
def test_update_container_404_for_nonexistent_container(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch(f"/internal/data/garden/containers/{_uid()}?user_id={USER}", json={"location": "x"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_add_plant_404_when_no_profile(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/garden/plants?user_id={OTHER_USER}", json={"name": "Basil"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_update_plant_404_for_nonexistent_plant(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch(f"/internal/data/garden/plants/{_uid()}?user_id={USER}", json={"status": "established"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_batch_add_plants_404_when_no_profile(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(f"/internal/data/garden/plants/batch?user_id={OTHER_USER}", json={
        "name": "Cosmos", "quantity": 2,
    })
    assert resp.status_code == 404


@pytest.mark.integration
def test_batch_add_plants_links_to_project(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/garden/plants/batch?user_id={USER}", json={
        "name": "Marigold", "quantity": 3, "project_id": project.id,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == project.id


@pytest.mark.integration
def test_batch_update_plants_filters_by_project_id(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    other_project = make_project(db_session, seed_garden_profile, name="Other project")
    from db.models import ProjectPlant

    in_project = make_plant(db_session, seed_garden_profile, name="Tomato", status="seedling")
    not_in_project = make_plant(db_session, seed_garden_profile, name="Tomato", status="seedling")
    db_session.add(ProjectPlant(project_id=project.id, plant_id=in_project.id))
    db_session.add(ProjectPlant(project_id=other_project.id, plant_id=not_in_project.id))
    db_session.commit()

    resp = client.patch(f"/internal/data/garden/plants/batch?user_id={USER}", json={
        "name": "Tomato", "project_id": project.id, "new_status": "established",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == in_project.id
    assert body[0]["status"] == "established"


@pytest.mark.integration
def test_batch_update_plants_404_when_no_matches(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch(f"/internal/data/garden/plants/batch?user_id={USER}", json={
        "name": "Nonexistent Plant", "new_status": "established",
    })
    assert resp.status_code == 404


@pytest.mark.integration
def test_update_task_series_400_on_invalid_cadence_days(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    series = make_task_series(db_session, project, revision, run)
    resp = client.patch(f"/internal/data/tasks/series/{series.id}?user_id={USER}", json={
        "cadence_days": 0,
    })
    assert resp.status_code == 400


@pytest.mark.integration
def test_update_task_series_404_for_nonexistent_series(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch(f"/internal/data/tasks/series/{_uid()}?user_id={USER}", json={"active": False})
    assert resp.status_code == 404


@pytest.mark.integration
def test_update_task_404_for_other_users_task(patched_sessionlocal, db_session, seed_garden_profile):
    _, _, _, task = _other_user_task(db_session)
    resp = client.patch(f"/internal/data/tasks/{task.id}?user_id={USER}", json={"title": "Hijacked"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_task_activity_404_for_other_users_task(patched_sessionlocal, db_session, seed_garden_profile):
    _, _, _, task = _other_user_task(db_session)
    resp = client.get(f"/internal/data/tasks/{task.id}/activity?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_task_activity_respects_limit(patched_sessionlocal, db_session, seed_garden_profile):
    project, revision, run = _base(db_session, seed_garden_profile)
    task = make_task(db_session, project, revision, run)
    client.patch(f"/internal/data/tasks/{task.id}?user_id={USER}", json={"title": "First rename"})
    client.patch(f"/internal/data/tasks/{task.id}?user_id={USER}", json={"title": "Second rename"})

    resp = client.get(f"/internal/data/tasks/{task.id}/activity?user_id={USER}&limit=1")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.integration
def test_get_plant_activity_404_for_other_users_plant(patched_sessionlocal, db_session, seed_garden_profile):
    other_profile = make_profile(db_session, user_id=OTHER_USER)
    plant = make_plant(db_session, other_profile, user_id=OTHER_USER)
    resp = client.get(f"/internal/data/garden/plants/{plant.id}/activity?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_bed_activity_404_for_nonexistent_bed(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get(f"/internal/data/garden/beds/{_uid()}/activity?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_container_activity_404_for_nonexistent_container(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get(f"/internal/data/garden/containers/{_uid()}/activity?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_container_activity_404_for_other_users_container(patched_sessionlocal, db_session, seed_garden_profile):
    other_profile = make_profile(db_session, user_id=OTHER_USER)
    container = make_container(db_session, other_profile, user_id=OTHER_USER)
    resp = client.get(f"/internal/data/garden/containers/{container.id}/activity?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_batch_activity_404_for_nonexistent_batch(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.get(f"/internal/data/garden/batches/{_uid()}/activity?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_activity_event_subjects_have_correct_shape(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    client.patch(f"/internal/data/garden/beds/{bed.id}?user_id={USER}", json={"notes": "Top-dressed."})

    resp = client.get(f"/internal/data/garden/beds/{bed.id}/activity?user_id={USER}")
    assert resp.status_code == 200
    event = resp.json()[0]
    assert any(s["subject_type"] == "bed" and s["subject_id"] == bed.id for s in event["subjects"])
