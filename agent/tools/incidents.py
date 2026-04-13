from __future__ import annotations

from datetime import datetime
from typing import Optional

from langchain.tools import tool

from agent.incidents import (
    approve_treatment_plan as approve_treatment_plan_data,
    create_incident_report,
    draft_treatment_plan as draft_treatment_plan_data,
    resolve_incident as resolve_incident_data,
)
from db.database import SessionLocal
from db.models import IncidentReport, IncidentSubject, TreatmentPlan


def _parse_optional_datetime(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromisoformat(value)


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
    session = SessionLocal()
    try:
        plan = draft_treatment_plan_data(session, incident_id)
        session.commit()
        return (
            f"Drafted treatment plan {plan.id}.\n"
            f"- Status: {plan.status}\n"
            f"- Approach: {plan.approach_summary}"
        )
    except Exception as e:
        session.rollback()
        return f"Failed to draft treatment plan: {str(e)}"
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
