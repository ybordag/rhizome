from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from langchain.tools import tool

from agent.domain.incidents import (
    approve_treatment_plan as approve_treatment_plan_data,
    create_incident_report,
    draft_treatment_plan as draft_treatment_plan_data,
    resolve_incident as resolve_incident_data,
)
from agent.domain.notifications import push_event
from db.database import SessionLocal, current_user_id
from db.models import IncidentReport, IncidentSubject, TreatmentPlan


def _parse_optional_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value)


@tool
def list_incidents(project_id: Optional[str] = None, status: Optional[str] = None, limit: int = 20) -> str:
    """List incident reports, optionally filtered by project or status."""
    session = SessionLocal()
    try:
        query = session.query(IncidentReport)
        if project_id:
            query = query.filter(IncidentReport.project_id == project_id)
        if status:
            query = query.filter(IncidentReport.status == status)
        incidents = query.order_by(IncidentReport.created_at.desc()).limit(limit).all()
        if not incidents:
            return "No incidents found."
        lines = ["Incidents:", ""]
        for inc in incidents:
            lines.append(
                f"- [{inc.status}] {inc.incident_type}: {inc.summary}"
                f" | id={inc.id} | severity={inc.severity or 'not set'}"
                f" | {inc.created_at.date().isoformat()}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to list incidents: {str(e)}"
    finally:
        session.close()


@tool
def get_incident(incident_id: str) -> str:
    """Show full details for a specific incident report including subjects and treatment plan status."""
    session = SessionLocal()
    try:
        incident = session.query(IncidentReport).filter(IncidentReport.id == incident_id).first()
        if not incident:
            return f"No incident found with id {incident_id}."
        subjects = (
            session.query(IncidentSubject)
            .filter(IncidentSubject.incident_id == incident_id)
            .all()
        )
        plan = (
            session.query(TreatmentPlan)
            .filter(TreatmentPlan.incident_id == incident_id)
            .order_by(TreatmentPlan.created_at.desc())
            .first()
        )
        lines = [
            f"Incident {incident.id}:",
            f"- Type: {incident.incident_type} | Status: {incident.status}",
            f"- Severity: {incident.severity or 'not set'}",
            f"- Reported by: {incident.reported_by} on {incident.created_at.date().isoformat()}",
            f"- Summary: {incident.summary}",
        ]
        if incident.notes:
            lines.append(f"- Notes: {incident.notes}")
        if subjects:
            lines.append("- Affected:")
            for s in subjects:
                lines.append(f"  - {s.subject_type}: {s.subject_id} ({s.role or 'primary'})")
        if plan:
            lines.append(f"- Treatment plan: {plan.id} [{plan.status}]")
        else:
            lines.append("- Treatment plan: none drafted")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to get incident: {str(e)}"
    finally:
        session.close()


@tool
def report_incident(
    incident_type: str,
    summary: str,
    project_id: Optional[str] = None,
    severity: Optional[str] = None,
    notes: Optional[str] = None,
    reported_by: str = "user",
    detected_at: Optional[str] = None,
    subjects: Optional[list[dict[str, str]]] = None,
) -> str:
    """Record a user-reported pest, blight, or weed incident and link affected objects."""
    session = SessionLocal()
    try:
        incident = create_incident_report(
            session,
            project_id=project_id,
            incident_type=incident_type,
            severity=severity,
            summary=summary,
            notes=notes,
            reported_by=reported_by,
            detected_at=_parse_optional_datetime(detected_at),
            subjects=subjects or [],
        )
        session.commit()
        return f"Recorded {incident.incident_type} incident {incident.id}: {incident.summary}"
    except Exception as e:
        session.rollback()
        return f"Failed to report incident: {str(e)}"
    finally:
        session.close()


@tool
def draft_treatment_plan(incident_id: str) -> str:
    """Draft an approval-gated treatment plan for a reported incident."""
    user_id = current_user_id.get()
    job_id = f"treatment_plan_{uuid.uuid4().hex[:8]}"
    push_event(user_id, {"type": "job_started", "job_id": job_id, "title": "Drafting treatment plan"})

    session = SessionLocal()
    try:
        plan = draft_treatment_plan_data(session, incident_id)
        session.commit()
        result = (
            f"Drafted treatment plan {plan.id}.\n"
            f"- Status: {plan.status}\n"
            f"- Approach: {plan.approach_summary}"
        )
        push_event(user_id, {
            "type": "job_complete", "job_id": job_id,
            "title": "Drafting treatment plan", "summary": f"Drafted plan {plan.id}",
        })
        return result
    except Exception as e:
        session.rollback()
        error = str(e)
        push_event(user_id, {"type": "job_failed", "job_id": job_id, "title": "Drafting treatment plan", "error": error})
        return f"Failed to draft treatment plan: {error}"
    finally:
        session.close()


@tool
def get_treatment_plan(treatment_plan_id: str) -> str:
    """Show a treatment plan and its follow-up strategy."""
    session = SessionLocal()
    try:
        plan = session.query(TreatmentPlan).filter(TreatmentPlan.id == treatment_plan_id).first()
        if not plan:
            return f"No treatment plan found with id {treatment_plan_id}."
        lines = [
            f"Treatment plan {plan.id}:",
            f"- Status: {plan.status}",
            f"- Approach: {plan.approach_summary}",
            "- Recommended steps:",
        ]
        for step in plan.recommended_steps or []:
            lines.append(f"  - {step['title']}")
        lines.append("- Follow-up:")
        for follow_up in plan.follow_up_strategy or []:
            lines.append(f"  - {follow_up['title']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to get treatment plan: {str(e)}"
    finally:
        session.close()


@tool
def approve_treatment_plan(treatment_plan_id: str) -> str:
    """Approve a drafted treatment plan and create treatment tasks."""
    session = SessionLocal()
    try:
        plan = approve_treatment_plan_data(session, treatment_plan_id)
        session.commit()
        return f"Approved treatment plan {plan.id} and created follow-up tasks."
    except Exception as e:
        session.rollback()
        return f"Failed to approve treatment plan: {str(e)}"
    finally:
        session.close()


@tool
def resolve_incident(incident_id: str, notes: Optional[str] = None) -> str:
    """Mark a reported incident as resolved."""
    session = SessionLocal()
    try:
        incident = resolve_incident_data(session, incident_id, notes=notes)
        session.commit()
        return f"Resolved incident {incident.id}."
    except Exception as e:
        session.rollback()
        return f"Failed to resolve incident: {str(e)}"
    finally:
        session.close()
