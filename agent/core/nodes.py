# nodes.py
from datetime import datetime, timezone as dt_timezone
from typing import Any

from langchain.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END
from langgraph.types import interrupt
from langchain.messages import AIMessage

from agent.domain.interactions import (
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
from langchain_core.runnables import RunnableConfig
from agent.core.model import get_model
from agent.core.telemetry import emit_state_snapshot, emit_tool_completed, emit_tool_started, start_span
from db.database import current_user_id
from agent.core.state import GardenState
from agent.core.temporal import DEFAULT_TIMEZONE, build_temporal_context, infer_session_context
from agent.domain.triage import build_triage_snapshot, format_triage_snapshot
from agent.tools import tools, tools_by_name
from agent.domain.weather import get_latest_weather_snapshot
from db.database import SessionLocal
from db.models import GardenProfile, InteractionRecord, MonitorAlert, Thread, TreatmentPlan

# None at module level — tests patch this directly; production builds it lazily in llm_call
model_with_tools = None

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

{alert_section}Latest weather:
{weather_context}

Latest triage:
{triage_context}

Recent structured interactions:
{interaction_context}

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
- If a plant problem is already being tracked, do not report a duplicate incident, draft a duplicate treatment plan, or
  call approve_treatment_plan again for an already-approved plan. Reuse the existing plan or show the related tasks.
- If the user asks for their task list, pending work, or what to do next, use task tools like list_project_tasks,
  list_due_tasks, get_task, explain_task_blockers, or list_blocked_tasks. Do not report a new incident or open a
  treatment-plan approval flow unless the user is explicitly asking to create or approve treatment work.
- When you use task tools like get_task, start_task, complete_task, skip_task, defer_task, or update_task, always use the
  exact task id returned by task-listing tools. Do not pass a task title as task_id unless the tool explicitly says that
  exact-title fallback is supported.
"""


def _monitor_alerts_text(state: GardenState) -> str:
    alerts = state.get("monitor_alerts") or []
    if not alerts:
        return ""
    lines = [f"⚠ {a['severity'].upper()}: {a['title']}\n  {a['body']}" for a in alerts]
    return "\n".join(lines)


def _interaction_context_text(state: GardenState) -> str:
    history = state.get("interaction_history") or []
    if not history:
        return "No recent structured interactions."
    lines = []
    for item in history[-5:]:
        lines.append(
            f"- {item.get('interaction_type', 'interaction')}: "
            f"status={item.get('status', 'unknown')}, "
            f"resolution={item.get('resolution_action', 'none')}"
        )
    return "\n".join(lines)


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


def session_context_intake(state: GardenState, config: RunnableConfig):
    configurable = config.get("configurable") or {}
    # Default to 1 for local CLI dev. The FastAPI layer always provides user_id
    # from the verified JWT; the CLI provides it via make_session_config().
    uid = int(configurable.get("user_id", 1))
    thread_id = configurable.get("thread_id", "")
    current_user_id.set(uid)

    opener = ""
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            opener = _message_text(message)
            break
    if not opener:
        opener = state.get("startup_opener") or ""

    session = SessionLocal()
    try:
        temporal_context = build_temporal_context(session, timezone=DEFAULT_TIMEZONE)
        session_context = infer_session_context(session, opener or "", timezone=DEFAULT_TIMEZONE)
        now = datetime.now(dt_timezone.utc).replace(tzinfo=None)

        # Upsert thread metadata — preview from last AI message in prior turns
        if thread_id:
            _upsert_thread(session, uid, thread_id, state, now)

        alert_rows = (
            session.query(MonitorAlert)
            .filter(
                MonitorAlert.user_id == uid,
                MonitorAlert.status == "pending",
                MonitorAlert.expires_at > now,
                MonitorAlert.severity.in_(["critical", "high"]),
            )
            .order_by(MonitorAlert.created_at.desc())
            .limit(5)
            .all()
        )
        monitor_alerts = [
            {
                "id": a.id,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "title": a.title,
                "body": a.body,
                "created_at": a.created_at.isoformat(),
            }
            for a in alert_rows
        ]
        return {
            "temporal_context": temporal_context,
            "session_context": session_context,
            "skip_tool_node": False,
            "user_id": uid,
            "monitor_alerts": monitor_alerts,
        }
    finally:
        session.close()


def _upsert_thread(session, user_id: int, thread_id: str, state: GardenState, now) -> None:
    """Create or update thread metadata at the start of each turn."""
    # Extract preview from the last AI message in prior turns
    preview = None
    human_count = 0
    for msg in state.get("messages", []):
        if hasattr(msg, "type"):
            if msg.type == "human":
                human_count += 1
            elif msg.type == "ai" and msg.content:
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                preview = content[:150]

    existing = session.query(Thread).filter(Thread.id == thread_id).first()
    if existing:
        existing.last_active_at = now
        existing.message_count = human_count
        if preview:
            existing.last_message_preview = preview
        # Auto-set title from first human message if still unset
        if not existing.title and human_count > 0:
            for msg in state.get("messages", []):
                if hasattr(msg, "type") and msg.type == "human" and msg.content:
                    text = msg.content if isinstance(msg.content, str) else str(msg.content)
                    existing.title = text[:60] + ("..." if len(text) > 60 else "")
                    break
    else:
        # First turn — create the thread record
        title = None
        if opener := next(
            (msg.content for msg in state.get("messages", [])
             if hasattr(msg, "type") and msg.type == "human" and msg.content),
            None
        ):
            text = opener if isinstance(opener, str) else str(opener)
            title = text[:60] + ("..." if len(text) > 60 else "")
        session.add(Thread(
            id=thread_id,
            user_id=user_id,
            title=title,
            last_active_at=now,
            message_count=human_count,
            created_at=now,
        ))
    session.commit()


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
    if state.get("triage_snapshot"):
        return {}

    opener = ""
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            opener = _message_text(message)
            break
    if not opener:
        opener = state.get("startup_opener") or ""

    session = SessionLocal()
    try:
        snapshot = build_triage_snapshot(session, opener=opener or "hi", timezone=DEFAULT_TIMEZONE)
        emit_state_snapshot(
            "triage_snapshot",
            payload={
                "snapshot_id": snapshot.id,
                "urgent_count": len(snapshot.urgent_task_ids or []),
                "recommended_count": len(snapshot.recommended_task_ids or []),
            },
            tags=["triage"],
        )
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


def should_enter_llm_after_triage(state: GardenState):
    if state.get("messages"):
        return "llm_call"
    return END

def llm_call(state: GardenState, config: RunnableConfig):
    """Always loads fresh profile from DB before building the system prompt."""
    profile_obj = None
    session = SessionLocal()
    try:
        profile_obj = session.query(GardenProfile).filter(
            GardenProfile.user_id == current_user_id.get()
        ).first()
    except Exception as e:
        print(f"[DEBUG] Failed to load garden profile: {e}")
    finally:
        session.close()

    profile_text = profile_obj.to_detailed() if profile_obj else "No garden profile found."
    temporal_text = state.get("temporal_context") or {"current_date": "unknown", "timezone": DEFAULT_TIMEZONE}
    weather_text = state.get("weather_context") or {"alerts_summary": "No weather snapshot available."}
    triage_text = (state.get("triage_snapshot") or {}).get("formatted") or "No triage snapshot available."
    interaction_text = _interaction_context_text(state)
    alerts_text = _monitor_alerts_text(state)
    alert_section = f"⚠ Active monitor alerts:\n{alerts_text}\n\n" if alerts_text else ""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        garden_profile=profile_text,
        temporal_context=temporal_text,
        alert_section=alert_section,
        weather_context=weather_text,
        triage_context=triage_text,
        interaction_context=interaction_text,
    )
    mtw = model_with_tools or get_model(config).bind_tools(tools)
    with start_span("rhizome.llm_call", {"rhizome.model": "primary"}):
        response = mtw.invoke(
            [SystemMessage(content=system_prompt)] + state["messages"]
        )
    return {"messages": [response]}

def tool_node(state: GardenState):
    """Performs the tool call"""

    result = []
    for tool_call in state["messages"][-1].tool_calls:
        tool_name = tool_call["name"]
        tool = tools_by_name.get(tool_name)
        if tool is None:
            available = ", ".join(sorted(tools_by_name))
            observation = (
                f"Unknown tool '{tool_name}'. "
                f"Use one of the registered tools instead: {available}"
            )
            emit_tool_completed(tool_name, success=False, error="unknown tool")
        else:
            emit_tool_started(tool_name, payload={"args": tool_call["args"]})
            try:
                observation = tool.invoke(tool_call["args"])
                emit_tool_completed(tool_name, success=True)
            except Exception as e:
                observation = f"Tool '{tool_name}' raised an unexpected error: {e}"
                emit_tool_completed(tool_name, success=False, error=str(e))
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
            plan = session.query(TreatmentPlan).filter(TreatmentPlan.id == source_id).first()
            if not plan:
                return {
                    "messages": [AIMessage(content=f"No treatment plan found with id {source_id}.")],
                    "pending_interaction": None,
                }
            if plan.status != "draft":
                return {
                    "messages": [
                        AIMessage(
                            content=(
                                f"Treatment plan {source_id} is already {plan.status}. "
                                "Use the existing treatment tasks or review the plan instead of approving it again."
                            )
                        )
                    ],
                    "pending_interaction": None,
                }
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

        emit_state_snapshot(
            "interaction_requested",
            payload={
                "source_type": source_type,
                "interaction_type": envelope.get("interaction_type"),
            },
            tags=["interaction"],
        )
        resolution = normalize_resolution(interrupt(envelope))
        emit_state_snapshot(
            "interaction_resolved",
            payload={
                "source_type": source_type,
                "action_id": resolution.action_id,
            },
            tags=["interaction"],
        )
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
                    "skip_tool_node": True,
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
                "skip_tool_node": False,
            }

        if interactive_call["name"] == "accept_project_proposal":
            if action_id == "accept_proposal":
                result = tools_by_name[interactive_call["name"]].invoke(interactive_call["args"])
                success = not str(result).startswith("Failed")
                resolve_interaction_record(
                    session,
                    record,
                    action_id=action_id,
                    resolution_summary=result if success else f"Approval failed: {result}",
                )
                session.commit()
                return {
                    "messages": [AIMessage(content=result)],
                    "pending_interaction": None,
                    "interaction_history": _interaction_record_to_history(record),
                    "skip_tool_node": True,
                }
            summary = "Revision requested." if action_id == "request_revision" else "Proposal not accepted."
            resolve_interaction_record(session, record, action_id=action_id, resolution_summary=summary)
            session.commit()
            return {
                "messages": [AIMessage(content=summary)],
                "pending_interaction": None,
                "interaction_history": _interaction_record_to_history(record),
                "skip_tool_node": True,
            }

        if interactive_call["name"] == "approve_treatment_plan":
            if action_id == "approve_treatment_plan":
                result = tools_by_name[interactive_call["name"]].invoke(interactive_call["args"])
                success = not str(result).startswith("Failed")
                resolve_interaction_record(
                    session,
                    record,
                    action_id=action_id,
                    resolution_summary=result if success else f"Approval failed: {result}",
                )
                session.commit()
                return {
                    "messages": [AIMessage(content=result)],
                    "pending_interaction": None,
                    "interaction_history": _interaction_record_to_history(record),
                    "skip_tool_node": True,
                }
            summary = "Revision requested." if action_id == "revise_treatment_plan" else "Treatment plan not approved."
            resolve_interaction_record(session, record, action_id=action_id, resolution_summary=summary)
            session.commit()
            return {
                "messages": [AIMessage(content=summary)],
                "pending_interaction": None,
                "interaction_history": _interaction_record_to_history(record),
                "skip_tool_node": True,
            }

        if interactive_call["name"] == "approve_weather_task_changes":
            if action_id == "approve_changes":
                result = tools_by_name[interactive_call["name"]].invoke(interactive_call["args"])
                success = not str(result).startswith("Failed")
                resolve_interaction_record(
                    session,
                    record,
                    action_id=action_id,
                    resolution_summary=result if success else f"Approval failed: {result}",
                )
                session.commit()
                return {
                    "messages": [AIMessage(content=result)],
                    "pending_interaction": None,
                    "interaction_history": _interaction_record_to_history(record),
                    "skip_tool_node": True,
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
                "skip_tool_node": True,
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


def should_continue_after_interaction(state: GardenState) -> str:
    if state.get("skip_tool_node"):
        return END
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tool_node"
    return END
