from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from agent.activity_log import record_create_event, record_update_event, snapshot_model
from db.models import (
    IncidentReport,
    IncidentSubject,
    ProjectRevision,
    Task,
    TaskGenerationRun,
    TreatmentPlan,
)


VALID_INCIDENT_TYPES = {"pest", "blight", "weed"}
VALID_INCIDENT_STATUSES = {"reported", "drafted", "approved", "resolved", "dismissed"}
VALID_TREATMENT_STATUSES = {"draft", "approved", "superseded", "completed"}


def create_incident_report(
    session,
    *,
    project_id: Optional[str],
    incident_type: str,
    severity: Optional[str],
    summary: str,
    notes: Optional[str],
    reported_by: str = "user",
    detected_at: Optional[datetime] = None,
    subjects: list[dict[str, str]] | None = None,
) -> IncidentReport:
    if incident_type not in VALID_INCIDENT_TYPES:
        raise ValueError(f"Invalid incident_type '{incident_type}'. Must be one of: {', '.join(sorted(VALID_INCIDENT_TYPES))}.")
    incident = IncidentReport(
        project_id=project_id,
        incident_type=incident_type,
        status="reported",
        severity=severity,
        summary=summary,
        notes=notes,
        reported_by=reported_by,
        detected_at=detected_at,
    )
    session.add(incident)
    session.flush()
    for subject in subjects or []:
        session.add(
            IncidentSubject(
                incident_id=incident.id,
                subject_type=subject["subject_type"],
                subject_id=subject["subject_id"],
                role=subject.get("role"),
            )
        )
    session.flush()
    record_create_event(
        session,
        event_type="incident_reported",
        category="incident",
        summary=f"Reported {incident_type} incident: {summary}",
        obj=incident,
        project_id=project_id,
        subjects=[{"subject_type": "incident_report", "subject_id": incident.id, "role": "primary"}] + list(subjects or []),
    )
    return incident


def _treatment_steps(incident: IncidentReport) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if incident.incident_type == "pest":
        steps = [
            {"title": "Inspect affected plants closely", "task_type": "maintenance", "days_from_approval": 0},
            {"title": "Apply organic pest treatment", "task_type": "emergency", "days_from_approval": 0},
        ]
        follow_up = [{"title": "Reinspect for pests", "cadence_days": 3, "repeat_count": 3}]
        summary = "Use an organic-first pest treatment plan with short-interval follow-up inspections."
    elif incident.incident_type == "blight":
        steps = [
            {"title": "Remove heavily affected material", "task_type": "emergency", "days_from_approval": 0},
            {"title": "Sanitize tools and improve airflow", "task_type": "maintenance", "days_from_approval": 0},
        ]
        follow_up = [{"title": "Monitor disease spread", "cadence_days": 2, "repeat_count": 4}]
        summary = "Remove affected growth, sanitize equipment, and monitor closely."
    else:
        steps = [
            {"title": "Clear weeds from affected area", "task_type": "maintenance", "days_from_approval": 0},
            {"title": "Add suppression mulch", "task_type": "maintenance", "days_from_approval": 1},
        ]
        follow_up = [{"title": "Check for weed regrowth", "cadence_days": 7, "repeat_count": 3}]
        summary = "Remove weeds promptly and follow with suppression work."
    return steps, follow_up, summary


def draft_treatment_plan(session, incident_id: str) -> TreatmentPlan:
    incident = session.query(IncidentReport).filter(IncidentReport.id == incident_id).first()
    if not incident:
        raise ValueError(f"No incident report found with id {incident_id}.")
    steps, follow_up, summary = _treatment_steps(incident)
    plan = TreatmentPlan(
        incident_id=incident.id,
        status="draft",
        approach_summary=summary,
        recommended_steps=steps,
        follow_up_strategy=follow_up,
        monitoring_notes="Generated from the reported incident; approval required before task creation.",
    )
    session.add(plan)
    session.flush()

    before = snapshot_model(incident)
    incident.status = "drafted"
    record_update_event(
        session,
        event_type="treatment_plan_drafted",
        category="incident",
        summary=f"Drafted a treatment plan for incident '{incident.summary}'.",
        before=before,
        obj=incident,
        project_id=incident.project_id,
        subjects=[{"subject_type": "incident_report", "subject_id": incident.id, "role": "primary"}],
    )
    record_create_event(
        session,
        event_type="treatment_plan_created",
        category="incident",
        summary=f"Created treatment plan for incident '{incident.summary}'.",
        obj=plan,
        project_id=incident.project_id,
        subjects=[{"subject_type": "treatment_plan", "subject_id": plan.id, "role": "primary"}],
    )
    return plan


def _incident_generation_run(session, *, project_id: str, revision_id: str, summary: str) -> TaskGenerationRun:
    run = TaskGenerationRun(
        project_id=project_id,
        revision_id=revision_id,
        run_type="event_followup",
        status="complete",
        summary=summary,
        run_metadata={"source": "incident"},
    )
    session.add(run)
    session.flush()
    record_create_event(
        session,
        event_type="task_generation_run_created",
        category="task",
        summary=summary,
        obj=run,
        project_id=project_id,
        revision_id=revision_id,
        subjects=[{"subject_type": "task_generation_run", "subject_id": run.id, "role": "primary"}],
    )
    return run


