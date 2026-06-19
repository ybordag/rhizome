"""
Agent router  — POST /internal/agent
Data router   — CRUD endpoints under /internal/data/
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent.api.models import (
    AgentRequest,
    AgentResponse,
    DeferTaskRequest,
    ResumeRequest,
    TaskActionRequest,
)
from agent.core.graph import agent
from db.database import SessionLocal, current_user_id
from db.models import MonitorAlert

# ---------------------------------------------------------------------------
# Agent router
# ---------------------------------------------------------------------------

agent_router = APIRouter()


@agent_router.post("/agent", response_model=AgentResponse)
def run_agent(req: AgentRequest):
    """
    Run a LangGraph agent turn.  Cambium calls this for AI operations.
    Returns the agent's text response, or an interaction payload if the
    graph paused for user confirmation.
    """
    config = {
        "configurable": {
            "thread_id": req.thread_id,
            "user_id": int(req.user_id),
            **({"provider": req.provider} if req.provider else {}),
            **({"provider_key": req.provider_key} if req.provider_key else {}),
            **({"model": req.model} if req.model else {}),
        }
    }

    agent.invoke(
        {"messages": [HumanMessage(content=req.message)]},
        config=config,
    )

    state = agent.get_state(config)
    interaction = None

    if state.next:
        interrupts = [i for task in state.tasks for i in task.interrupts]
        if interrupts:
            interaction = interrupts[0].value

    # Extract last AI message text
    ai_messages = [
        m for m in state.values.get("messages", [])
        if hasattr(m, "type") and m.type == "ai"
    ]
    response_text = ai_messages[-1].content if ai_messages else ""

    return AgentResponse(
        thread_id=req.thread_id,
        response=response_text,
        interaction=interaction if isinstance(interaction, dict) else None,
    )


@agent_router.post("/agent/resume", response_model=AgentResponse)
def resume_agent(req: ResumeRequest):
    """Resume a paused graph after user interaction resolution."""
    config = {"configurable": {"thread_id": req.thread_id, "user_id": int(req.user_id)}}
    agent.invoke(Command(resume=req.resolution), config=config)
    state = agent.get_state(config)
    ai_messages = [
        m for m in state.values.get("messages", [])
        if hasattr(m, "type") and m.type == "ai"
    ]
    response_text = ai_messages[-1].content if ai_messages else ""
    return AgentResponse(thread_id=req.thread_id, response=response_text, interaction=None)


@agent_router.post("/agent/stream")
async def stream_agent(req: AgentRequest):
    """
    Stream a LangGraph agent turn via SSE.

    Emits a sequence of typed events:
      data: {"type": "token",       "content": "The "}
      data: {"type": "interaction", "payload": {...}}   # when graph pauses
      data: {"type": "done"}

    Cambium proxies this stream directly to Verdant (text/event-stream).
    Verdant reads tokens with fetch + ReadableStream.
    """
    config = {
        "configurable": {
            "thread_id": req.thread_id,
            "user_id": int(req.user_id),
            **({"provider": req.provider} if req.provider else {}),
            **({"provider_key": req.provider_key} if req.provider_key else {}),
            **({"model": req.model} if req.model else {}),
        }
    }

    async def generate():
        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=req.message)]},
            config=config,
            version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"

        # After stream ends, check for a graph interrupt (interaction node)
        state = agent.get_state(config)
        if state.next:
            interrupts = [i for task in state.tasks for i in task.interrupts]
            if interrupts and isinstance(interrupts[0].value, dict):
                yield f"data: {json.dumps({'type': 'interaction', 'payload': interrupts[0].value})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@agent_router.post("/agent/resume/stream")
async def resume_agent_stream(req: ResumeRequest):
    """
    Resume a paused graph with SSE streaming.
    Same event format as /agent/stream.
    """
    config = {"configurable": {"thread_id": req.thread_id, "user_id": int(req.user_id)}}

    async def generate():
        async for event in agent.astream_events(
            Command(resume=req.resolution),
            config=config,
            version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"

        state = agent.get_state(config)
        if state.next:
            interrupts = [i for task in state.tasks for i in task.interrupts]
            if interrupts and isinstance(interrupts[0].value, dict):
                yield f"data: {json.dumps({'type': 'interaction', 'payload': interrupts[0].value})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Data router — direct SQLAlchemy, no agent overhead
# ---------------------------------------------------------------------------

data_router = APIRouter()


def _set_user(user_id: str) -> int:
    uid = int(user_id)
    current_user_id.set(uid)
    return uid


# --- Alerts ---

@data_router.get("/alerts")
def list_alerts(user_id: str):
    uid = _set_user(user_id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session = SessionLocal()
    try:
        rows = (
            session.query(MonitorAlert)
            .filter(
                MonitorAlert.user_id == uid,
                MonitorAlert.status == "pending",
                MonitorAlert.expires_at > now,
            )
            .order_by(MonitorAlert.severity, MonitorAlert.created_at.desc())
            .all()
        )
        return [
            {
                "id": r.id,
                "alert_type": r.alert_type,
                "severity": r.severity,
                "title": r.title,
                "body": r.body,
                "created_at": r.created_at.isoformat(),
                "expires_at": r.expires_at.isoformat(),
            }
            for r in rows
        ]
    finally:
        session.close()


@data_router.post("/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: str, user_id: str):
    uid = _set_user(user_id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session = SessionLocal()
    try:
        alert = (
            session.query(MonitorAlert)
            .filter(MonitorAlert.id == alert_id, MonitorAlert.user_id == uid)
            .first()
        )
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        alert.status = "dismissed"
        alert.dismissed_at = now
        session.commit()
        return {"status": "dismissed"}
    finally:
        session.close()


# --- Tasks ---

@data_router.get("/tasks")
def list_tasks(user_id: str, project_id: str = None, status: str = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import list_project_tasks
    return {"result": list_project_tasks.invoke({"project_id": project_id or "", "status": status})}


@data_router.get("/tasks/daily")
def daily_tasks(user_id: str, limit: int = 10, project_id: str = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import get_daily_priority_tasks
    return {"result": get_daily_priority_tasks.invoke({"limit": limit, "project_id": project_id})}


@data_router.get("/tasks/{task_id}")
def get_task(task_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.tracker import get_task as _get_task
    return {"result": _get_task.invoke({"task_id": task_id})}


@data_router.post("/tasks/{task_id}/complete")
def complete_task(task_id: str, user_id: str, body: TaskActionRequest = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import complete_task as _complete_task
    return {"result": _complete_task.invoke({"task_id": task_id, "notes": body.notes if body else None})}


@data_router.post("/tasks/{task_id}/skip")
def skip_task(task_id: str, user_id: str, body: TaskActionRequest = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import skip_task as _skip_task
    return {"result": _skip_task.invoke({"task_id": task_id, "notes": body.notes if body else None})}


@data_router.post("/tasks/{task_id}/defer")
def defer_task(task_id: str, user_id: str, body: DeferTaskRequest):
    _set_user(user_id)
    from agent.tools.projects.tracker import defer_task as _defer_task
    return {"result": _defer_task.invoke({"task_id": task_id, "defer_until": body.defer_until, "notes": body.notes})}


# --- Projects ---

@data_router.get("/projects")
def list_projects(user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import list_projects as _list_projects
    return {"result": _list_projects.invoke({})}


@data_router.get("/projects/{project_id}")
def get_project(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import get_project as _get_project
    return {"result": _get_project.invoke({"project_id": project_id})}


@data_router.get("/projects/{project_id}/progress")
def get_project_progress(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import get_project_progress
    return {"result": get_project_progress.invoke({"project_id": project_id})}


@data_router.get("/projects/{project_id}/tasks")
def get_project_tasks(project_id: str, user_id: str, status: str = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import list_project_tasks
    return {"result": list_project_tasks.invoke({"project_id": project_id, "status": status})}


# --- Monitor ---

@data_router.get("/monitor/runs")
def list_monitor_runs(user_id: str, limit: int = 20):
    _set_user(user_id)
    from db.models import MonitorRun
    session = SessionLocal()
    try:
        rows = (
            session.query(MonitorRun)
            .order_by(MonitorRun.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "run_type": r.run_type,
                "status": r.status,
                "summary": r.summary,
                "error": r.error,
                "created_at": r.created_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ]
    finally:
        session.close()


@data_router.get("/monitor/runs/{run_id}")
def get_monitor_run(run_id: str, user_id: str):
    _set_user(user_id)
    from db.models import MonitorRun
    session = SessionLocal()
    try:
        run = session.query(MonitorRun).filter(MonitorRun.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return {
            "id": run.id,
            "run_type": run.run_type,
            "status": run.status,
            "summary": run.summary,
            "error": run.error,
            "created_at": run.created_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
    finally:
        session.close()
