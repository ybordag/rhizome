"""
Tests for Group B endpoint additions:
  - #128: Quick care recording (plants, beds, containers)
  - #129: Incident CRUD gaps + manual treatment plans
"""
import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from tests.support.factories import (
    make_bed, make_container, make_incident_report, make_plant, make_profile,
    make_project, make_treatment_plan,
)

client = TestClient(app)
USER = "1"


# ---------------------------------------------------------------------------
# #128 — Quick care recording
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_record_plant_care_watered(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, name="Basil", last_watered_at=None)

    resp = client.post(f"/internal/data/garden/plants/{plant.id}/care?user_id={USER}",
                       json={"care_type": "watered"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["care_state"]["last_watered_at"] is not None
    assert data["task"] is None  # no existing task

    db_session.refresh(plant)
    assert plant.last_watered_at is not None


@pytest.mark.integration
def test_record_plant_care_with_recorded_at(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, name="Tomato")
    resp = client.post(f"/internal/data/garden/plants/{plant.id}/care?user_id={USER}",
                       json={"care_type": "fertilized", "recorded_at": "2026-06-01T10:00:00"})
    assert resp.status_code == 200
    db_session.refresh(plant)
    assert plant.last_fertilized_at is not None
    assert "2026-06-01" in plant.last_fertilized_at.isoformat()


@pytest.mark.integration
def test_record_bed_care(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/garden/beds/{bed.id}/care?user_id={USER}",
                       json={"care_type": "inspected", "notes": "No issues found"})
    assert resp.status_code == 200
    assert resp.json()["care_state"]["last_inspected_at"] is not None
    db_session.refresh(bed)
    assert bed.care_state_notes == "No issues found"


@pytest.mark.integration
def test_record_container_care(patched_sessionlocal, db_session, seed_garden_profile):
    container = make_container(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/garden/containers/{container.id}/care?user_id={USER}",
                       json={"care_type": "watered"})
    assert resp.status_code == 200
    assert resp.json()["care_state"]["last_watered_at"] is not None


@pytest.mark.integration
def test_record_care_invalid_type_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/garden/plants/{plant.id}/care?user_id={USER}",
                       json={"care_type": "amended"})  # amended not valid for plants
    assert resp.status_code == 400


@pytest.mark.integration
def test_record_care_invalid_care_type_string_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/garden/plants/{plant.id}/care?user_id={USER}",
                       json={"care_type": "teleported"})
    assert resp.status_code == 400


