# nodes.py
from typing import Any

from langchain.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END
from langgraph.types import interrupt
from langchain.messages import AIMessage

from agent.interactions import (
    build_confirmation_interaction,
    build_proposal_review_interaction,
    find_pending_interaction_record,
    rebuild_envelope_from_record,
    build_treatment_plan_review_interaction,
    build_triage_view_interaction,
    build_weather_change_review_interaction,
    normalize_resolution,
    record_interaction_summary,
    resolve_interaction_record,
    stable_confirmation_source_id,
)
from agent.model import model
from agent.state import GardenState
from agent.temporal import DEFAULT_TIMEZONE, build_temporal_context, infer_session_context
from agent.triage import build_triage_snapshot, format_triage_snapshot
from agent.tools import tools, tools_by_name
from agent.weather import get_latest_weather_snapshot
from db.database import SessionLocal
from db.models import GardenProfile, InteractionRecord

model_with_tools = model.bind_tools(tools)

DESTRUCTIVE_TOOLS = {
    "delete_project", "delete_bed", "delete_plant", "remove_container",
    "delete_batch", "remove_plant", "batch_remove_plants"
}
INTERACTION_REVIEW_TOOLS = {
    "accept_project_proposal": "proposal_review",
    "approve_treatment_plan": "treatment_plan_review",
    "approve_weather_task_changes": "weather_change_review",
}

SYSTEM_PROMPT_TEMPLATE = """You are Rhizome, a knowledgeable and practical gardening assistant.

You know this specific garden well:

{garden_profile}

Session time context:
{temporal_context}

Latest weather:
{weather_context}

Latest triage:
{triage_context}

Guidelines:
- Always ground your advice in the specific conditions of this garden
- Never recommend plants that are toxic to dogs or children — flag this immediately if the user asks about one
- Prefer organic solutions: manual pest removal, neem oil, companion planting before anything chemical
- Be cost-conscious: suggest seeds over starter plants, propagation over buying, DIY over purchasing where sensible
- Be honest about what won't work in zone 9b or in the specific conditions of each bed
- Ask for photos or more description when you need them to give good advice
- Before calling any delete tool (delete_project, delete_bed, delete_plant, delete_batch, remove_container, remove_plant, 
  batch_remove_plants), always confirm with the user first by describing exactly what will be deleted and asking them to 
  confirm. Only call the delete tool after the user explicitly confirms.
- Before creating a new batch or project, check whether a similar one already exists using list_batches or list_projects 
  first.
"""


def _message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)


def session_context_intake(state: GardenState):
    opener = ""
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            opener = _message_text(message)
            break

    session = SessionLocal()
    try:
        temporal_context = build_temporal_context(session, timezone=DEFAULT_TIMEZONE)
        session_context = infer_session_context(session, opener or "", timezone=DEFAULT_TIMEZONE)
        return {
            "temporal_context": temporal_context,
            "session_context": session_context,
        }
    finally:
        session.close()


def weather_context_loader(state: GardenState):
    session = SessionLocal()
    try:
        snapshot = get_latest_weather_snapshot(session)
        if snapshot:
            return {
                "weather_context": {
                    "id": snapshot.id,
                    "created_at": snapshot.created_at.isoformat(),
                    "location_label": snapshot.location_label,
                    "conditions_summary": snapshot.conditions_summary,
                    "alerts_summary": snapshot.alerts_summary,
                    "derived_impacts": snapshot.derived_impacts or [],
                }
            }
        return {
            "weather_context": {
                "id": None,
                "created_at": None,
                "location_label": "not configured",
                "conditions_summary": "Weather unavailable.",
                "alerts_summary": "No weather snapshot available.",
                "derived_impacts": [],
            }
        }
    except Exception:
        session.rollback()
        return {
            "weather_context": {
                "id": None,
                "created_at": None,
                "location_label": "unavailable",
                "conditions_summary": "Weather unavailable.",
                "alerts_summary": "No weather snapshot available.",
                "derived_impacts": [],
            }
        }
    finally:
        session.close()


