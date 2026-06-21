"""Regression coverage for structured PATCH /garden/plants/batch/remove."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from db.models import ProjectPlant
from tests.support.factories import (
    link_plant_to_project,
    make_batch,
    make_plant,
    make_project,
)

client = TestClient(app)
USER = "1"


@pytest.mark.integration
def test_batch_remove_plants_returns_structured_array(patched_sessionlocal, db_session, seed_garden_profile):
    batch = make_batch(db_session, seed_garden_profile, plant_name="Marigold", name="Marigold Batch")
    plants = [
        make_plant(db_session, seed_garden_profile, batch=batch, name="Marigold", status="seedling")
        for _ in range(3)
    ]

    resp = client.patch(f"/internal/data/garden/plants/batch/remove?user_id={USER}", json={
        "name": "Marigold",
        "reason": "culled extras",
        "current_status": "seedling",
        "quantity": 2,
    })

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert "result" not in body[0]
    assert [p["id"] for p in body] == [plants[0].id, plants[1].id]
    assert all(p["status"] == "removed" for p in body)


@pytest.mark.integration
def test_batch_remove_plants_updates_rows_notes_and_project_links(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    project = make_project(db_session, seed_garden_profile)
    plant = make_plant(db_session, seed_garden_profile, name="Cosmos", status="seedling")
    link = link_plant_to_project(db_session, project, plant)

    resp = client.patch(f"/internal/data/garden/plants/batch/remove?user_id={USER}", json={
        "name": "Cosmos",
        "reason": "root rot",
        "project_id": project.id,
    })

    assert resp.status_code == 200
    body = resp.json()
    assert [p["id"] for p in body] == [plant.id]
    db_session.expire_all()
    assert db_session.query(ProjectPlant).filter(ProjectPlant.id == link.id).one().removed_at is not None
    refreshed = db_session.get(type(plant), plant.id)
    assert refreshed.status == "removed"
    assert "root rot" in refreshed.notes


@pytest.mark.integration
def test_batch_remove_plants_filters_by_project_id(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile, name="Project A")
    other_project = make_project(db_session, seed_garden_profile, name="Project B")
    in_project = make_plant(db_session, seed_garden_profile, name="Tomato", status="seedling")
    not_in_project = make_plant(db_session, seed_garden_profile, name="Tomato", status="seedling")
    link_plant_to_project(db_session, project, in_project)
    link_plant_to_project(db_session, other_project, not_in_project)

    resp = client.patch(f"/internal/data/garden/plants/batch/remove?user_id={USER}", json={
        "name": "Tomato",
        "project_id": project.id,
        "reason": "space constraints",
    })

    assert resp.status_code == 200
    body = resp.json()
    assert [p["id"] for p in body] == [in_project.id]
    assert body[0]["status"] == "removed"
    db_session.expire_all()
    assert db_session.get(type(not_in_project), not_in_project.id).status == "seedling"


@pytest.mark.integration
def test_batch_remove_plants_ignores_inactive_project_links(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    project = make_project(db_session, seed_garden_profile)
    active = make_plant(db_session, seed_garden_profile, name="Zinnia", status="seedling")
    inactive = make_plant(db_session, seed_garden_profile, name="Zinnia", status="seedling")
    link_plant_to_project(db_session, project, active)
    link_plant_to_project(db_session, project, inactive, removed_at=datetime(2026, 4, 1))

    resp = client.patch(f"/internal/data/garden/plants/batch/remove?user_id={USER}", json={
        "name": "Zinnia",
        "project_id": project.id,
        "reason": "bed reset",
    })

    assert resp.status_code == 200
    body = resp.json()
    assert [p["id"] for p in body] == [active.id]
    db_session.expire_all()
    assert db_session.get(type(inactive), inactive.id).status == "seedling"


@pytest.mark.integration
def test_batch_remove_plants_ignores_already_removed_plants(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    active = make_plant(db_session, seed_garden_profile, name="Dill", status="seedling")
    already_removed = make_plant(db_session, seed_garden_profile, name="Dill", status="removed")

    resp = client.patch(f"/internal/data/garden/plants/batch/remove?user_id={USER}", json={
        "name": "Dill",
        "reason": "cleanup",
    })

    assert resp.status_code == 200
    body = resp.json()
    assert [p["id"] for p in body] == [active.id]
    assert body[0]["status"] == "removed"
    assert already_removed.id not in [p["id"] for p in body]


@pytest.mark.integration
def test_batch_remove_plants_returns_400_when_quantity_is_zero(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    plant = make_plant(db_session, seed_garden_profile, name="Parsley", status="seedling")

    resp = client.patch(f"/internal/data/garden/plants/batch/remove?user_id={USER}", json={
        "name": "Parsley",
        "reason": "cleanup",
        "quantity": 0,
    })

    assert resp.status_code == 400
    db_session.expire_all()
    assert db_session.get(type(plant), plant.id).status == "seedling"


@pytest.mark.integration
def test_batch_remove_plants_returns_404_when_no_matches(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch(f"/internal/data/garden/plants/batch/remove?user_id={USER}", json={
        "name": "Nonexistent Plant",
        "reason": "cleanup",
    })

    assert resp.status_code == 404


@pytest.mark.integration
def test_batch_remove_plants_returns_400_when_quantity_exceeds_matches(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    make_plant(db_session, seed_garden_profile, name="Basil", status="seedling")

    resp = client.patch(f"/internal/data/garden/plants/batch/remove?user_id={USER}", json={
        "name": "Basil",
        "reason": "thinning",
        "quantity": 3,
    })

    assert resp.status_code == 400


@pytest.mark.integration
def test_batch_remove_plants_returns_400_on_invalid_current_status(
    patched_sessionlocal,
    db_session,
    seed_garden_profile,
):
    resp = client.patch(f"/internal/data/garden/plants/batch/remove?user_id={USER}", json={
        "name": "Basil",
        "reason": "cleanup",
        "current_status": "not-a-status",
    })

    assert resp.status_code == 400


@pytest.mark.integration
def test_batch_remove_plants_scoped_to_current_user(patched_sessionlocal, db_session, seed_garden_profile):
    mine = make_plant(db_session, seed_garden_profile, name="Pepper", status="seedling", user_id=USER)
    make_plant(db_session, seed_garden_profile, name="Pepper", status="seedling", user_id="2")

    resp = client.patch(f"/internal/data/garden/plants/batch/remove?user_id={USER}", json={
        "name": "Pepper",
        "reason": "culled extras",
    })

    assert resp.status_code == 200
    body = resp.json()
    assert [p["id"] for p in body] == [mine.id]
