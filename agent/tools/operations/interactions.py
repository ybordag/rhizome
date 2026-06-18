from __future__ import annotations

from typing import Any, Optional

from langchain.tools import tool

from agent.domain.interactions import (
    format_interaction_record,
    get_pending_interaction_record,
    list_recent_interaction_records,
    resolve_interaction_record,
)
from db.database import SessionLocal
from db.models import InteractionRecord, TriageSnapshot


def _load_record(session, interaction_id: str) -> InteractionRecord:
    record = session.query(InteractionRecord).filter(InteractionRecord.id == interaction_id).first()
    if not record:
        raise ValueError(f"No interaction record found with id {interaction_id}.")
    return record


def _resolve_confirmation(record: InteractionRecord, action_id: str) -> str:
    if action_id != "confirm":
        return "Operation cancelled. No changes were made."
    from agent.tools import tools_by_name

    results = []
    for tool_call in (record.record_metadata or {}).get("tool_calls", []):
        tool = tools_by_name[tool_call["name"]]
        results.append(tool.invoke(tool_call.get("args") or {}))
    return "\n".join(results) if results else "No destructive actions were queued."


def _resolve_proposal_review(record: InteractionRecord, action_id: str, inputs: dict[str, Any]) -> str:
    metadata = record.record_metadata or {}
    context = metadata.get("context") or {}
    if action_id == "accept_proposal":
        from agent.tools.projects.planning import accept_project_proposal

        return accept_project_proposal.invoke(
            {"project_id": context["project_id"], "proposal_id": context["proposal_id"]}
        )
    if action_id == "request_revision":
        note = (inputs or {}).get("note")
        return f"Revision requested for proposal {context.get('proposal_id')}.{f' Note: {note}' if note else ''}"
    return f"Proposal {context.get('proposal_id')} was not accepted."


def _resolve_treatment_review(record: InteractionRecord, action_id: str, inputs: dict[str, Any]) -> str:
    treatment_plan_id = ((record.record_metadata or {}).get("context") or {}).get("treatment_plan_id")
    if action_id == "approve_treatment_plan":
        from agent.tools.operations.incidents import approve_treatment_plan

        return approve_treatment_plan.invoke({"treatment_plan_id": treatment_plan_id})
    if action_id == "revise_treatment_plan":
        note = (inputs or {}).get("note")
        return f"Revision requested for treatment plan {treatment_plan_id}.{f' Note: {note}' if note else ''}"
    return f"Treatment plan {treatment_plan_id} was not approved."


def _resolve_weather_review(record: InteractionRecord, action_id: str) -> str:
    change_set_id = ((record.record_metadata or {}).get("context") or {}).get("change_set_id")
    if action_id == "approve_changes":
        from agent.tools.operations.weather import approve_weather_task_changes

        return approve_weather_task_changes.invoke({"change_set_id": change_set_id})
    return f"Dismissed weather task changes for change set {change_set_id}."


def _resolve_triage(record: InteractionRecord, action_id: str, inputs: dict[str, Any]) -> str:
    from agent.tools.projects.tracker import get_task, start_task

    metadata = record.record_metadata or {}
    context = metadata.get("context") or {}
    if action_id == "continue":
        return "Triage noted."
    if action_id == "focus_section":
        section = (inputs or {}).get("section")
        if not section:
            return "focus_section requires a section."
        section_map = {
            "Urgent": context.get("urgent_task_ids") or [],
            "Routine": context.get("routine_task_ids") or [],
            "Project Work": context.get("project_task_ids") or [],
        }
        task_ids = section_map.get(section, [])
        if not task_ids:
            return f"No tasks available in {section}."
        return f"{section} tasks:\n" + "\n".join(f"- {task_id}" for task_id in task_ids)
    if action_id == "show_task_details":
        task_id = (inputs or {}).get("task_id")
        if not task_id:
            return "show_task_details requires a task_id."
        return get_task.invoke({"task_id": task_id})
    if action_id == "start_task":
        task_id = (inputs or {}).get("task_id")
        if not task_id:
            return "start_task requires a task_id."
        return start_task.invoke({"task_id": task_id})
    return "Unsupported triage action."


@tool
def get_pending_interaction() -> str:
    """Show the latest pending structured interaction summary."""
    session = SessionLocal()
    try:
        record = get_pending_interaction_record(session)
        if not record:
            return "No pending interaction found."
        return format_interaction_record(record)
    except Exception as e:
        return f"Failed to load pending interaction: {str(e)}"
    finally:
        session.close()


@tool
def list_recent_interactions(
    limit: int = 20,
    interaction_type: Optional[str] = None,
    project_id: Optional[str] = None,
) -> str:
    """List recent interaction summaries for history or frontend/API use."""
    session = SessionLocal()
    try:
        if limit < 1:
            return "limit must be at least 1."
        records = list_recent_interaction_records(
            session,
            limit=limit,
            interaction_type=interaction_type,
            project_id=project_id,
        )
        if not records:
            return "No interaction records found."
        return "\n\n".join(format_interaction_record(record) for record in records)
    except Exception as e:
        return f"Failed to list interactions: {str(e)}"
    finally:
        session.close()


@tool
def get_interaction_record(interaction_id: str) -> str:
    """Show one persisted interaction summary and its available actions."""
    session = SessionLocal()
    try:
        record = _load_record(session, interaction_id)
        return format_interaction_record(record)
    except Exception as e:
        return f"Failed to load interaction record: {str(e)}"
    finally:
        session.close()


@tool
def resolve_interaction(interaction_id: str, action_id: str, inputs: Optional[dict[str, Any]] = None) -> str:
    """Resolve a pending interaction summary through its action contract."""
    session = SessionLocal()
    try:
        record = _load_record(session, interaction_id)
        if record.status != "pending":
            return f"Interaction {interaction_id} is already {record.status}."

        if record.interaction_type == "confirmation_request":
            result = _resolve_confirmation(record, action_id)
        elif record.interaction_type == "proposal_review":
            result = _resolve_proposal_review(record, action_id, inputs or {})
        elif record.interaction_type == "treatment_plan_review":
            result = _resolve_treatment_review(record, action_id, inputs or {})
        elif record.interaction_type == "weather_change_review":
            result = _resolve_weather_review(record, action_id)
        elif record.interaction_type == "triage_view":
            result = _resolve_triage(record, action_id, inputs or {})
        else:
            return f"Unsupported interaction type '{record.interaction_type}'."

        resolve_interaction_record(
            session,
            record,
            action_id=action_id,
            resolution_summary=result,
        )
        session.commit()
        return result
    except Exception as e:
        session.rollback()
        return f"Failed to resolve interaction: {str(e)}"
    finally:
        session.close()
