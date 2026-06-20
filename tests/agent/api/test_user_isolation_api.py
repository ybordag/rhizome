"""
API-level multi-tenancy isolation tests.

Every test follows the same pattern:
  1. Create resource owned by user "2"
  2. Request as user "1"
  3. Expect 404 (not the resource, not 403 — we return 404 to avoid leaking
     whether an object exists at all)

List endpoints are tested to confirm they only return the requesting user's
resources — not an empty list, but definitely excluding other users' data.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from db.models import (
    Bed,
    Container,
    GardenProfile,
    GardeningProject,
    MonitorAlert,
    MonitorRun,
    Plant,
)

client = TestClient(app)

USER_1 = "user-uuid-001"
USER_2 = "user-uuid-002"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _uid():
    return str(uuid.uuid4())


def _profile(user_id: str) -> GardenProfile:
    return GardenProfile(
        id=_uid(), user_id=user_id, climate_zone="9b",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(path: str, user_id: str = USER_1) -> int:
    return client.get(f"{path}?user_id={user_id}").status_code


def _patch(path: str, user_id: str = USER_1) -> int:
    return client.patch(f"{path}?user_id={user_id}", json={}).status_code


def _delete(path: str, user_id: str = USER_1) -> int:
    return client.delete(f"{path}?user_id={user_id}").status_code


def _post(path: str, user_id: str = USER_1, body: dict = None) -> int:
    return client.post(f"{path}?user_id={user_id}", json=body or {}).status_code


# ---------------------------------------------------------------------------
# Garden — Beds
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_bed_list_excludes_other_user(patched_sessionlocal, db_session):
    p1 = _profile(USER_1); p2 = _profile(USER_2)
    db_session.add_all([p1, p2])
    bed1 = Bed(id=_uid(), user_id=USER_1, garden_profile_id=p1.id, name="My bed")
    bed2 = Bed(id=_uid(), user_id=USER_2, garden_profile_id=p2.id, name="Their bed")
    db_session.add_all([bed1, bed2])
    db_session.commit()

    resp = client.get(f"/internal/data/garden/beds?user_id={USER_1}")
    assert resp.status_code == 200
    body = str(resp.json())
    assert "Their bed" not in body
    assert "My bed" in body


@pytest.mark.integration
def test_bed_update_wrong_user_returns_404(patched_sessionlocal, db_session):
    p2 = _profile(USER_2)
    db_session.add(p2)
    bed = Bed(id=_uid(), user_id=USER_2, garden_profile_id=p2.id, name="Their bed")
    db_session.add(bed)
    db_session.commit()

    assert _patch(f"/internal/data/garden/beds/{bed.id}") == 404


@pytest.mark.integration
def test_bed_delete_wrong_user_returns_404(patched_sessionlocal, db_session):
    p2 = _profile(USER_2)
    db_session.add(p2)
    bed = Bed(id=_uid(), user_id=USER_2, garden_profile_id=p2.id, name="Their bed")
    db_session.add(bed)
    db_session.commit()

    assert _delete(f"/internal/data/garden/beds/{bed.id}") == 404


# ---------------------------------------------------------------------------
# Garden — Containers
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_container_list_excludes_other_user(patched_sessionlocal, db_session):
    p1 = _profile(USER_1); p2 = _profile(USER_2)
    db_session.add_all([p1, p2])
    c1 = Container(id=_uid(), user_id=USER_1, garden_profile_id=p1.id, name="My pot")
    c2 = Container(id=_uid(), user_id=USER_2, garden_profile_id=p2.id, name="Their pot")
    db_session.add_all([c1, c2])
    db_session.commit()

    resp = client.get(f"/internal/data/garden/containers?user_id={USER_1}")
    assert resp.status_code == 200
    assert "Their pot" not in str(resp.json())
    assert "My pot" in str(resp.json())


@pytest.mark.integration
def test_container_update_wrong_user_returns_404(patched_sessionlocal, db_session):
    p2 = _profile(USER_2)
    db_session.add(p2)
    container = Container(id=_uid(), user_id=USER_2, garden_profile_id=p2.id, name="Their pot")
    db_session.add(container)
    db_session.commit()

    assert _patch(f"/internal/data/garden/containers/{container.id}") == 404


@pytest.mark.integration
def test_container_delete_wrong_user_returns_404(patched_sessionlocal, db_session):
    p2 = _profile(USER_2)
    db_session.add(p2)
    container = Container(id=_uid(), user_id=USER_2, garden_profile_id=p2.id, name="Their pot")
    db_session.add(container)
    db_session.commit()

    assert _delete(f"/internal/data/garden/containers/{container.id}") == 404


# ---------------------------------------------------------------------------
# Garden — Plants
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_plant_list_excludes_other_user(patched_sessionlocal, db_session):
    p1 = _profile(USER_1); p2 = _profile(USER_2)
    db_session.add_all([p1, p2])
    pl1 = Plant(id=_uid(), user_id=USER_1, garden_profile_id=p1.id, name="My tomato")
    pl2 = Plant(id=_uid(), user_id=USER_2, garden_profile_id=p2.id, name="Their tomato")
    db_session.add_all([pl1, pl2])
    db_session.commit()

    resp = client.get(f"/internal/data/garden/plants?user_id={USER_1}")
    assert resp.status_code == 200
    assert "Their tomato" not in str(resp.json())
    assert "My tomato" in str(resp.json())


@pytest.mark.integration
def test_plant_update_wrong_user_returns_404(patched_sessionlocal, db_session):
    p2 = _profile(USER_2)
    db_session.add(p2)
    plant = Plant(id=_uid(), user_id=USER_2, garden_profile_id=p2.id, name="Their tomato")
    db_session.add(plant)
    db_session.commit()

    assert _patch(f"/internal/data/garden/plants/{plant.id}") == 404


@pytest.mark.integration
def test_plant_remove_wrong_user_returns_404(patched_sessionlocal, db_session):
    p2 = _profile(USER_2)
    db_session.add(p2)
    plant = Plant(id=_uid(), user_id=USER_2, garden_profile_id=p2.id, name="Their tomato")
    db_session.add(plant)
    db_session.commit()

    assert _patch(f"/internal/data/garden/plants/{plant.id}/remove") == 404


@pytest.mark.integration
def test_plant_delete_wrong_user_returns_404(patched_sessionlocal, db_session):
    p2 = _profile(USER_2)
    db_session.add(p2)
    plant = Plant(id=_uid(), user_id=USER_2, garden_profile_id=p2.id, name="Their tomato")
    db_session.add(plant)
    db_session.commit()

    assert _delete(f"/internal/data/garden/plants/{plant.id}") == 404


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_project_list_excludes_other_user(patched_sessionlocal, db_session):
    p1 = _profile(USER_1); p2 = _profile(USER_2)
    db_session.add_all([p1, p2])
    proj1 = GardeningProject(
        id=_uid(), user_id=USER_1, garden_profile_id=p1.id,
        name="My project", goal="grow tomatoes", status="planning"
    )
    proj2 = GardeningProject(
        id=_uid(), user_id=USER_2, garden_profile_id=p2.id,
        name="Their project", goal="grow basil", status="planning"
    )
    db_session.add_all([proj1, proj2])
    db_session.commit()

    resp = client.get(f"/internal/data/projects?user_id={USER_1}")
    assert resp.status_code == 200
    assert "Their project" not in str(resp.json())
    assert "My project" in str(resp.json())


@pytest.mark.integration
def test_project_get_wrong_user_returns_404(patched_sessionlocal, db_session):
    p2 = _profile(USER_2)
    db_session.add(p2)
    proj = GardeningProject(
        id=_uid(), user_id=USER_2, garden_profile_id=p2.id,
        name="Their project", goal="grow basil", status="planning"
    )
    db_session.add(proj)
    db_session.commit()

    assert _get(f"/internal/data/projects/{proj.id}") == 404


@pytest.mark.integration
def test_project_update_wrong_user_returns_404(patched_sessionlocal, db_session):
    p2 = _profile(USER_2)
    db_session.add(p2)
    proj = GardeningProject(
        id=_uid(), user_id=USER_2, garden_profile_id=p2.id,
        name="Their project", goal="grow basil", status="planning"
    )
    db_session.add(proj)
    db_session.commit()

    assert _patch(f"/internal/data/projects/{proj.id}") == 404


@pytest.mark.integration
def test_project_delete_wrong_user_returns_404(patched_sessionlocal, db_session):
    p2 = _profile(USER_2)
    db_session.add(p2)
    proj = GardeningProject(
        id=_uid(), user_id=USER_2, garden_profile_id=p2.id,
        name="Their project", goal="grow basil", status="planning"
    )
    db_session.add(proj)
    db_session.commit()

    assert _delete(f"/internal/data/projects/{proj.id}") == 404


@pytest.mark.integration
def test_project_progress_wrong_user_returns_404(patched_sessionlocal, db_session):
    p2 = _profile(USER_2)
    db_session.add(p2)
    proj = GardeningProject(
        id=_uid(), user_id=USER_2, garden_profile_id=p2.id,
        name="Their project", goal="grow basil", status="planning"
    )
    db_session.add(proj)
    db_session.commit()

    assert _get(f"/internal/data/projects/{proj.id}/progress") == 404


# ---------------------------------------------------------------------------
# Monitor runs
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_monitor_run_list_excludes_other_user(patched_sessionlocal, db_session):
    run1 = MonitorRun(id=_uid(), user_id=USER_1, run_type="triage", status="completed",
                      summary="User 1 triage")
    run2 = MonitorRun(id=_uid(), user_id=USER_2, run_type="triage", status="completed",
                      summary="User 2 triage")
    db_session.add_all([run1, run2])
    db_session.commit()

    resp = client.get(f"/internal/data/monitor/runs?user_id={USER_1}")
    assert resp.status_code == 200
    assert "User 2 triage" not in str(resp.json())
    assert "User 1 triage" in str(resp.json())


@pytest.mark.integration
def test_monitor_run_get_wrong_user_returns_404(patched_sessionlocal, db_session):
    run = MonitorRun(id=_uid(), user_id=USER_2, run_type="weather", status="completed")
    db_session.add(run)
    db_session.commit()

    assert _get(f"/internal/data/monitor/runs/{run.id}") == 404


# ---------------------------------------------------------------------------
# Alerts (supplemental — dismiss wrong user already tested in test_internal_api.py)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_alert_list_excludes_other_user(patched_sessionlocal, db_session):
    future = _now() + timedelta(hours=24)
    a1 = MonitorAlert(id=_uid(), user_id=USER_1, expires_at=future,
                      alert_type="triage", severity="high", title="My alert", body=".")
    a2 = MonitorAlert(id=_uid(), user_id=USER_2, expires_at=future,
                      alert_type="triage", severity="high", title="Their alert", body=".")
    db_session.add_all([a1, a2])
    db_session.commit()

    resp = client.get(f"/internal/data/alerts?user_id={USER_1}")
    assert resp.status_code == 200
    assert "Their alert" not in str(resp.json())
    assert "My alert" in str(resp.json())


# ---------------------------------------------------------------------------
# Triage snapshot (GET /triage/latest) — different users have different
# garden locations, so triage data must not be shared between them.
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_triage_latest_scoped_to_current_user(patched_sessionlocal, db_session):
    from db.models import TriageSnapshot

    profile_1 = _profile(USER_1)
    profile_2 = _profile(USER_2)
    db_session.add_all([profile_1, profile_2])
    db_session.commit()

    snapshot_1 = TriageSnapshot(
        id=_uid(), garden_profile_id=profile_1.id, timezone="America/Los_Angeles",
        reasoning_summary="User 1 plan", user_focus_summary="user-1 session",
    )
    snapshot_2 = TriageSnapshot(
        id=_uid(), garden_profile_id=profile_2.id, timezone="America/Los_Angeles",
        reasoning_summary="User 2 plan", user_focus_summary="user-2 session",
    )
    db_session.add_all([snapshot_1, snapshot_2])
    db_session.commit()

    resp = client.get(f"/internal/data/triage/latest?user_id={USER_1}")
    assert resp.status_code == 200
    assert "user-2 session" not in str(resp.json())
    assert "user-1 session" in str(resp.json())


@pytest.mark.integration
def test_triage_latest_no_profile_returns_not_found_message(patched_sessionlocal, db_session):
    resp = client.get(f"/internal/data/triage/latest?user_id={USER_1}")
    assert resp.status_code == 200
    assert "No triage snapshot found" in str(resp.json())