def approve_treatment_plan(session, treatment_plan_id: str) -> TreatmentPlan:
    plan = session.query(TreatmentPlan).filter(TreatmentPlan.id == treatment_plan_id).first()
    if not plan:
        raise ValueError(f"No treatment plan found with id {treatment_plan_id}.")
    if plan.status != "draft":
        raise ValueError(f"Treatment plan {treatment_plan_id} is already {plan.status}.")

    incident = session.query(IncidentReport).filter(IncidentReport.id == plan.incident_id).first()
    if not incident:
        raise ValueError("Treatment plan is missing its incident report.")
    if not incident.project_id:
        raise ValueError("Treatment tasks require the incident to be linked to a project.")

    revision = (
        session.query(ProjectRevision)
        .filter(ProjectRevision.project_id == incident.project_id, ProjectRevision.status == "active")
        .order_by(ProjectRevision.revision_number.desc())
        .first()
    )
    if not revision:
        raise ValueError("Treatment task generation requires an active project revision.")

    subjects = session.query(IncidentSubject).filter(IncidentSubject.incident_id == incident.id).all()
    linked_subjects = [
        {"subject_type": subject.subject_type, "subject_id": subject.subject_id, "role": subject.role or "affected"}
        for subject in subjects
    ]
    run = _incident_generation_run(
        session,
        project_id=incident.project_id,
        revision_id=revision.id,
        summary=f"Created treatment tasks for incident '{incident.summary}'.",
    )
    approval_time = datetime.utcnow()

    for step in plan.recommended_steps or []:
        due = approval_time + timedelta(days=int(step.get("days_from_approval", 0) or 0))
        task = Task(
            project_id=incident.project_id,
            revision_id=revision.id,
            generation_run_id=run.id,
            parent_task_id=None,
            series_id=None,
            source_type="generated_override",
            generator_key=f"incident.{incident.incident_type}.{incident.id}.{step['title'].lower().replace(' ', '_')}",
            title=step["title"],
            description=f"Treatment step for incident '{incident.summary}'.",
            type=step.get("task_type", "maintenance"),
            status="pending",
            scheduled_date=due,
            earliest_start=due,
            window_start=due,
            window_end=due + timedelta(days=1),
            deadline=due + timedelta(days=1),
            estimated_minutes=int(step.get("estimated_minutes", 20) or 20),
            reversible=True,
            what_happens_if_skipped="The reported issue may worsen.",
            what_happens_if_delayed="Treatment and recovery may take longer.",
            notes="Created from approved treatment plan.",
            linked_subjects=linked_subjects,
        )
        session.add(task)
        session.flush()
        record_create_event(
            session,
            event_type="task_created",
            category="task",
            summary=f"Created treatment task '{task.title}'.",
            obj=task,
            project_id=incident.project_id,
            revision_id=revision.id,
            metadata={"incident_id": incident.id},
            subjects=[{"subject_type": "task", "subject_id": task.id, "role": "primary"}] + linked_subjects,
        )

    before_plan = snapshot_model(plan)
    plan.status = "approved"
    plan.approved_at = approval_time
    record_update_event(
        session,
        event_type="treatment_plan_approved",
        category="incident",
        summary=f"Approved treatment plan for incident '{incident.summary}'.",
        before=before_plan,
        obj=plan,
        project_id=incident.project_id,
        subjects=[{"subject_type": "treatment_plan", "subject_id": plan.id, "role": "primary"}],
    )

    before_incident = snapshot_model(incident)
    incident.status = "approved"
    record_update_event(
        session,
        event_type="incident_updated",
        category="incident",
        summary=f"Incident '{incident.summary}' is now approved for treatment.",
        before=before_incident,
        obj=incident,
        project_id=incident.project_id,
        subjects=[{"subject_type": "incident_report", "subject_id": incident.id, "role": "primary"}],
    )
    return plan


def resolve_incident(session, incident_id: str, notes: Optional[str] = None) -> IncidentReport:
    incident = session.query(IncidentReport).filter(IncidentReport.id == incident_id).first()
    if not incident:
        raise ValueError(f"No incident report found with id {incident_id}.")
    before = snapshot_model(incident)
    incident.status = "resolved"
    if notes:
        incident.notes = f"{incident.notes}\nResolved: {notes}".strip() if incident.notes else f"Resolved: {notes}"
    record_update_event(
        session,
        event_type="incident_resolved",
        category="incident",
        summary=f"Resolved incident '{incident.summary}'.",
        before=before,
        obj=incident,
        project_id=incident.project_id,
        metadata={"notes": notes},
        subjects=[{"subject_type": "incident_report", "subject_id": incident.id, "role": "primary"}],
    )
    return incident
