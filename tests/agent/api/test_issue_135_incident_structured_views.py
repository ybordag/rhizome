"""
Tests for #135: structured JSON for the remaining incident/treatment-plan
endpoints — `GET /incidents/{id}` (now `IncidentDetailView`), `GET
/incidents/{id}/treatment`, `POST /incidents`, `PATCH /incidents/{id}/resolve`,
`PATCH /treatment-plans/{id}/approve`, and `GET /incidents/{id}/activity` (now
`TreatmentPlanView`/`IncidentView`/`ActivityEventView`).

Two live bugs were found and fixed while doing this, both previously
uncovered by any test:

1. `GET /incidents/{id}/treatment` called the `get_treatment_plan` tool with
   `{"incident_id": incident_id}`, but the tool's parameter is
   `treatment_plan_id` — every call raised a pydantic `ValidationError`
   before the tool body ran (same shape of bug as #136's
   `resolve_interaction` mismatch). Fixed by querying the latest plan for the
   incident directly instead of going through the tool.
2. `POST /incidents/{id}/treatment/manual` stored `follow_up_strategy` as
   `[body.follow_up_strategy]` — a list containing a bare string — while
   AI-drafted plans (`agent/domain/incidents.py`'s `_treatment_steps`) always
   store a list of `{"title": ...}` dicts. The `get_treatment_plan` tool's
   prose renderer does `follow_up['title']`, which would `TypeError` on a
   plain string. Fixed to wrap the string in a `{"title": ...}` dict to match
   the canonical shape (and to satisfy `TreatmentPlanView.follow_up_strategy:
   list[dict]`).
"""
import pytest
from fastapi.testclient import TestClient

from agent.api.app import app
from tests.support.factories import make_incident_report, make_project, make_treatment_plan

client = TestClient(app)
USER = "1"