def triage_reasoner(state: GardenState):
    opener = ""
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            opener = _message_text(message)
            break

    session = SessionLocal()
    try:
        snapshot = build_triage_snapshot(session, opener=opener or "hi", timezone=DEFAULT_TIMEZONE)
        triage_interaction = build_triage_view_interaction(session, snapshot)
        record = record_interaction_summary(
            session,
            triage_interaction,
            source_type="triage",
            source_id=snapshot.id,
            metadata={"triage_snapshot_id": snapshot.id},
        )
        triage_interaction["id"] = record.id
        triage_interaction["context"]["interaction_record_id"] = record.id
        session.commit()
        return {
            "triage_snapshot": {
                "id": snapshot.id,
                "created_at": snapshot.created_at.isoformat(),
                "reasoning_summary": snapshot.reasoning_summary,
                "user_focus_summary": snapshot.user_focus_summary,
                "urgent_task_ids": snapshot.urgent_task_ids,
                "routine_task_ids": snapshot.routine_task_ids,
                "project_task_ids": snapshot.project_task_ids,
                "formatted": format_triage_snapshot(session, snapshot),
            },
            "pending_interaction": triage_interaction,
        }
    except Exception:
        session.rollback()
        return {
            "triage_snapshot": {
                "id": None,
                "created_at": None,
                "reasoning_summary": "Triage unavailable.",
                "user_focus_summary": None,
                "urgent_task_ids": [],
                "routine_task_ids": [],
                "project_task_ids": [],
                "formatted": "No triage snapshot available.",
            },
            "pending_interaction": None,
        }
    finally:
        session.close()

def llm_call(state: GardenState):
    """Always loads fresh profile from DB before building the system prompt."""
    profile_obj = None
    session = SessionLocal()
    try:
        profile_obj = session.query(GardenProfile).filter(
            GardenProfile.user_id == 1
        ).first()
    except Exception as e:
        print(f"[DEBUG] Failed to load garden profile: {e}")
    finally:
        session.close()

    profile_text = profile_obj.to_detailed() if profile_obj else "No garden profile found."
    temporal_text = state.get("temporal_context") or {"current_date": "unknown", "timezone": DEFAULT_TIMEZONE}
    weather_text = state.get("weather_context") or {"alerts_summary": "No weather snapshot available."}
    triage_text = (state.get("triage_snapshot") or {}).get("formatted") or "No triage snapshot available."
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        garden_profile=profile_text,
        temporal_context=temporal_text,
        weather_context=weather_text,
        triage_context=triage_text,
    )
    response = model_with_tools.invoke(
        [SystemMessage(content=system_prompt)] + state["messages"]
    )
    return {"messages": [response]}

def tool_node(state: GardenState):
    """Performs the tool call"""

    result = []
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        result.append(ToolMessage(content=observation, tool_call_id=tool_call["id"]))
    return {"messages": result}

def _interaction_record_to_history(record: InteractionRecord | None) -> list[dict[str, Any]]:
    if not record:
        return []
    return [
        {
            "id": record.id,
            "interaction_type": record.interaction_type,
            "status": record.status,
            "resolution_action": record.resolution_action,
        }
    ]


def _interactive_tool_call(last_message):
    for call in getattr(last_message, "tool_calls", []) or []:
        if call["name"] in INTERACTION_REVIEW_TOOLS:
            return call
    return None