@pytest.mark.integration
def test_record_care_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/garden/plants/{plant.id}/care?user_id=other-user",
                       json={"care_type": "watered"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_record_bed_care_amended_valid(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/garden/beds/{bed.id}/care?user_id={USER}",
                       json={"care_type": "amended"})
    assert resp.status_code == 200
    assert resp.json()["care_state"]["last_amended_at"] is not None


@pytest.mark.integration
def test_record_plant_care_pruned_valid(patched_sessionlocal, db_session, seed_garden_profile):
    plant = make_plant(db_session, seed_garden_profile, last_pruned_at=None)
    resp = client.post(f"/internal/data/garden/plants/{plant.id}/care?user_id={USER}",
                       json={"care_type": "pruned"})
    assert resp.status_code == 200
    assert resp.json()["care_state"]["last_pruned_at"] is not None


@pytest.mark.integration
def test_record_bed_care_pruned_invalid(patched_sessionlocal, db_session, seed_garden_profile):
    bed = make_bed(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/garden/beds/{bed.id}/care?user_id={USER}",
                       json={"care_type": "pruned"})  # pruned is plant-only
    assert resp.status_code == 400


@pytest.mark.integration
def test_record_container_care_amended_valid(patched_sessionlocal, db_session, seed_garden_profile):
    container = make_container(db_session, seed_garden_profile)
    resp = client.post(f"/internal/data/garden/containers/{container.id}/care?user_id={USER}",
                       json={"care_type": "amended"})
    assert resp.status_code == 200
    assert resp.json()["care_state"]["last_amended_at"] is not None


@pytest.mark.integration
def test_record_care_completes_existing_task(
    patched_sessionlocal, db_session, seed_garden_profile,
):
    """When a pending watering task is linked to a plant, recording care completes it."""
    from tests.support.factories import (
        make_project, make_project_brief, make_project_proposal,
        make_project_revision, make_task_generation_run, make_task,
    )
    profile = seed_garden_profile
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    run = make_task_generation_run(db_session, project=project, revision=revision)
    plant = make_plant(db_session, profile, name="Care Plant", last_watered_at=None)

    # Create a pending watering task linked to this plant
    task = make_task(
        db_session, project=project, revision=revision, generation_run=run,
        generator_key="care.water.weekly", title="Water the plants",
        status="pending",
        linked_subjects=[{"subject_type": "plant", "subject_id": plant.id, "role": "primary"}],
    )

    resp = client.post(
        f"/internal/data/garden/plants/{plant.id}/care?user_id={USER}",
        json={"care_type": "watered"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"] is not None
    assert data["task"]["id"] == task.id
    assert data["task"]["status"] == "done"
    assert data["care_state"]["last_watered_at"] is not None


# ---------------------------------------------------------------------------
# #129 — Incident CRUD gaps
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_list_incidents_severity_filter(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    make_incident_report(db_session, project_id=project.id, severity="high", summary="High severity")
    make_incident_report(db_session, project_id=project.id, severity="low", summary="Low severity")

    resp = client.get(f"/internal/data/incidents?user_id={USER}&severity=high")
    assert resp.status_code == 200
    results = resp.json()
    assert all(r["severity"] == "high" for r in results)
    assert any(r["summary"] == "High severity" for r in results)


@pytest.mark.integration
def test_list_incidents_since_filter(patched_sessionlocal, db_session, seed_garden_profile):
    from datetime import datetime, timezone
    project = make_project(db_session, seed_garden_profile)
    old = make_incident_report(db_session, project_id=project.id, summary="Old incident")
    old.created_at = datetime(2026, 1, 1, tzinfo=None)
    db_session.commit()
    make_incident_report(db_session, project_id=project.id, summary="Recent incident")

    resp = client.get(f"/internal/data/incidents?user_id={USER}&since=2026-06-01T00:00:00")
    assert resp.status_code == 200
    summaries = [r["summary"] for r in resp.json()]
    assert "Recent incident" in summaries
    assert "Old incident" not in summaries


@pytest.mark.integration
def test_list_incidents_incident_type_filter(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    make_incident_report(db_session, project_id=project.id, incident_type="pest")
    make_incident_report(db_session, project_id=project.id, incident_type="disease")

    resp = client.get(f"/internal/data/incidents?user_id={USER}&incident_type=pest")
    assert resp.status_code == 200
    assert all(r["incident_type"] == "pest" for r in resp.json())


@pytest.mark.integration
def test_list_incidents_multi_tenancy(patched_sessionlocal, db_session, seed_garden_profile):
    """Incidents from user 1's projects must not appear when querying as user 2."""
    project = make_project(db_session, seed_garden_profile)
    make_incident_report(db_session, project_id=project.id, summary="User 1 incident")

    resp = client.get("/internal/data/incidents?user_id=user-2")
    assert resp.status_code == 200
    assert all(r["summary"] != "User 1 incident" for r in resp.json())


@pytest.mark.integration
def test_update_incident(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, summary="Original")

    resp = client.patch(f"/internal/data/incidents/{incident.id}?user_id={USER}",
                        json={"summary": "Updated", "severity": "critical"})
    assert resp.status_code == 200
    assert resp.json()["summary"] == "Updated"
    assert resp.json()["severity"] == "critical"


@pytest.mark.integration
def test_update_incident_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id)

    resp = client.patch(f"/internal/data/incidents/{incident.id}?user_id=other-user",
                        json={"summary": "Hack"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_delete_incident(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id)

    resp = client.delete(f"/internal/data/incidents/{incident.id}?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.integration
def test_delete_incident_with_approved_plan_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id)
    make_treatment_plan(db_session, incident, status="approved")

    resp = client.delete(f"/internal/data/incidents/{incident.id}?user_id={USER}")
    assert resp.status_code == 400


@pytest.mark.integration
def test_create_manual_treatment_plan(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id)

    resp = client.post(f"/internal/data/incidents/{incident.id}/treatment/manual?user_id={USER}",
                       json={
                           "approach_summary": "Neem oil spray every 3 days",
                           "recommended_steps": [
                               {"title": "Apply neem oil", "task_type": "maintenance", "estimated_minutes": 15, "days_from_approval": 0},
                               {"title": "Reinspect", "task_type": "inspection", "estimated_minutes": 10, "days_from_approval": 3},
                           ],
                           "follow_up_strategy": "Monitor weekly for 2 weeks",
                       })
    assert resp.status_code == 200
    data = resp.json()
    assert data["approach_summary"] == "Neem oil spray every 3 days"
    assert len(data["recommended_steps"]) == 2
    assert data["status"] == "draft"


@pytest.mark.integration
def test_create_manual_treatment_plan_duplicate_draft_returns_409(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id)
    make_treatment_plan(db_session, incident, status="draft")

    resp = client.post(f"/internal/data/incidents/{incident.id}/treatment/manual?user_id={USER}",
                       json={"approach_summary": "Another plan", "recommended_steps": []})
    assert resp.status_code == 409


@pytest.mark.integration
def test_update_treatment_plan(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id)
    plan = make_treatment_plan(db_session, incident, status="draft")

    resp = client.patch(f"/internal/data/treatment-plans/{plan.id}?user_id={USER}",
                        json={"approach_summary": "Updated approach"})
    assert resp.status_code == 200
    assert resp.json()["approach_summary"] == "Updated approach"


@pytest.mark.integration
def test_update_approved_treatment_plan_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id)
    plan = make_treatment_plan(db_session, incident, status="approved")

    resp = client.patch(f"/internal/data/treatment-plans/{plan.id}?user_id={USER}",
                        json={"approach_summary": "Sneaky edit"})
    assert resp.status_code == 400


@pytest.mark.integration
def test_delete_treatment_plan(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id)
    plan = make_treatment_plan(db_session, incident, status="draft")

    resp = client.delete(f"/internal/data/treatment-plans/{plan.id}?user_id={USER}")
    assert resp.status_code == 200


@pytest.mark.integration
def test_delete_approved_treatment_plan_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id)
    plan = make_treatment_plan(db_session, incident, status="approved")

    resp = client.delete(f"/internal/data/treatment-plans/{plan.id}?user_id={USER}")
    assert resp.status_code == 400


@pytest.mark.integration
def test_treatment_plan_write_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id)
    plan = make_treatment_plan(db_session, incident, status="draft")

    resp = client.patch(f"/internal/data/treatment-plans/{plan.id}?user_id=other-user",
                        json={"approach_summary": "Unauthorized edit"})
    assert resp.status_code == 404

    resp = client.delete(f"/internal/data/treatment-plans/{plan.id}?user_id=other-user")
    assert resp.status_code == 404


@pytest.mark.integration
def test_create_manual_treatment_plan_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id)

    resp = client.post(f"/internal/data/incidents/{incident.id}/treatment/manual?user_id=other-user",
                       json={"approach_summary": "Unauthorized", "recommended_steps": []})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Project-less incident isolation
#
# IncidentReport now carries its own user_id column (audit fix, post-#130) —
# project-less incidents are scoped to their owner directly rather than being
# universally inaccessible (the old zinnia-era workaround).
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_list_incidents_includes_owned_projectless(patched_sessionlocal, db_session, seed_garden_profile):
    orphan = make_incident_report(db_session, project_id=None, incident_type="pest", user_id=USER)

    resp = client.get(f"/internal/data/incidents?user_id={USER}")
    assert resp.status_code == 200
    ids = [i["id"] for i in resp.json()]
    assert orphan.id in ids


@pytest.mark.integration
def test_list_incidents_excludes_projectless_owned_by_other_user(patched_sessionlocal, db_session, seed_garden_profile):
    orphan = make_incident_report(db_session, project_id=None, incident_type="pest", user_id="other-user")

    resp = client.get(f"/internal/data/incidents?user_id={USER}")
    assert resp.status_code == 200
    ids = [i["id"] for i in resp.json()]
    assert orphan.id not in ids


@pytest.mark.integration
def test_patch_owned_projectless_incident_succeeds(patched_sessionlocal, db_session, seed_garden_profile):
    orphan = make_incident_report(db_session, project_id=None, user_id=USER)

    resp = client.patch(f"/internal/data/incidents/{orphan.id}?user_id={USER}",
                        json={"severity": "high"})
    assert resp.status_code == 200


@pytest.mark.integration
def test_patch_projectless_incident_owned_by_other_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    orphan = make_incident_report(db_session, project_id=None, user_id="other-user")

    resp = client.patch(f"/internal/data/incidents/{orphan.id}?user_id={USER}",
                        json={"severity": "high"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_delete_projectless_incident_owned_by_other_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    orphan = make_incident_report(db_session, project_id=None, user_id="other-user")

    resp = client.delete(f"/internal/data/incidents/{orphan.id}?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_manual_treatment_plan_on_owned_projectless_incident_succeeds(patched_sessionlocal, db_session, seed_garden_profile):
    orphan = make_incident_report(db_session, project_id=None, user_id=USER)

    resp = client.post(f"/internal/data/incidents/{orphan.id}/treatment/manual?user_id={USER}",
                       json={"approach_summary": "Fix it", "recommended_steps": []})
    assert resp.status_code == 200


@pytest.mark.integration
def test_manual_treatment_plan_on_projectless_incident_owned_by_other_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    orphan = make_incident_report(db_session, project_id=None, user_id="other-user")

    resp = client.post(f"/internal/data/incidents/{orphan.id}/treatment/manual?user_id={USER}",
                       json={"approach_summary": "Fix it", "recommended_steps": []})
    assert resp.status_code == 404
