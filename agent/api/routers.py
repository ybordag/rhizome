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
    AssignLocationsRequest,
    CreateProjectRequest,
    DeferTaskRequest,
    ReportIncidentRequest,
    ResumeRequest,
    ResolveInteractionRequest,
    TaskActionRequest,
    UpdateBriefRequest,
    UpdateProjectRequest,
    UpdateTaskRequest,
    UpdateTaskSeriesRequest,
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


@data_router.post("/tasks/{task_id}/start")
def start_task(task_id: str, user_id: str, body: TaskActionRequest = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import start_task as _start_task
    return {"result": _start_task.invoke({"task_id": task_id, "notes": body.notes if body else None})}


@data_router.patch("/tasks/{task_id}")
def update_task(task_id: str, user_id: str, body: UpdateTaskRequest = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import update_task as _update_task
    params = {"task_id": task_id}
    if body:
        params.update({k: v for k, v in body.model_dump().items() if v is not None})
    return {"result": _update_task.invoke(params)}


@data_router.get("/tasks/due")
def list_due_tasks(user_id: str, project_id: str = None, days_ahead: int = 7):
    _set_user(user_id)
    from agent.tools.projects.tracker import list_due_tasks as _list_due_tasks
    return {"result": _list_due_tasks.invoke({"project_id": project_id, "days_ahead": days_ahead})}


@data_router.get("/tasks/blocked")
def list_blocked_tasks(user_id: str, project_id: str = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import list_blocked_tasks as _list_blocked_tasks
    return {"result": _list_blocked_tasks.invoke({"project_id": project_id})}


@data_router.get("/tasks/{task_id}/blockers")
def explain_task_blockers(task_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.tracker import explain_task_blockers as _explain
    return {"result": _explain.invoke({"task_id": task_id})}


@data_router.get("/tasks/{task_id}/activity")
def get_task_activity(task_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.tools.operations.activity import get_task_activity as _get_task_activity
    return {"result": _get_task_activity.invoke({"task_id": task_id, "limit": limit})}


@data_router.post("/tasks/materialize")
def materialize_tasks(user_id: str, project_id: str = None, days_ahead: int = 14):
    _set_user(user_id)
    from agent.tools.projects.tracker import materialize_recurring_tasks
    return {"result": materialize_recurring_tasks.invoke({"project_id": project_id, "days_ahead": days_ahead})}


@data_router.patch("/tasks/series/{series_id}")
def update_task_series(series_id: str, user_id: str, body: UpdateTaskSeriesRequest = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import update_task_series as _update_series
    params = {"series_id": series_id}
    if body:
        params.update({k: v for k, v in body.model_dump().items() if v is not None})
    return {"result": _update_series.invoke(params)}


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


@data_router.post("/projects")
def create_project(user_id: str, body: CreateProjectRequest):
    _set_user(user_id)
    from agent.tools.projects.projects import create_project as _create
    return {"result": _create.invoke(body.model_dump(exclude_none=True))}


@data_router.patch("/projects/{project_id}")
def update_project(project_id: str, user_id: str, body: UpdateProjectRequest = None):
    _set_user(user_id)
    from agent.tools.projects.projects import update_project as _update
    params = {"project_id": project_id}
    if body:
        params.update({k: v for k, v in body.model_dump().items() if v is not None})
    return {"result": _update.invoke(params)}


@data_router.delete("/projects/{project_id}")
def delete_project(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import delete_project as _delete
    return {"result": _delete.invoke({"project_id": project_id})}


@data_router.get("/projects/{project_id}/brief")
def get_project_brief(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.planning import get_project_brief as _get_brief
    return {"result": _get_brief.invoke({"project_id": project_id})}


@data_router.patch("/projects/{project_id}/brief")
def update_project_brief(project_id: str, user_id: str, body: UpdateBriefRequest = None):
    _set_user(user_id)
    from agent.tools.projects.planning import update_project_brief as _update_brief
    params = {"project_id": project_id}
    if body:
        params.update({k: v for k, v in body.model_dump().items() if v is not None})
    return {"result": _update_brief.invoke(params)}


@data_router.get("/projects/{project_id}/proposals")
def list_project_proposals(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.planning import list_project_proposals as _list
    return {"result": _list.invoke({"project_id": project_id})}


@data_router.get("/projects/{project_id}/proposals/{proposal_id}")
def get_project_proposal(project_id: str, proposal_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.planning import get_project_proposal as _get
    return {"result": _get.invoke({"proposal_id": proposal_id})}


@data_router.post("/projects/{project_id}/proposals/{proposal_id}/accept")
def accept_project_proposal(project_id: str, proposal_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.planning import accept_project_proposal as _accept
    return {"result": _accept.invoke({"proposal_id": proposal_id})}


@data_router.get("/projects/{project_id}/series")
def list_project_series(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.tracker import list_task_series
    return {"result": list_task_series.invoke({"project_id": project_id})}


@data_router.post("/projects/{project_id}/beds/{bed_id}")
def assign_bed(project_id: str, bed_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import assign_bed_to_project
    return {"result": assign_bed_to_project.invoke({"project_id": project_id, "bed_id": bed_id})}


@data_router.delete("/projects/{project_id}/beds/{bed_id}")
def unassign_bed(project_id: str, bed_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import unassign_bed_from_project
    return {"result": unassign_bed_from_project.invoke({"project_id": project_id, "bed_id": bed_id})}


@data_router.post("/projects/{project_id}/beds/batch")
def assign_beds_batch(project_id: str, user_id: str, body: AssignLocationsRequest):
    _set_user(user_id)
    from agent.tools.projects.projects import assign_beds_to_project
    return {"result": assign_beds_to_project.invoke({"project_id": project_id, "bed_ids": body.bed_ids or []})}


@data_router.post("/projects/{project_id}/containers/{container_id}")
def assign_container(project_id: str, container_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import assign_container_to_project
    return {"result": assign_container_to_project.invoke({"project_id": project_id, "container_id": container_id})}


@data_router.delete("/projects/{project_id}/containers/{container_id}")
def unassign_container(project_id: str, container_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import unassign_container_from_project
    return {"result": unassign_container_from_project.invoke({"project_id": project_id, "container_id": container_id})}


@data_router.post("/projects/{project_id}/containers/batch")
def assign_containers_batch(project_id: str, user_id: str, body: AssignLocationsRequest):
    _set_user(user_id)
    from agent.tools.projects.projects import assign_containers_to_project
    return {"result": assign_containers_to_project.invoke({"project_id": project_id, "container_ids": body.container_ids or []})}


@data_router.post("/projects/{project_id}/plants/{plant_id}")
def add_plant_to_project(project_id: str, plant_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import add_plant_to_project as _add
    return {"result": _add.invoke({"project_id": project_id, "plant_id": plant_id})}


@data_router.delete("/projects/{project_id}/plants/{plant_id}")
def remove_plant_from_project(project_id: str, plant_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import remove_plant_from_project as _remove
    return {"result": _remove.invoke({"project_id": project_id, "plant_id": plant_id})}


@data_router.get("/projects/{project_id}/activity")
def get_project_activity(
    project_id: str, user_id: str,
    category: str = None, event_type: str = None,
    since: str = None, before_timestamp: str = None, limit: int = 20,
):
    _set_user(user_id)
    from agent.tools.operations.activity import list_project_activity
    return {"result": list_project_activity.invoke({
        "project_id": project_id, "category": category, "event_type": event_type,
        "since": since, "before_timestamp": before_timestamp, "limit": limit,
    })}


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


# ---------------------------------------------------------------------------
# Garden — profile
# ---------------------------------------------------------------------------

@data_router.get("/garden/profile")
def get_garden_profile(user_id: str):
    _set_user(user_id)
    from agent.tools.garden.profile import get_garden_profile as _get
    return {"result": _get.invoke({})}


@data_router.patch("/garden/profile")
def update_garden_profile(user_id: str, body: dict = None):
    _set_user(user_id)
    from agent.tools.garden.profile import update_garden_profile as _update
    return {"result": _update.invoke(body or {})}


# ---------------------------------------------------------------------------
# Garden — beds
# ---------------------------------------------------------------------------

@data_router.get("/garden/beds")
def list_beds(user_id: str):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import list_beds as _list
    return {"result": _list.invoke({})}


@data_router.patch("/garden/beds/{bed_id}")
def update_bed(bed_id: str, user_id: str, body: dict = None):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import update_bed as _update
    return {"result": _update.invoke({"bed_id": bed_id, **(body or {})})}


@data_router.delete("/garden/beds/{bed_id}")
def delete_bed(bed_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import delete_bed as _delete
    return {"result": _delete.invoke({"bed_id": bed_id})}


@data_router.get("/garden/beds/{bed_id}/care/state")
def get_bed_care_state(bed_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.care import get_current_care_state
    return {"result": get_current_care_state.invoke({"subject_type": "bed", "subject_id": bed_id})}


@data_router.get("/garden/beds/{bed_id}/care/history")
def get_bed_care_history(bed_id: str, user_id: str, limit: int = 10):
    _set_user(user_id)
    from agent.tools.operations.care import get_recent_care_history
    return {"result": get_recent_care_history.invoke({"subject_type": "bed", "subject_id": bed_id, "limit": limit})}


@data_router.get("/garden/beds/{bed_id}/activity")
def get_bed_activity(bed_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.tools.operations.activity import get_bed_activity as _get
    return {"result": _get.invoke({"bed_id": bed_id, "limit": limit})}


# ---------------------------------------------------------------------------
# Garden — containers
# ---------------------------------------------------------------------------

@data_router.get("/garden/containers")
def list_containers(user_id: str):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import list_containers as _list
    return {"result": _list.invoke({})}


@data_router.post("/garden/containers")
def add_container(user_id: str, body: dict):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import add_container as _add
    return {"result": _add.invoke(body)}


@data_router.patch("/garden/containers/{container_id}")
def update_container(container_id: str, user_id: str, body: dict = None):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import update_container as _update
    return {"result": _update.invoke({"container_id": container_id, **(body or {})})}


@data_router.delete("/garden/containers/{container_id}")
def remove_container(container_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import remove_container as _remove
    return {"result": _remove.invoke({"container_id": container_id})}


@data_router.get("/garden/containers/{container_id}/care/state")
def get_container_care_state(container_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.care import get_current_care_state
    return {"result": get_current_care_state.invoke({"subject_type": "container", "subject_id": container_id})}


@data_router.get("/garden/containers/{container_id}/care/history")
def get_container_care_history(container_id: str, user_id: str, limit: int = 10):
    _set_user(user_id)
    from agent.tools.operations.care import get_recent_care_history
    return {"result": get_recent_care_history.invoke({"subject_type": "container", "subject_id": container_id, "limit": limit})}


@data_router.get("/garden/containers/{container_id}/activity")
def get_container_activity(container_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.tools.operations.activity import get_container_activity as _get
    return {"result": _get.invoke({"container_id": container_id, "limit": limit})}


# ---------------------------------------------------------------------------
# Garden — plants
# ---------------------------------------------------------------------------

@data_router.get("/garden/plants")
def list_plants(user_id: str, status: str = None, project_id: str = None, batch_id: str = None):
    _set_user(user_id)
    from agent.tools.garden.plants import list_plants as _list
    return {"result": _list.invoke({"status": status, "project_id": project_id, "batch_id": batch_id})}


@data_router.post("/garden/plants")
def add_plant(user_id: str, body: dict):
    _set_user(user_id)
    from agent.tools.garden.plants import add_plant as _add
    return {"result": _add.invoke(body)}


@data_router.patch("/garden/plants/{plant_id}")
def update_plant(plant_id: str, user_id: str, body: dict = None):
    _set_user(user_id)
    from agent.tools.garden.plants import update_plant as _update
    return {"result": _update.invoke({"plant_id": plant_id, **(body or {})})}


@data_router.delete("/garden/plants/{plant_id}")
def remove_plant(plant_id: str, user_id: str, reason: str = None):
    _set_user(user_id)
    from agent.tools.garden.plants import remove_plant as _remove
    return {"result": _remove.invoke({"plant_id": plant_id, "reason": reason or "removed via API"})}


@data_router.post("/garden/plants/batch")
def batch_add_plants(user_id: str, body: dict):
    _set_user(user_id)
    from agent.tools.garden.plants import batch_add_plant_type
    return {"result": batch_add_plant_type.invoke(body)}


@data_router.patch("/garden/plants/batch")
def batch_update_plants(user_id: str, body: dict):
    _set_user(user_id)
    from agent.tools.garden.plants import batch_update_plants as _batch_update
    return {"result": _batch_update.invoke(body)}


@data_router.get("/garden/plants/{plant_id}/care/state")
def get_plant_care_state(plant_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.care import get_current_care_state
    return {"result": get_current_care_state.invoke({"subject_type": "plant", "subject_id": plant_id})}


@data_router.get("/garden/plants/{plant_id}/care/history")
def get_plant_care_history(plant_id: str, user_id: str, limit: int = 10):
    _set_user(user_id)
    from agent.tools.operations.care import get_recent_care_history
    return {"result": get_recent_care_history.invoke({"subject_type": "plant", "subject_id": plant_id, "limit": limit})}


@data_router.get("/garden/plants/{plant_id}/activity")
def get_plant_activity(plant_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.tools.operations.activity import get_plant_activity as _get
    return {"result": _get.invoke({"plant_id": plant_id, "limit": limit})}


# ---------------------------------------------------------------------------
# Garden — batches
# ---------------------------------------------------------------------------

@data_router.get("/garden/batches")
def list_batches(user_id: str):
    _set_user(user_id)
    from agent.tools.garden.plants import list_batches as _list
    return {"result": _list.invoke({})}


@data_router.delete("/garden/batches/{batch_id}")
def delete_batch(batch_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.garden.plants import delete_batch as _delete
    return {"result": _delete.invoke({"batch_id": batch_id})}


@data_router.get("/garden/batches/{batch_id}/activity")
def get_batch_activity(batch_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.tools.operations.activity import get_batch_activity as _get
    return {"result": _get.invoke({"batch_id": batch_id, "limit": limit})}


# ---------------------------------------------------------------------------
# Garden — search
# ---------------------------------------------------------------------------

@data_router.get("/garden/search")
def search_garden(user_id: str, query: str, subject_type: str = None):
    _set_user(user_id)
    from agent.tools.garden.search import search_garden as _search
    return {"result": _search.invoke({"query": query, "subject_type": subject_type})}


@data_router.get("/garden/locations/{location}")
def list_by_location(location: str, user_id: str):
    _set_user(user_id)
    from agent.tools.garden.search import list_by_location as _list
    return {"result": _list.invoke({"location": location})}


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------

@data_router.get("/triage/latest")
def get_triage_snapshot(user_id: str):
    _set_user(user_id)
    from agent.tools.operations.triage import get_latest_triage_snapshot
    return {"result": get_latest_triage_snapshot.invoke({})}


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

@data_router.get("/weather/latest")
def get_weather_snapshot(user_id: str):
    _set_user(user_id)
    from agent.tools.operations.weather import get_latest_weather_snapshot
    return {"result": get_latest_weather_snapshot.invoke({})}


@data_router.post("/weather/refresh")
def refresh_weather(user_id: str):
    _set_user(user_id)
    from agent.tools.operations.weather import refresh_weather_snapshot
    return {"result": refresh_weather_snapshot.invoke({})}


@data_router.get("/weather/tasks/impacted")
def weather_impacted_tasks(user_id: str):
    _set_user(user_id)
    from agent.tools.operations.weather import list_weather_impacted_tasks
    return {"result": list_weather_impacted_tasks.invoke({})}


@data_router.patch("/weather/changesets/{changeset_id}/approve")
def approve_weather_changes(changeset_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.weather import approve_weather_task_changes
    return {"result": approve_weather_task_changes.invoke({"change_set_id": changeset_id})}


# ---------------------------------------------------------------------------
# Incidents & treatment plans
# ---------------------------------------------------------------------------

@data_router.get("/incidents")
def list_incidents(user_id: str, project_id: str = None, status: str = None):
    _set_user(user_id)
    from agent.tools.operations.incidents import list_incidents as _list
    return {"result": _list.invoke({"project_id": project_id, "status": status})}


@data_router.post("/incidents")
def report_incident(user_id: str, body: ReportIncidentRequest):
    _set_user(user_id)
    from agent.tools.operations.incidents import report_incident as _report
    return {"result": _report.invoke(body.model_dump(exclude_none=True))}


@data_router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.incidents import get_incident as _get
    return {"result": _get.invoke({"incident_id": incident_id})}


@data_router.patch("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.incidents import resolve_incident as _resolve
    return {"result": _resolve.invoke({"incident_id": incident_id})}


@data_router.get("/incidents/{incident_id}/treatment")
def get_treatment_plan(incident_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.incidents import get_treatment_plan as _get
    return {"result": _get.invoke({"incident_id": incident_id})}


@data_router.patch("/treatment-plans/{plan_id}/approve")
def approve_treatment_plan(plan_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.incidents import approve_treatment_plan as _approve
    return {"result": _approve.invoke({"treatment_plan_id": plan_id})}


@data_router.get("/incidents/{incident_id}/activity")
def get_incident_activity(incident_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.tools.operations.activity import get_incident_activity as _get
    return {"result": _get.invoke({"incident_id": incident_id, "limit": limit})}


# ---------------------------------------------------------------------------
# Interactions
# ---------------------------------------------------------------------------

@data_router.get("/interactions/pending")
def get_pending_interaction(user_id: str):
    _set_user(user_id)
    from agent.tools.operations.interactions import get_pending_interaction as _get
    return {"result": _get.invoke({})}


@data_router.get("/interactions/recent")
def list_recent_interactions(user_id: str, limit: int = 10):
    _set_user(user_id)
    from agent.tools.operations.interactions import list_recent_interactions as _list
    return {"result": _list.invoke({"limit": limit})}


@data_router.get("/interactions/{interaction_id}")
def get_interaction(interaction_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.interactions import get_interaction_record
    return {"result": get_interaction_record.invoke({"interaction_id": interaction_id})}


@data_router.post("/interactions/{interaction_id}/resolve")
def resolve_interaction(interaction_id: str, user_id: str, body: ResolveInteractionRequest):
    _set_user(user_id)
    from agent.tools.operations.interactions import resolve_interaction as _resolve
    return {"result": _resolve.invoke({"interaction_id": interaction_id, **body.model_dump(exclude_none=True)})}


# ---------------------------------------------------------------------------
# Activity — global feed
# ---------------------------------------------------------------------------

@data_router.get("/activity")
def list_recent_activity(
    user_id: str,
    category: str = None, event_type: str = None,
    since: str = None, before_timestamp: str = None, limit: int = 20,
):
    _set_user(user_id)
    from agent.tools.operations.activity import list_recent_activity as _list
    return {"result": _list.invoke({
        "category": category, "event_type": event_type,
        "since": since, "before_timestamp": before_timestamp, "limit": limit,
    })}