def interaction_node(state: GardenState):
    """Intercepts structured approval/review flows and pauses for a typed interaction resolution."""
    last_message = state["messages"][-1]

    destructive_calls = [
        call for call in last_message.tool_calls
        if call["name"] in DESTRUCTIVE_TOOLS
    ]
    interactive_call = _interactive_tool_call(last_message)

    if not destructive_calls and not interactive_call:
        return {}

    session = SessionLocal()
    try:
        envelope = None
        record = None
        source_type = "confirmation"
        source_id = None
        project_id = None
        metadata = {}

        if destructive_calls:
            source_id = stable_confirmation_source_id(destructive_calls)
            source_type = "confirmation"
            record = find_pending_interaction_record(
                session,
                source_type=source_type,
                source_id=source_id,
                interaction_type="confirmation_request",
            )
            if record:
                envelope = rebuild_envelope_from_record(record)
            else:
                envelope = build_confirmation_interaction(destructive_calls)
            metadata = {"tool_calls": destructive_calls}
        elif interactive_call["name"] == "accept_project_proposal":
            project_id = interactive_call["args"]["project_id"]
            source_id = interactive_call["args"]["proposal_id"]
            source_type = "planner"
            record = find_pending_interaction_record(
                session,
                source_type=source_type,
                source_id=source_id,
                interaction_type="proposal_review",
            )
            envelope = rebuild_envelope_from_record(record) if record else build_proposal_review_interaction(session, project_id, source_id)
            metadata = {"tool_name": interactive_call["name"], "tool_args": interactive_call["args"]}
        elif interactive_call["name"] == "approve_treatment_plan":
            source_type = "incident"
            source_id = interactive_call["args"]["treatment_plan_id"]
            record = find_pending_interaction_record(
                session,
                source_type=source_type,
                source_id=source_id,
                interaction_type="treatment_plan_review",
            )
            envelope = rebuild_envelope_from_record(record) if record else build_treatment_plan_review_interaction(session, source_id)
            metadata = {"tool_name": interactive_call["name"], "tool_args": interactive_call["args"]}
        elif interactive_call["name"] == "approve_weather_task_changes":
            source_type = "weather"
            source_id = interactive_call["args"]["change_set_id"]
            record = find_pending_interaction_record(
                session,
                source_type=source_type,
                source_id=source_id,
                interaction_type="weather_change_review",
            )
            envelope = rebuild_envelope_from_record(record) if record else build_weather_change_review_interaction(session, source_id)
            metadata = {"tool_name": interactive_call["name"], "tool_args": interactive_call["args"]}

        if envelope is None:
            return {}

        record = session.query(InteractionRecord).filter(InteractionRecord.id == envelope["id"]).first()
        if not record:
            record = record_interaction_summary(
                session,
                envelope,
                source_type=source_type,
                source_id=source_id,
                project_id=project_id,
                metadata=metadata,
            )
            envelope["id"] = record.id
            envelope["context"]["interaction_record_id"] = record.id
            session.commit()

        resolution = normalize_resolution(interrupt(envelope))
        action_id = resolution.action_id

        if destructive_calls:
            if action_id != "confirm":
                resolve_interaction_record(
                    session,
                    record,
                    action_id=action_id,
                    resolution_summary="Operation cancelled. No changes were made.",
                )
                session.commit()
                return {
                    "messages": [AIMessage(content="Operation cancelled. No changes were made.")],
                    "pending_interaction": None,
                    "interaction_history": _interaction_record_to_history(record),
                }

            resolve_interaction_record(
                session,
                record,
                action_id=action_id,
                resolution_summary="Destructive operation confirmed.",
            )
            session.commit()
            return {
                "pending_interaction": None,
                "interaction_history": _interaction_record_to_history(record),
            }

        if interactive_call["name"] == "accept_project_proposal":
            if action_id == "accept_proposal":
                resolve_interaction_record(
                    session,
                    record,
                    action_id=action_id,
                    resolution_summary="Proposal approved for acceptance.",
                )
                session.commit()
                return {
                    "pending_interaction": None,
                    "interaction_history": _interaction_record_to_history(record),
                }
            summary = "Revision requested." if action_id == "request_revision" else "Proposal not accepted."
            resolve_interaction_record(session, record, action_id=action_id, resolution_summary=summary)
            session.commit()
            return {
                "messages": [AIMessage(content=summary)],
                "pending_interaction": None,
                "interaction_history": _interaction_record_to_history(record),
            }

        if interactive_call["name"] == "approve_treatment_plan":
            if action_id == "approve_treatment_plan":
                resolve_interaction_record(
                    session,
                    record,
                    action_id=action_id,
                    resolution_summary="Treatment plan approved.",
                )
                session.commit()
                return {
                    "pending_interaction": None,
                    "interaction_history": _interaction_record_to_history(record),
                }
            summary = "Revision requested." if action_id == "revise_treatment_plan" else "Treatment plan not approved."
            resolve_interaction_record(session, record, action_id=action_id, resolution_summary=summary)
            session.commit()
            return {
                "messages": [AIMessage(content=summary)],
                "pending_interaction": None,
                "interaction_history": _interaction_record_to_history(record),
            }

        if interactive_call["name"] == "approve_weather_task_changes":
            if action_id == "approve_changes":
                resolve_interaction_record(
                    session,
                    record,
                    action_id=action_id,
                    resolution_summary="Weather task changes approved.",
                )
                session.commit()
                return {
                    "pending_interaction": None,
                    "interaction_history": _interaction_record_to_history(record),
                }
            resolve_interaction_record(
                session,
                record,
                action_id=action_id,
                resolution_summary="Weather task changes dismissed.",
            )
            session.commit()
            return {
                "messages": [AIMessage(content="Weather task changes dismissed.")],
                "pending_interaction": None,
                "interaction_history": _interaction_record_to_history(record),
            }

        return {}
    finally:
        session.close()


def confirmation_node(state: GardenState):
    return interaction_node(state)

def should_continue(state: GardenState) -> str:
    last_message = state["messages"][-1]
    if not last_message.tool_calls:
        return END
    
    for call in last_message.tool_calls:
        if call["name"] in DESTRUCTIVE_TOOLS or call["name"] in INTERACTION_REVIEW_TOOLS:
            return "interaction_node"
    
    return "tool_node"