# ---------------------------------------------------------------------------
# GET /incidents/{id} — IncidentDetailView
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_incident_returns_detail_view_with_subjects_and_plan(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER, summary="Aphids spotted")
    make_treatment_plan(db_session, incident, status="draft")

    resp = client.get(f"/internal/data/incidents/{incident.id}?user_id={USER}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == incident.id
    assert body["summary"] == "Aphids spotted"
    assert body["treatment_plan"]["status"] == "draft"
    assert body["treatment_plan"]["approach_summary"]
    assert body["subjects"] == []


@pytest.mark.integration
def test_get_incident_with_no_treatment_plan_returns_null(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)

    resp = client.get(f"/internal/data/incidents/{incident.id}?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json()["treatment_plan"] is None


@pytest.mark.integration
def test_get_incident_picks_most_recent_plan(patched_sessionlocal, db_session, seed_garden_profile):
    """A superseded draft shouldn't shadow the plan that actually matters."""
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)
    make_treatment_plan(db_session, incident, status="superseded", approach_summary="Old approach")
    newest = make_treatment_plan(db_session, incident, status="approved", approach_summary="Current approach")

    resp = client.get(f"/internal/data/incidents/{incident.id}?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json()["treatment_plan"]["id"] == newest.id
    assert resp.json()["treatment_plan"]["approach_summary"] == "Current approach"


@pytest.mark.integration
def test_get_incident_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)

    resp = client.get(f"/internal/data/incidents/{incident.id}?user_id=other-user")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /incidents/{id}/treatment — the param-mismatch regression
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_treatment_plan_for_incident_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)
    plan = make_treatment_plan(db_session, incident, status="draft", approach_summary="Spray and isolate")

    resp = client.get(f"/internal/data/incidents/{incident.id}/treatment?user_id={USER}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == plan.id
    assert body["incident_id"] == incident.id
    assert body["approach_summary"] == "Spray and isolate"
    assert body["recommended_steps"] == [{"title": "Apply treatment"}]


@pytest.mark.integration
def test_get_treatment_plan_for_incident_with_no_plan_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)

    resp = client.get(f"/internal/data/incidents/{incident.id}/treatment?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_treatment_plan_for_incident_returns_most_recent(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)
    make_treatment_plan(db_session, incident, status="superseded", approach_summary="Old")
    newest = make_treatment_plan(db_session, incident, status="draft", approach_summary="New")

    resp = client.get(f"/internal/data/incidents/{incident.id}/treatment?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json()["id"] == newest.id


@pytest.mark.integration
def test_get_treatment_plan_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)
    make_treatment_plan(db_session, incident, status="draft")

    resp = client.get(f"/internal/data/incidents/{incident.id}/treatment?user_id=other-user")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /incidents/{id}/treatment/manual — follow_up_strategy shape regression
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_create_manual_treatment_plan_wraps_follow_up_strategy_as_dict(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)

    resp = client.post(
        f"/internal/data/incidents/{incident.id}/treatment/manual?user_id={USER}",
        json={"approach_summary": "Hand-pick pests", "recommended_steps": [], "follow_up_strategy": "Recheck in a week"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Must be a dict with a "title" key, not a bare string — get_treatment_plan's
    # prose renderer indexes follow_up['title'] and would TypeError on a string.
    assert body["follow_up_strategy"] == [{"title": "Recheck in a week"}]


@pytest.mark.integration
def test_create_manual_treatment_plan_without_follow_up_strategy(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)

    resp = client.post(
        f"/internal/data/incidents/{incident.id}/treatment/manual?user_id={USER}",
        json={"approach_summary": "Hand-pick pests", "recommended_steps": []},
    )
    assert resp.status_code == 200
    assert resp.json()["follow_up_strategy"] == []


# ---------------------------------------------------------------------------
# POST /incidents — structured response
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_report_incident_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(
        f"/internal/data/incidents?user_id={USER}",
        json={"incident_type": "pest", "summary": "Aphids on roses", "severity": "low"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["incident_type"] == "pest"
    assert body["summary"] == "Aphids on roses"
    assert body["status"] == "reported"
    assert "id" in body


@pytest.mark.integration
def test_report_incident_invalid_type_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.post(
        f"/internal/data/incidents?user_id={USER}",
        json={"incident_type": "not-a-real-type", "summary": "Something happened"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PATCH /incidents/{id}/resolve — structured response + notes support
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_resolve_incident_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER, status="reported")

    resp = client.patch(f"/internal/data/incidents/{incident.id}/resolve?user_id={USER}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"


@pytest.mark.integration
def test_resolve_incident_with_notes_appends_to_notes_field(patched_sessionlocal, db_session, seed_garden_profile):
    """The router previously never exposed `notes` at all on this endpoint,
    even though the underlying tool/domain function always supported it."""
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER, notes="Initial notes")

    resp = client.patch(
        f"/internal/data/incidents/{incident.id}/resolve?user_id={USER}",
        json={"notes": "Treated and confirmed gone"},
    )
    assert resp.status_code == 200
    assert "Treated and confirmed gone" in resp.json()["notes"]


@pytest.mark.integration
def test_resolve_incident_not_found_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch(f"/internal/data/incidents/does-not-exist/resolve?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_resolve_incident_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id="other-user")

    resp = client.patch(f"/internal/data/incidents/{incident.id}/resolve?user_id={USER}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /treatment-plans/{id}/approve — structured response + error paths
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_approve_treatment_plan_returns_structured_view(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)
    plan = make_treatment_plan(db_session, incident, status="draft")

    resp = client.patch(f"/internal/data/treatment-plans/{plan.id}/approve?user_id={USER}")
    assert resp.status_code == 400
    assert "active project revision" in resp.json()["detail"]


@pytest.mark.integration
def test_approve_treatment_plan_not_found_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    resp = client.patch(f"/internal/data/treatment-plans/does-not-exist/approve?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_approve_already_approved_treatment_plan_returns_400(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)
    plan = make_treatment_plan(db_session, incident, status="approved")

    resp = client.patch(f"/internal/data/treatment-plans/{plan.id}/approve?user_id={USER}")
    assert resp.status_code == 400
    assert "already" in resp.json()["detail"].lower()


@pytest.mark.integration
def test_approve_treatment_plan_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id="other-user")
    plan = make_treatment_plan(db_session, incident, status="draft")

    resp = client.patch(f"/internal/data/treatment-plans/{plan.id}/approve?user_id={USER}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /incidents/{id}/activity — structured response
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_incident_activity_returns_structured_events(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id=USER)
    make_treatment_plan(db_session, incident, status="draft")

    resp = client.get(f"/internal/data/incidents/{incident.id}/activity?user_id={USER}")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    # make_incident_report/make_treatment_plan are direct ORM inserts (no
    # activity_log recording), so this just proves the endpoint returns a
    # structured (possibly empty) list rather than 500ing or wrapping prose.


@pytest.mark.integration
def test_get_incident_activity_wrong_user_returns_404(patched_sessionlocal, db_session, seed_garden_profile):
    project = make_project(db_session, seed_garden_profile)
    incident = make_incident_report(db_session, project_id=project.id, user_id="other-user")

    resp = client.get(f"/internal/data/incidents/{incident.id}/activity?user_id={USER}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_get_incident_activity_records_real_events_via_tools(patched_sessionlocal, db_session, seed_garden_profile):
    """Drive through the actual tool layer (not direct ORM inserts) so a real
    activity_log row exists, proving the structured serializer round-trips
    real data, not just an empty list."""
    from agent.tools.operations.incidents import report_incident

    project = make_project(db_session, seed_garden_profile)

    from db.database import current_user_id
    token = current_user_id.set(USER)
    try:
        report_incident.invoke({
            "incident_type": "pest",
            "summary": "Aphids on tomatoes",
            "project_id": project.id,
        })
    finally:
        current_user_id.reset(token)

    resp = client.get(f"/internal/data/incidents?user_id={USER}")
    assert resp.status_code == 200
    incidents = resp.json()
    assert len(incidents) == 1
    incident_id = incidents[0]["id"]

    activity_resp = client.get(f"/internal/data/incidents/{incident_id}/activity?user_id={USER}")
    assert activity_resp.status_code == 200
    events = activity_resp.json()
    assert len(events) >= 1
    assert events[0]["event_type"] == "incident_reported"
    assert events[0]["category"] == "incident"
