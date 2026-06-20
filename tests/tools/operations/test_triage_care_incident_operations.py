from __future__ import annotations

import pytest

from agent.tools.operations.incidents import (
    approve_treatment_plan,
    draft_treatment_plan,
    report_incident,
)
from agent.tools.operations.care import get_current_care_state, get_recent_care_history
from agent.tools.projects.tracker import complete_task
from agent.tools.operations.triage import get_latest_triage_snapshot, run_daily_triage
from agent.tools.operations.weather import (
    approve_weather_task_changes,
    draft_weather_task_changes,
    list_weather_impacted_tasks,
)
from db.models import ActivityEvent, GardenProfile, IncidentReport, Plant, Task, TreatmentPlan, WeatherTaskChangeSet
from tests.support.factories import (
    link_plant_to_project,
    make_container,
    make_plant,
    make_profile,
    make_project,
    make_project_brief,
    make_project_proposal,
    make_project_revision,
    make_task,
    make_task_generation_run,
    make_weather_snapshot,
)
from tests.tools.projects.test_task_tracker_tools import _accept_plan
from agent.tools.projects.tracker import generate_project_tasks


@pytest.mark.integration
def test_task_completion_updates_care_state_and_history(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    brief = make_project_brief(db_session, project)
    proposal = make_project_proposal(db_session, project, brief)
    revision = make_project_revision(db_session, project, proposal)
    generation_run = make_task_generation_run(db_session, project=project, revision=revision)
    container = make_container(db_session, profile)
    plant = make_plant(db_session, profile, container=container, name="Tomato")
    link_plant_to_project(db_session, project, plant)
    task = make_task(
        db_session,
        project=project,
        revision=revision,
        generation_run=generation_run,
        title="Water Tomato",
        generator_key="tomato.watering.2026-04-12",
        series_id=None,
        linked_subjects=[
            {"subject_type": "plant", "subject_id": plant.id, "role": "primary"},
            {"subject_type": "container", "subject_id": container.id, "role": "affected"},
        ],
    )

    result = complete_task.invoke({"task_id": task.id, "actual_minutes": 12, "notes": "Watered thoroughly."})
    db_session.expire_all()
    refreshed_plant = db_session.query(Plant).filter(Plant.id == plant.id).one()

    assert "Completed task" in result
    assert refreshed_plant.last_watered_at is not None
    assert "Watered thoroughly." in (refreshed_plant.care_state_notes or "")
    assert db_session.query(ActivityEvent).filter(ActivityEvent.event_type == "plant_watered").count() == 1
    history = get_recent_care_history.invoke({"subject_type": "plant", "subject_id": plant.id, "limit": 5})
    current = get_current_care_state.invoke({"subject_type": "plant", "subject_id": plant.id})
    assert "plant_watered" in history
    assert "last_watered_at" in current


@pytest.mark.integration
def test_triage_uses_weather_snapshot_and_returns_grouped_output(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    generate_project_tasks.invoke({"project_id": project.id})
    make_weather_snapshot(
        db_session,
        derived_impacts=[{"date": "2026-04-14", "impact_type": "heat", "severity": "high", "summary": "Heat stress likely."}],
        alerts_summary="Heat stress likely. (2026-04-14)",
    )

    result = run_daily_triage.invoke({"opener": "I only have 20 minutes and low energy, but I want to work outside."})
    latest = get_latest_triage_snapshot.invoke({})

    assert "Daily triage:" in result
    assert "Routine:" in result or "Project Work:" in result
    assert "Daily triage:" in latest
    assert "Heat stress likely." in result
    assert "Urgent:" not in result
    assert "Urgent:" not in latest


@pytest.mark.integration
def test_triage_only_uses_urgent_for_emergencies(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="start")
    generate_project_tasks.invoke({"project_id": project.id})
    make_weather_snapshot(
        db_session,
        derived_impacts=[
            {"date": "2026-04-14", "impact_type": "heat", "severity": "high", "summary": "Heat stress likely."},
        ],
        alerts_summary="Heat stress likely. (2026-04-14)",
    )

    result = run_daily_triage.invoke({"opener": "I can work outside today and want to focus on the tomato project."})

    assert "Acquire Tomato starts" in result
    assert "Project Work:" in result or "Routine:" in result
    assert "Urgent:" not in result


@pytest.mark.integration
def test_weather_task_changes_are_drafted_then_approved(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    generate_project_tasks.invoke({"project_id": project.id})
    make_weather_snapshot(
        db_session,
        derived_impacts=[{"date": "2026-04-14", "impact_type": "frost", "severity": "high", "summary": "Frost risk."}],
        alerts_summary="Frost risk. (2026-04-14)",
    )

    impacted = list_weather_impacted_tasks.invoke({"project_id": project.id})
    drafted = draft_weather_task_changes.invoke({"project_id": project.id})
    change_set = db_session.query(WeatherTaskChangeSet).order_by(WeatherTaskChangeSet.created_at.desc()).first()
    assert change_set is not None

    before_statuses = {task.id: task.status for task in db_session.query(Task).filter(Task.project_id == project.id).all()}
    approved = approve_weather_task_changes.invoke({"change_set_id": change_set.id})
    db_session.expire_all()
    after_statuses = {task.id: task.status for task in db_session.query(Task).filter(Task.project_id == project.id).all()}

    assert "Weather-impacted tasks:" in impacted or "No weather-impacted tasks found." in impacted
    assert "Drafted weather task changes." in drafted
    assert "Approved weather task changes" in approved
    assert before_statuses != after_statuses or db_session.query(Task).filter(Task.project_id == project.id).count() > len(before_statuses)


@pytest.mark.integration
def test_incident_reporting_and_treatment_workflow_creates_tasks(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    generate_project_tasks.invoke({"project_id": project.id})
    profile = db_session.query(GardenProfile).filter(GardenProfile.id == project.garden_profile_id).one()
    container = make_container(db_session, profile)
    plant = make_plant(db_session, profile, container=container, name="Tomato")
    link_plant_to_project(db_session, project, plant)

    reported = report_incident.invoke(
        {
            "incident_type": "pest",
            "summary": "Aphids on tomato leaves",
            "project_id": project.id,
            "severity": "medium",
            "subjects": [{"subject_type": "plant", "subject_id": plant.id, "role": "affected"}],
        }
    )
    incident = db_session.query(IncidentReport).order_by(IncidentReport.created_at.desc()).first()
    drafted = draft_treatment_plan.invoke({"incident_id": incident.id})
    plan = db_session.query(TreatmentPlan).order_by(TreatmentPlan.created_at.desc()).first()
    approved = approve_treatment_plan.invoke({"treatment_plan_id": plan.id})

    task_titles = {task.title for task in db_session.query(Task).filter(Task.project_id == project.id).all()}

    assert "Recorded pest incident" in reported
    assert "Drafted treatment plan" in drafted
    assert "Approved treatment plan" in approved
    assert any("Inspect affected plants closely" == title or "Apply organic pest treatment" == title for title in task_titles)


@pytest.mark.integration
def test_draft_treatment_plan_reuses_existing_active_plan(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    reported = report_incident.invoke(
        {
            "incident_type": "blight",
            "summary": "Powdery mildew on tomato leaves",
            "project_id": project.id,
            "severity": "medium",
            "subjects": [],
        }
    )
    incident = db_session.query(IncidentReport).order_by(IncidentReport.created_at.desc()).first()

    first = draft_treatment_plan.invoke({"incident_id": incident.id})
    second = draft_treatment_plan.invoke({"incident_id": incident.id})

    plans = db_session.query(TreatmentPlan).filter(TreatmentPlan.incident_id == incident.id).all()
    assert "Recorded blight incident" in reported
    assert len(plans) == 1
    assert plans[0].id in first
    assert plans[0].id in second


# ---------------------------------------------------------------------------
# draft_treatment_plan — job event push (#130)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_draft_treatment_plan_pushes_job_started_and_complete(db_session, patched_sessionlocal):
    from agent.domain import notifications
    from db.database import current_user_id

    current_user_id.set("1")
    queue = notifications.get_or_create_user_queue("1")
    try:
        project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
        reported = report_incident.invoke({
            "incident_type": "pest",
            "summary": "Aphids on tomato leaves",
            "project_id": project.id,
            "severity": "medium",
            "subjects": [],
        })
        incident = db_session.query(IncidentReport).order_by(IncidentReport.created_at.desc()).first()

        draft_treatment_plan.invoke({"incident_id": incident.id})

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        types = [e["type"] for e in events]
        assert "job_started" in types
        assert "job_complete" in types
        started = next(e for e in events if e["type"] == "job_started")
        complete = next(e for e in events if e["type"] == "job_complete")
        assert started["title"] == "Drafting treatment plan"
        assert started["job_id"] == complete["job_id"]
    finally:
        notifications.remove_user_queue("1")


@pytest.mark.integration
def test_draft_treatment_plan_pushes_job_failed_on_error(db_session, patched_sessionlocal, monkeypatch):
    from agent.domain import notifications
    from db.database import current_user_id

    monkeypatch.setattr(
        "agent.tools.operations.incidents.draft_treatment_plan_data",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    current_user_id.set("1")
    queue = notifications.get_or_create_user_queue("1")
    try:
        result = draft_treatment_plan.invoke({"incident_id": "nonexistent"})
        assert "Failed to draft treatment plan" in result

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert events[-1]["type"] == "job_failed"
        assert events[-1]["error"] == "boom"
    finally:
        notifications.remove_user_queue("1")


@pytest.mark.integration
def test_draft_treatment_plan_works_without_active_queue(db_session, patched_sessionlocal):
    """No active queue (no SSE connection) — must not raise."""
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    report_incident.invoke({
        "incident_type": "pest",
        "summary": "Aphids on tomato leaves",
        "project_id": project.id,
        "severity": "medium",
        "subjects": [],
    })
    incident = db_session.query(IncidentReport).order_by(IncidentReport.created_at.desc()).first()
    result = draft_treatment_plan.invoke({"incident_id": incident.id})
    assert "Drafted treatment plan" in result


@pytest.mark.integration
def test_report_incident_reuses_existing_open_incident_for_same_issue(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")

    first = report_incident.invoke(
        {
            "incident_type": "blight",
            "summary": "Powdery mildew on tomato leaves",
            "project_id": project.id,
            "severity": "medium",
            "subjects": [],
        }
    )
    second = report_incident.invoke(
        {
            "incident_type": "blight",
            "summary": "Powdery mildew on tomato leaves",
            "project_id": project.id,
            "severity": "medium",
            "subjects": [],
        }
    )

    incidents = db_session.query(IncidentReport).filter(IncidentReport.project_id == project.id).all()
    assert len(incidents) == 1
    assert incidents[0].id in first
    assert incidents[0].id in second


@pytest.mark.integration
def test_report_incident_infers_project_from_subjects_for_treatment_approval(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    generate_project_tasks.invoke({"project_id": project.id})
    profile = db_session.query(GardenProfile).filter(GardenProfile.id == project.garden_profile_id).one()
    container = make_container(db_session, profile)
    plant = make_plant(db_session, profile, container=container, name="Tomato")
    link_plant_to_project(db_session, project, plant)

    reported = report_incident.invoke(
        {
            "incident_type": "blight",
            "summary": "Powdery mildew suspected on tomato leaves.",
            "severity": "medium",
            "subjects": [{"subject_type": "plant", "subject_id": plant.id, "role": "affected"}],
        }
    )
    incident = db_session.query(IncidentReport).order_by(IncidentReport.created_at.desc()).first()
    drafted = draft_treatment_plan.invoke({"incident_id": incident.id})
    plan = db_session.query(TreatmentPlan).order_by(TreatmentPlan.created_at.desc()).first()
    approved = approve_treatment_plan.invoke({"treatment_plan_id": plan.id})

    db_session.expire_all()
    refreshed_incident = db_session.query(IncidentReport).filter(IncidentReport.id == incident.id).one()
    refreshed_plan = db_session.query(TreatmentPlan).filter(TreatmentPlan.id == plan.id).one()
    incident_tasks = db_session.query(Task).filter(Task.project_id == project.id, Task.generator_key.like("incident.%")).all()

    assert "Recorded blight incident" in reported
    assert refreshed_incident.project_id == project.id
    assert "Drafted treatment plan" in drafted
    assert "Approved treatment plan" in approved
    assert refreshed_plan.status == "approved"
    assert incident_tasks


@pytest.mark.integration
def test_approving_treatment_plan_supersedes_other_draft_plans_for_same_project_issue(db_session, patched_sessionlocal):
    project = _accept_plan(db_session, patched_sessionlocal, propagation_method="seed")
    first = report_incident.invoke(
        {
            "incident_type": "blight",
            "summary": "Powdery mildew on tomato leaves",
            "project_id": project.id,
            "severity": "medium",
            "subjects": [],
        }
    )
    incident = db_session.query(IncidentReport).order_by(IncidentReport.created_at.desc()).first()
    first_plan_msg = draft_treatment_plan.invoke({"incident_id": incident.id})
    first_plan = db_session.query(TreatmentPlan).order_by(TreatmentPlan.created_at.asc()).first()

    duplicate_incident = IncidentReport(
        user_id="1",
        project_id=project.id,
        incident_type="blight",
        status="reported",
        severity="medium",
        summary="Powdery mildew spreading on tomatoes",
        reported_by="user",
    )
    db_session.add(duplicate_incident)
    db_session.commit()
    db_session.refresh(duplicate_incident)
    second_plan_msg = draft_treatment_plan.invoke({"incident_id": duplicate_incident.id})
    second_plan = db_session.query(TreatmentPlan).order_by(TreatmentPlan.created_at.desc()).first()

    approved = approve_treatment_plan.invoke({"treatment_plan_id": second_plan.id})

    db_session.expire_all()
    refreshed_first = db_session.query(TreatmentPlan).filter(TreatmentPlan.id == first_plan.id).one()
    refreshed_second = db_session.query(TreatmentPlan).filter(TreatmentPlan.id == second_plan.id).one()
    assert "Drafted treatment plan" in first_plan_msg
    assert "Drafted treatment plan" in second_plan_msg
    assert "Approved treatment plan" in approved
    assert refreshed_second.status == "approved"
    assert refreshed_first.status == "superseded"
