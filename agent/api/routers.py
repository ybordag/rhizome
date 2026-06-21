"""
Agent router  — POST /internal/agent
Data router   — CRUD endpoints under /internal/data/
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent.api.models import (
    AgentRequest,
    AgentResponse,
    AssignLocationsRequest,
    BulkTaskUpdateRequest,
    CreateBedRequest,
    CreateCalendarAnnotationRequest,
    CreateManualTreatmentPlanRequest,
    CreateProjectExpenseRequest,
    CreateProjectRequest,
    CreateShoppingItemRequest,
    CreateTaskRequest,
    CreateTaskSeriesRequest,
    CreateThreadRequest,
    DeferTaskRequest,
    RecordCareRequest,
    ReportIncidentRequest,
    ResolveIncidentRequest,
    ResumeRequest,
    ResolveInteractionRequest,
    TaskActionRequest,
    UpdateBriefRequest,
    UpdateCalendarAnnotationRequest,
    UpdateIncidentRequest,
    UpdateProjectExpenseRequest,
    UpdateProjectRequest,
    UpdateSessionContextRequest,
    UpdateShoppingItemRequest,
    UpdateTaskRequest,
    UpdateTaskSeriesRequest,
    UpdateTreatmentPlanRequest,
)
from agent.core.graph import agent
from db.database import SessionLocal, current_user_id
from db.models import (
    Bed, CalendarAnnotation, Container, GardenProfile, GardeningProject,
    IncidentReport, MonitorAlert, Plant, PlantBatch, ProjectBed, ProjectBrief, ProjectContainer,
    ProjectExpense, ProjectPlant, ProjectProposal, ShoppingItem, Task, TaskDependency,
    TaskSeries, Thread, TreatmentPlan,
)
from pydantic import BaseModel as _BaseModel
from sqlalchemy import func, or_

# Heartbeat interval for the notifications SSE stream — module-level so tests
# can monkeypatch it to a tiny value instead of waiting out a real 30s window.
NOTIFICATION_HEARTBEAT_SECONDS = 30.0

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
            "user_id": req.user_id,
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

    # Extract last AI message text. Content may be a plain string or a list of
    # content blocks (multi-modal format used by some providers/models).
    ai_messages = [
        m for m in state.values.get("messages", [])
        if hasattr(m, "type") and m.type == "ai"
    ]
    if ai_messages:
        content = ai_messages[-1].content
        if isinstance(content, list):
            response_text = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            response_text = content if isinstance(content, str) else str(content)
    else:
        response_text = ""

    return AgentResponse(
        thread_id=req.thread_id,
        response=response_text,
        interaction=interaction if isinstance(interaction, dict) else None,
    )


@agent_router.post("/agent/resume", response_model=AgentResponse)
def resume_agent(req: ResumeRequest):
    """Resume a paused graph after user interaction resolution."""
    config = {"configurable": {"thread_id": req.thread_id, "user_id": req.user_id}}
    agent.invoke(Command(resume=req.resolution), config=config)
    state = agent.get_state(config)
    ai_messages = [
        m for m in state.values.get("messages", [])
        if hasattr(m, "type") and m.type == "ai"
    ]
    response_text = ai_messages[-1].content if ai_messages else ""
    return AgentResponse(thread_id=req.thread_id, response=response_text, interaction=None)


def get_streaming_agent(request: Request):
    """Dependency indirection so tests can override this with a graph built
    on a test-scoped async checkpointer (`app.dependency_overrides`) instead
    of the real one built in agent/api/app.py's lifespan — see #141."""
    return request.app.state.streaming_agent


def _is_user_visible_llm_stream_event(event: dict) -> bool:
    """Only expose tokens from the final assistant LLM node.

    `astream_events()` also includes internal chat-model calls, such as the
    triage summary model used while building context. Those are valid graph
    internals but must not be streamed as user-facing assistant text (#142).
    """
    return (
        event.get("event") == "on_chat_model_stream"
        and (event.get("metadata") or {}).get("langgraph_node") == "llm_call"
    )


@agent_router.post("/agent/stream")
async def stream_agent(req: AgentRequest, streaming_agent=Depends(get_streaming_agent)):
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
            "user_id": req.user_id,
            **({"provider": req.provider} if req.provider else {}),
            **({"provider_key": req.provider_key} if req.provider_key else {}),
            **({"model": req.model} if req.model else {}),
        }
    }

    async def generate():
        async for event in streaming_agent.astream_events(
            {"messages": [HumanMessage(content=req.message)]},
            config=config,
            version="v2",
        ):
            if _is_user_visible_llm_stream_event(event):
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"

        # After stream ends, check for a graph interrupt (interaction node).
        # Must use the async accessor — calling the sync .get_state() here
        # would run on the same event loop driving this generator, which the
        # async checkpointer classes explicitly reject (#141).
        state = await streaming_agent.aget_state(config)
        if state.next:
            interrupts = [i for task in state.tasks for i in task.interrupts]
            if interrupts and isinstance(interrupts[0].value, dict):
                yield f"data: {json.dumps({'type': 'interaction', 'payload': interrupts[0].value})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@agent_router.post("/agent/resume/stream")
async def resume_agent_stream(req: ResumeRequest, streaming_agent=Depends(get_streaming_agent)):
    """
    Resume a paused graph with SSE streaming.
    Same event format as /agent/stream.
    """
    config = {"configurable": {"thread_id": req.thread_id, "user_id": req.user_id}}

    async def generate():
        async for event in streaming_agent.astream_events(
            Command(resume=req.resolution),
            config=config,
            version="v2",
        ):
            if _is_user_visible_llm_stream_event(event):
                chunk = event["data"]["chunk"]
                if chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"

        state = await streaming_agent.aget_state(config)
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


def _set_user(user_id: str) -> str:
    current_user_id.set(user_id)
    return user_id


def _would_create_cycle(session, blocking_task_id: str, blocked_task_id: str) -> bool:
    """True if adding (blocking→blocked) would create a dependency cycle.
    BFS from blocked_task_id following blocking direction to see if we reach blocking_task_id.
    """
    visited: set = set()
    queue = [blocked_task_id]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        if current == blocking_task_id:
            return True
        visited.add(current)
        downstream = [bid for (bid,) in session.query(TaskDependency.blocked_task_id)
                      .filter(TaskDependency.blocking_task_id == current).all()]
        queue.extend(downstream)
    return False


def _result_or_404(result) -> dict:
    """Convert tool 'not found' error strings to HTTP 404.

    Tools return human-readable strings when an entity is not found
    (e.g. "No bed found with id abc-123."). The router converts these
    to 404 so callers get proper HTTP semantics.
    """
    if isinstance(result, str):
        lower = result.lower()
        if lower.startswith("no ") or "not found" in lower or "not assigned" in lower:
            raise HTTPException(status_code=404, detail=result)
    return {"result": result}


_UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def _mutation_error_status(result) -> Optional[int]:
    """Classify a tool's string result as an HTTP error status, or None on success.

    Mutation tools return human-readable strings for both success and failure
    (they're read by the LLM, so their return type can't change). The router
    needs to tell the two apart to decide whether to build a structured view
    or raise an HTTPException.
    """
    if not isinstance(result, str):
        return None
    lower = result.lower()
    if re.search(r"\bno [a-z_ ]*found\b", lower) or "not found" in lower or "not assigned" in lower:
        return 404
    if (
        lower.startswith("error")
        or lower.startswith("invalid")
        or lower.startswith("failed")
        or "cannot " in lower
        or "must be" in lower
        or "must contain" in lower
        or "but only" in lower
    ):
        return 400
    return None


def _extract_id_after(result: str, marker: str) -> Optional[str]:
    match = re.search(rf"{re.escape(marker)} ({_UUID_RE})", result)
    return match.group(1) if match else None


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


@data_router.get("/notifications/stream")
async def notification_stream(user_id: str):
    """
    Long-lived SSE stream. Frontend opens once on app mount and keeps it open
    for the session. Emits a heartbeat every 30s when no event is pending.
    """
    from agent.domain.notifications import get_or_create_user_queue, remove_user_queue

    queue = get_or_create_user_queue(user_id)

    async def generate():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=NOTIFICATION_HEARTBEAT_SECONDS)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            remove_user_queue(user_id)

    return StreamingResponse(generate(), media_type="text/event-stream")


@data_router.get("/notifications")
def get_notifications(user_id: str, since: str = None):
    """
    Current-state snapshot — called on app mount and on stream reconnection.
    `since` (ISO datetime, optional) limits alerts/interactions to those
    created after that timestamp.
    """
    from agent.domain.notifications import get_active_jobs
    from db.models import InteractionRecord

    uid = _set_user(user_id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since_dt = datetime.fromisoformat(since).replace(tzinfo=None) if since else None
    session = SessionLocal()
    try:
        alert_query = session.query(MonitorAlert).filter(
            MonitorAlert.user_id == uid,
            MonitorAlert.status == "pending",
            MonitorAlert.expires_at > now,
        )
        if since_dt:
            alert_query = alert_query.filter(MonitorAlert.created_at > since_dt)
        alerts = alert_query.order_by(MonitorAlert.severity, MonitorAlert.created_at.desc()).all()

        interaction_query = session.query(InteractionRecord).filter(
            InteractionRecord.user_id == uid,
            InteractionRecord.status == "pending",
        )
        if since_dt:
            interaction_query = interaction_query.filter(InteractionRecord.created_at > since_dt)
        interactions = interaction_query.order_by(InteractionRecord.created_at.desc()).all()

        return {
            "alerts": [
                {
                    "id": a.id,
                    "alert_type": a.alert_type,
                    "severity": a.severity,
                    "title": a.title,
                    "body": a.body,
                    "created_at": a.created_at.isoformat(),
                    "expires_at": a.expires_at.isoformat(),
                }
                for a in alerts
            ],
            "pending_interactions": [
                {"id": i.id, "title": i.title, "interaction_type": i.interaction_type}
                for i in interactions
            ],
            "active_jobs": get_active_jobs(uid),
        }
    finally:
        session.close()


# --- Tasks ---

@data_router.get("/tasks")
def list_tasks(
    user_id: str, project_id: str = None, status: str = None,
    type: str = None, subject_type: str = None, subject_id: str = None,
):
    _set_user(user_id)
    session = SessionLocal()
    try:
        user_pids = [pid for (pid,) in session.query(GardeningProject.id).filter(
            GardeningProject.user_id == user_id).all()]
        query = session.query(Task).filter(Task.project_id.in_(user_pids))
        if project_id:
            query = query.filter(Task.project_id == project_id)
        if status:
            query = query.filter(Task.status == status)
        else:
            query = query.filter(Task.status != "superseded")
        if type:
            query = query.filter(Task.type == type)
        tasks = query.order_by(Task.deadline.asc(), Task.scheduled_date.asc()).all()
        # linked_subjects is JSON — filter in Python to stay cross-DB compatible
        if subject_type or subject_id:
            def _matches(t):
                for s in (t.linked_subjects or []):
                    if subject_type and s.get("subject_type") != subject_type:
                        continue
                    if subject_id and s.get("subject_id") != subject_id:
                        continue
                    return True
                return False
            tasks = [t for t in tasks if _matches(t)]
        return [t.to_summary_view() for t in tasks]
    finally:
        session.close()


@data_router.post("/tasks")
def create_task(user_id: str, body: CreateTaskRequest):
    _set_user(user_id)
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == body.project_id,
            GardeningProject.user_id == user_id,
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        from datetime import datetime as _dt
        def _parse_date(s):
            return _dt.fromisoformat(s) if s else None
        task = Task(
            project_id=body.project_id,
            source_type="user",
            generator_key="user_direct",
            is_user_modified=True,
            title=body.title,
            type=body.type,
            priority=body.priority or "normal",
            scheduled_date=_parse_date(body.scheduled_date),
            earliest_start=_parse_date(body.earliest_start),
            window_start=_parse_date(body.window_start),
            window_end=_parse_date(body.window_end),
            deadline=_parse_date(body.deadline),
            estimated_minutes=body.estimated_minutes or 0,
            notes=body.notes,
            linked_subjects=body.linked_subjects or [],
            reversible=body.reversible if body.reversible is not None else True,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return task.to_detail_view()
    finally:
        session.close()


@data_router.delete("/tasks/{task_id}")
def delete_task(task_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        user_pids = {pid for (pid,) in session.query(GardeningProject.id).filter(
            GardeningProject.user_id == user_id).all()}
        task = session.query(Task).filter(Task.id == task_id).first()
        if not task or task.project_id not in user_pids:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status == "in_progress":
            raise HTTPException(status_code=400, detail="Cannot delete a task that is in progress. Complete or skip it first.")
        session.delete(task)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


@data_router.get("/tasks/daily")
def daily_tasks(user_id: str, limit: int = 10, project_id: str = None):
    _set_user(user_id)
    from agent.domain.tracker import get_daily_priority_tasks as _domain_daily
    session = SessionLocal()
    try:
        scored = _domain_daily(session, limit=limit, project_id=project_id)
        return [
            row["task"].to_summary_view(
                urgency=row["urgency"],
                blocked=row["blocked"],
                due_date=row["due_date"],
                score=row["score"],
            )
            for row in scored
        ]
    finally:
        session.close()


@data_router.get("/tasks/due")
def list_due_tasks(user_id: str, project_id: str = None, days_ahead: int = 7):
    _set_user(user_id)
    from agent.domain.tracker import build_due_task_view as _domain_due
    session = SessionLocal()
    try:
        rows = _domain_due(session, project_id=project_id, days_ahead=days_ahead)
        return [
            row["task"].to_summary_view(
                urgency=row["urgency"],
                blocked=row["blocked"],
                due_date=row["due_date"],
            )
            for row in rows
        ]
    finally:
        session.close()


@data_router.get("/tasks/blocked")
def list_blocked_tasks(user_id: str, project_id: str = None):
    _set_user(user_id)
    from agent.domain.tracker import build_blocked_task_view as _domain_blocked
    session = SessionLocal()
    try:
        rows = _domain_blocked(session, project_id=project_id)
        return [
            row["task"].to_summary_view(
                urgency=row["urgency"],
                blocked=row["blocked"],
                due_date=row["due_date"],
            )
            for row in rows
        ]
    finally:
        session.close()


@data_router.get("/tasks/{task_id}")
def get_task(task_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        if not task or task.project_id not in [
            pid for (pid,) in session.query(GardeningProject.id).filter(
                GardeningProject.user_id == user_id).all()
        ]:
            raise HTTPException(status_code=404, detail="Task not found")
        return task.to_detail_view()
    finally:
        session.close()


@data_router.post("/tasks/{task_id}/complete")
def complete_task(task_id: str, user_id: str, body: TaskActionRequest = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import complete_task as _complete_task
    return _result_or_404(_complete_task.invoke({"task_id": task_id, "notes": body.notes if body else None}))


@data_router.post("/tasks/{task_id}/skip")
def skip_task(task_id: str, user_id: str, body: TaskActionRequest = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import skip_task as _skip_task
    return _result_or_404(_skip_task.invoke({"task_id": task_id, "notes": body.notes if body else None}))


@data_router.post("/tasks/{task_id}/defer")
def defer_task(task_id: str, user_id: str, body: DeferTaskRequest):
    _set_user(user_id)
    from agent.tools.projects.tracker import defer_task as _defer_task
    return _result_or_404(_defer_task.invoke({"task_id": task_id, "defer_until": body.defer_until, "notes": body.notes}))


@data_router.post("/tasks/{task_id}/start")
def start_task(task_id: str, user_id: str, body: TaskActionRequest = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import start_task as _start_task
    return _result_or_404(_start_task.invoke({"task_id": task_id, "notes": body.notes if body else None}))


@data_router.patch("/tasks/{task_id}")
def update_task(task_id: str, user_id: str, body: UpdateTaskRequest = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import update_task as _update_task
    params = {"task_id": task_id}
    if body:
        params.update({k: v for k, v in body.model_dump().items() if v is not None})
    result = _update_task.invoke(params)
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    session = SessionLocal()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        if not task or task.project_id not in [
            pid for (pid,) in session.query(GardeningProject.id).filter(
                GardeningProject.user_id == user_id).all()
        ]:
            raise HTTPException(status_code=404, detail="Task not found")
        return task.to_detail_view()
    finally:
        session.close()


@data_router.post("/tasks/{task_id}/dependencies")
def add_task_dependency(task_id: str, user_id: str, body: dict):
    _set_user(user_id)
    blocking_task_id = body.get("blocking_task_id")
    if not blocking_task_id:
        raise HTTPException(status_code=400, detail="blocking_task_id is required")
    session = SessionLocal()
    try:
        user_pids = {pid for (pid,) in session.query(GardeningProject.id).filter(
            GardeningProject.user_id == user_id).all()}
        blocked = session.query(Task).filter(Task.id == task_id).first()
        blocking = session.query(Task).filter(Task.id == blocking_task_id).first()
        if not blocked or blocked.project_id not in user_pids:
            raise HTTPException(status_code=404, detail="Task not found")
        if not blocking or blocking.project_id not in user_pids:
            raise HTTPException(status_code=400, detail="Blocking task not found or not owned by user")
        if task_id == blocking_task_id:
            raise HTTPException(status_code=400, detail="A task cannot depend on itself")
        if _would_create_cycle(session, blocking_task_id, task_id):
            raise HTTPException(status_code=400, detail="This dependency would create a cycle")
        existing = session.query(TaskDependency).filter(
            TaskDependency.blocking_task_id == blocking_task_id,
            TaskDependency.blocked_task_id == task_id,
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Dependency already exists")
        dep = TaskDependency(blocking_task_id=blocking_task_id, blocked_task_id=task_id)
        session.add(dep)
        session.commit()
        return {"blocking_task_id": blocking_task_id, "blocked_task_id": task_id}
    finally:
        session.close()


@data_router.delete("/tasks/{task_id}/dependencies/{blocking_task_id}")
def remove_task_dependency(task_id: str, blocking_task_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        user_pids = {pid for (pid,) in session.query(GardeningProject.id).filter(
            GardeningProject.user_id == user_id).all()}
        task = session.query(Task).filter(Task.id == task_id).first()
        if not task or task.project_id not in user_pids:
            raise HTTPException(status_code=404, detail="Task not found")
        dep = session.query(TaskDependency).filter(
            TaskDependency.blocking_task_id == blocking_task_id,
            TaskDependency.blocked_task_id == task_id,
        ).first()
        if not dep:
            raise HTTPException(status_code=404, detail="Dependency not found")
        session.delete(dep)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


@data_router.get("/tasks/{task_id}/blockers")
def explain_task_blockers(task_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.tracker import explain_task_blockers as _explain
    return _result_or_404(_explain.invoke({"task_id": task_id}))


@data_router.get("/tasks/{task_id}/activity")
def get_task_activity(task_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.api.views import ActivityEventView
    from agent.domain.activity_log import activity_events_to_view_data, get_activity_for_subject

    session = SessionLocal()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        if not task or task.project_id not in [
            pid for (pid,) in session.query(GardeningProject.id).filter(
                GardeningProject.user_id == user_id).all()
        ]:
            raise HTTPException(status_code=404, detail="Task not found")
        events = get_activity_for_subject(session, subject_type="task", subject_id=task_id, limit=limit)
        return [ActivityEventView(**data) for data in activity_events_to_view_data(session, events)]
    finally:
        session.close()


@data_router.post("/tasks/materialize")
def materialize_tasks(user_id: str, project_id: str = None, days_ahead: int = 14):
    _set_user(user_id)
    from agent.tools.projects.tracker import materialize_recurring_tasks
    return {"result": materialize_recurring_tasks.invoke({"project_id": project_id, "days_ahead": days_ahead})}


@data_router.post("/tasks/series")
def create_task_series(user_id: str, body: CreateTaskSeriesRequest):
    _set_user(user_id)
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == body.project_id,
            GardeningProject.user_id == user_id,
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        from datetime import datetime as _dt
        series = TaskSeries(
            project_id=body.project_id,
            source_type="user",
            generator_key="user_direct",
            title=body.title_template,
            type=body.type,
            cadence=body.cadence,
            cadence_days=body.window_days,
            default_estimated_minutes=body.estimated_minutes or 0,
            linked_subjects=body.linked_subjects or [],
            start_condition={"date": body.start_date} if body.start_date else {},
            end_condition={"date": body.end_date} if body.end_date else {},
            active=True,
        )
        session.add(series)
        session.commit()
        session.refresh(series)
        return series.to_view()
    finally:
        session.close()


@data_router.delete("/tasks/series/{series_id}")
def delete_task_series(series_id: str, user_id: str, delete_pending_tasks: str = "false"):
    _set_user(user_id)
    session = SessionLocal()
    try:
        user_pids = {pid for (pid,) in session.query(GardeningProject.id).filter(
            GardeningProject.user_id == user_id).all()}
        series = session.query(TaskSeries).filter(TaskSeries.id == series_id).first()
        if not series or series.project_id not in user_pids:
            raise HTTPException(status_code=404, detail="Task series not found")
        if delete_pending_tasks == "true":
            session.query(Task).filter(
                Task.series_id == series_id,
                Task.status.in_(["pending", "deferred"]),
            ).delete(synchronize_session=False)
        session.delete(series)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


@data_router.patch("/tasks/series/{series_id}")
def update_task_series(series_id: str, user_id: str, body: UpdateTaskSeriesRequest = None):
    _set_user(user_id)
    from agent.tools.projects.tracker import update_task_series as _update_series
    params = {"series_id": series_id}
    if body:
        params.update({k: v for k, v in body.model_dump().items() if v is not None})
    result = _update_series.invoke(params)
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    session = SessionLocal()
    try:
        series = session.query(TaskSeries).filter(TaskSeries.id == series_id).first()
        if not series or series.project_id not in [
            pid for (pid,) in session.query(GardeningProject.id).filter(
                GardeningProject.user_id == user_id).all()
        ]:
            raise HTTPException(status_code=404, detail="Task series not found")
        return series.to_view()
    finally:
        session.close()


# --- Projects ---

@data_router.get("/projects")
def list_projects(user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        projects = session.query(GardeningProject).filter(
            GardeningProject.user_id == user_id
        ).order_by(GardeningProject.created_at.desc()).all()
        if not projects:
            return []
        pids = [p.id for p in projects]
        plant_counts = dict(session.query(ProjectPlant.project_id, func.count(ProjectPlant.id))
            .filter(ProjectPlant.project_id.in_(pids), ProjectPlant.removed_at == None)
            .group_by(ProjectPlant.project_id).all())
        bed_counts = dict(session.query(ProjectBed.project_id, func.count(ProjectBed.id))
            .filter(ProjectBed.project_id.in_(pids))
            .group_by(ProjectBed.project_id).all())
        container_counts = dict(session.query(ProjectContainer.project_id, func.count(ProjectContainer.id))
            .filter(ProjectContainer.project_id.in_(pids))
            .group_by(ProjectContainer.project_id).all())
        batch_counts = dict(session.query(PlantBatch.project_id, func.count(PlantBatch.id))
            .filter(PlantBatch.project_id.in_(pids))
            .group_by(PlantBatch.project_id).all())
        return [p.to_summary_view(
            plant_count=plant_counts.get(p.id, 0),
            bed_count=bed_counts.get(p.id, 0),
            container_count=container_counts.get(p.id, 0),
            batch_count=batch_counts.get(p.id, 0),
        ) for p in projects]
    finally:
        session.close()


@data_router.get("/projects/{project_id}")
def get_project(project_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id,
            GardeningProject.user_id == user_id,
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        plant_count = session.query(func.count(ProjectPlant.id)).filter(
            ProjectPlant.project_id == project_id, ProjectPlant.removed_at == None).scalar() or 0
        bed_count = session.query(func.count(ProjectBed.id)).filter(
            ProjectBed.project_id == project_id).scalar() or 0
        container_count = session.query(func.count(ProjectContainer.id)).filter(
            ProjectContainer.project_id == project_id).scalar() or 0
        batch_count = session.query(func.count(PlantBatch.id)).filter(
            PlantBatch.project_id == project_id).scalar() or 0
        return project.to_detail_view(
            plant_count=plant_count, bed_count=bed_count,
            container_count=container_count, batch_count=batch_count,
        )
    finally:
        session.close()


@data_router.get("/projects/{project_id}/progress")
def get_project_progress(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.api.views import ProjectProgressView
    from agent.domain.projects import get_project_progress_data
    session = SessionLocal()
    try:
        data = get_project_progress_data(session, project_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"No project found with id {project_id}.")
        return ProjectProgressView(**data)
    finally:
        session.close()


@data_router.get("/projects/{project_id}/tasks")
def get_project_tasks(project_id: str, user_id: str, status: str = None, include_dependencies: str = None):
    _set_user(user_id)
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id,
            GardeningProject.user_id == user_id,
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        query = session.query(Task).filter(Task.project_id == project_id)
        if status:
            query = query.filter(Task.status == status)
        else:
            query = query.filter(Task.status != "superseded")
        tasks = query.order_by(Task.parent_task_id.asc(), Task.deadline.asc(), Task.scheduled_date.asc()).all()
        task_views = [t.to_summary_view() for t in tasks]
        if include_dependencies == "true":
            task_ids = [t.id for t in tasks]
            edges = [
                {"blocking_task_id": d.blocking_task_id, "blocked_task_id": d.blocked_task_id}
                for d in session.query(TaskDependency).filter(
                    TaskDependency.blocking_task_id.in_(task_ids),
                    TaskDependency.blocked_task_id.in_(task_ids),
                ).all()
            ]
            return {"tasks": task_views, "edges": edges}
        return task_views
    finally:
        session.close()


@data_router.patch("/projects/{project_id}/tasks/bulk")
def bulk_update_project_tasks(project_id: str, user_id: str, body: BulkTaskUpdateRequest):
    _set_user(user_id)
    if len(body.updates) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 tasks per bulk update")
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id,
            GardeningProject.user_id == user_id,
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        from datetime import datetime as _dt
        def _parse(s):
            return _dt.fromisoformat(s) if s else None
        task_ids = [u.task_id for u in body.updates]
        tasks_map = {t.id: t for t in session.query(Task).filter(
            Task.id.in_(task_ids), Task.project_id == project_id).all()}
        # Validate all tasks exist and are editable
        for upd in body.updates:
            t = tasks_map.get(upd.task_id)
            if not t:
                raise HTTPException(status_code=400, detail=f"Task {upd.task_id} not found in project")
            if t.status in ("done", "superseded"):
                raise HTTPException(status_code=400, detail=f"Task {upd.task_id} has status '{t.status}' and cannot be updated")
        # Apply updates
        for upd in body.updates:
            t = tasks_map[upd.task_id]
            if upd.scheduled_date is not None:
                t.scheduled_date = _parse(upd.scheduled_date)
            if upd.window_start is not None:
                t.window_start = _parse(upd.window_start)
            if upd.window_end is not None:
                t.window_end = _parse(upd.window_end)
            if upd.deadline is not None:
                t.deadline = _parse(upd.deadline)
            t.is_user_modified = True
        session.commit()
        return [tasks_map[u.task_id].to_summary_view() for u in body.updates]
    finally:
        session.close()


def _project_detail_view(session, project_id: str, user_id: str):
    project = session.query(GardeningProject).filter(
        GardeningProject.id == project_id,
        GardeningProject.user_id == user_id,
    ).first()
    if not project:
        return None
    plant_count = session.query(func.count(ProjectPlant.id)).filter(
        ProjectPlant.project_id == project_id, ProjectPlant.removed_at == None).scalar() or 0
    bed_count = session.query(func.count(ProjectBed.id)).filter(
        ProjectBed.project_id == project_id).scalar() or 0
    container_count = session.query(func.count(ProjectContainer.id)).filter(
        ProjectContainer.project_id == project_id).scalar() or 0
    batch_count = session.query(func.count(PlantBatch.id)).filter(
        PlantBatch.project_id == project_id).scalar() or 0
    return project.to_detail_view(
        plant_count=plant_count, bed_count=bed_count,
        container_count=container_count, batch_count=batch_count,
    )


def _project_or_404(session, project_id: str, user_id: str):
    project = session.query(GardeningProject).filter(
        GardeningProject.id == project_id,
        GardeningProject.user_id == user_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@data_router.post("/projects")
def create_project(user_id: str, body: CreateProjectRequest):
    _set_user(user_id)
    from agent.api.views import ProjectDetailView
    from agent.tools.projects.projects import create_project as _create
    result = _create.invoke(body.model_dump(exclude_none=True))
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    project_id = _extract_id_after(result, "with id")
    session = SessionLocal()
    try:
        view = _project_detail_view(session, project_id, user_id)
        if not view:
            raise HTTPException(status_code=500, detail="Project was created but could not be re-fetched")
        return ProjectDetailView(**view)
    finally:
        session.close()


@data_router.patch("/projects/{project_id}")
def update_project(project_id: str, user_id: str, body: UpdateProjectRequest = None):
    _set_user(user_id)
    from agent.api.views import ProjectDetailView
    from agent.tools.projects.projects import update_project as _update
    params = {"project_id": project_id}
    if body:
        params.update({k: v for k, v in body.model_dump().items() if v is not None})
    result = _update.invoke(params)
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    session = SessionLocal()
    try:
        view = _project_detail_view(session, project_id, user_id)
        if not view:
            raise HTTPException(status_code=404, detail="Project not found")
        return ProjectDetailView(**view)
    finally:
        session.close()


@data_router.delete("/projects/{project_id}")
def delete_project(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.api.views import ProjectDetailView
    from agent.tools.projects.projects import delete_project as _delete
    session = SessionLocal()
    try:
        view = _project_detail_view(session, project_id, user_id)
        if not view:
            raise HTTPException(status_code=404, detail="Project not found")
    finally:
        session.close()
    result = _delete.invoke({"project_id": project_id})
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    return ProjectDetailView(**view)


@data_router.get("/projects/{project_id}/brief")
def get_project_brief(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.api.views import ProjectBriefView
    from agent.tools.projects.planning import get_project_brief as _get_brief
    result = _get_brief.invoke({"project_id": project_id})
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    session = SessionLocal()
    try:
        _project_or_404(session, project_id, user_id)
        brief = session.query(ProjectBrief).filter(ProjectBrief.project_id == project_id).first()
        if not brief:
            raise HTTPException(status_code=404, detail=f"No brief found for project {project_id}.")
        return ProjectBriefView(**brief.to_view())
    finally:
        session.close()


@data_router.patch("/projects/{project_id}/brief")
def update_project_brief(project_id: str, user_id: str, body: UpdateBriefRequest = None):
    _set_user(user_id)
    from agent.api.views import ProjectBriefView
    from agent.tools.projects.planning import update_project_brief as _update_brief
    params = {"project_id": project_id}
    if body:
        supported = {
            "desired_outcome", "target_start", "target_completion", "budget_cap",
            "effort_preference", "propagation_preference", "priority_preferences",
            "notes", "status",
        }
        params.update({k: v for k, v in body.model_dump().items() if k in supported and v is not None})
    result = _update_brief.invoke(params)
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    session = SessionLocal()
    try:
        _project_or_404(session, project_id, user_id)
        brief = session.query(ProjectBrief).filter(ProjectBrief.project_id == project_id).first()
        if not brief:
            raise HTTPException(status_code=404, detail=f"No brief found for project {project_id}.")
        return ProjectBriefView(**brief.to_view())
    finally:
        session.close()


@data_router.get("/projects/{project_id}/proposals")
def list_project_proposals(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.api.views import ProposalSummaryView
    session = SessionLocal()
    try:
        _project_or_404(session, project_id, user_id)
        proposals = (
            session.query(ProjectProposal)
            .filter(ProjectProposal.project_id == project_id)
            .order_by(ProjectProposal.version.desc())
            .all()
        )
        return [ProposalSummaryView(**p.to_summary_view()) for p in proposals]
    finally:
        session.close()


@data_router.get("/projects/{project_id}/proposals/{proposal_id}")
def get_project_proposal(project_id: str, proposal_id: str, user_id: str):
    _set_user(user_id)
    from agent.api.views import ProposalDetailView
    session = SessionLocal()
    try:
        _project_or_404(session, project_id, user_id)
        proposal = (
            session.query(ProjectProposal)
            .filter(ProjectProposal.id == proposal_id, ProjectProposal.project_id == project_id)
            .first()
        )
        if not proposal:
            raise HTTPException(status_code=404, detail=f"No proposal found with id {proposal_id} for project {project_id}.")
        return ProposalDetailView(**proposal.to_detail_view())
    finally:
        session.close()


@data_router.post("/projects/{project_id}/proposals/{proposal_id}/accept")
def accept_project_proposal(project_id: str, proposal_id: str, user_id: str):
    _set_user(user_id)
    from agent.api.views import ProposalDetailView
    from agent.tools.projects.planning import accept_project_proposal as _accept
    result = _accept.invoke({"project_id": project_id, "proposal_id": proposal_id})
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    session = SessionLocal()
    try:
        proposal = (
            session.query(ProjectProposal)
            .filter(ProjectProposal.id == proposal_id, ProjectProposal.project_id == project_id)
            .first()
        )
        if not proposal:
            raise HTTPException(status_code=404, detail=f"No proposal found with id {proposal_id} for project {project_id}.")
        return ProposalDetailView(**proposal.to_detail_view())
    finally:
        session.close()


@data_router.get("/projects/{project_id}/series")
def list_project_series(project_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id,
            GardeningProject.user_id == user_id,
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        series = session.query(TaskSeries).filter(
            TaskSeries.project_id == project_id, TaskSeries.active == True
        ).all()
        return [s.to_view() for s in series]
    finally:
        session.close()


@data_router.get("/projects/{project_id}/beds")
def list_project_beds(project_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id, GardeningProject.user_id == user_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        beds = session.query(Bed).join(ProjectBed, Bed.id == ProjectBed.bed_id).filter(
            ProjectBed.project_id == project_id).all()
        # Determine availability: not in any OTHER active/maintaining project
        busy_bed_ids = {bid for (bid,) in session.query(ProjectBed.bed_id).join(
            GardeningProject, ProjectBed.project_id == GardeningProject.id
        ).filter(
            GardeningProject.user_id == user_id,
            GardeningProject.status.in_(["active", "maintaining"]),
            GardeningProject.id != project_id,
        ).all()}
        return [b.to_view(available=b.id not in busy_bed_ids) for b in beds]
    finally:
        session.close()


@data_router.get("/projects/{project_id}/containers")
def list_project_containers(project_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id, GardeningProject.user_id == user_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        containers = session.query(Container).join(
            ProjectContainer, Container.id == ProjectContainer.container_id
        ).filter(ProjectContainer.project_id == project_id).all()
        busy_ids = {cid for (cid,) in session.query(ProjectContainer.container_id).join(
            GardeningProject, ProjectContainer.project_id == GardeningProject.id
        ).filter(
            GardeningProject.user_id == user_id,
            GardeningProject.status.in_(["active", "maintaining"]),
            GardeningProject.id != project_id,
        ).all()}
        return [c.to_view(available=c.id not in busy_ids) for c in containers]
    finally:
        session.close()


@data_router.post("/projects/{project_id}/beds/{bed_id}")
def assign_bed(project_id: str, bed_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import assign_bed_to_project
    return _result_or_404(assign_bed_to_project.invoke({"project_id": project_id, "bed_id": bed_id}))


@data_router.delete("/projects/{project_id}/beds/{bed_id}")
def unassign_bed(project_id: str, bed_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import unassign_bed_from_project
    return _result_or_404(unassign_bed_from_project.invoke({"project_id": project_id, "bed_id": bed_id}))


@data_router.post("/projects/{project_id}/beds/batch")
def assign_beds_batch(project_id: str, user_id: str, body: AssignLocationsRequest):
    _set_user(user_id)
    from agent.tools.projects.projects import assign_beds_to_project
    return _result_or_404(assign_beds_to_project.invoke({"project_id": project_id, "bed_ids": body.bed_ids or []}))


@data_router.post("/projects/{project_id}/containers/{container_id}")
def assign_container(project_id: str, container_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import assign_container_to_project
    return _result_or_404(assign_container_to_project.invoke({"project_id": project_id, "container_id": container_id}))


@data_router.delete("/projects/{project_id}/containers/{container_id}")
def unassign_container(project_id: str, container_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import unassign_container_from_project
    return _result_or_404(unassign_container_from_project.invoke({"project_id": project_id, "container_id": container_id}))


@data_router.post("/projects/{project_id}/containers/batch")
def assign_containers_batch(project_id: str, user_id: str, body: AssignLocationsRequest):
    _set_user(user_id)
    from agent.tools.projects.projects import assign_containers_to_project
    return _result_or_404(assign_containers_to_project.invoke({"project_id": project_id, "container_ids": body.container_ids or []}))


@data_router.post("/projects/{project_id}/plants/{plant_id}")
def add_plant_to_project(project_id: str, plant_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import add_plant_to_project as _add
    return _result_or_404(_add.invoke({"project_id": project_id, "plant_id": plant_id}))


@data_router.delete("/projects/{project_id}/plants/{plant_id}")
def remove_plant_from_project(project_id: str, plant_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import remove_plant_from_project as _remove
    return _result_or_404(_remove.invoke({"project_id": project_id, "plant_id": plant_id}))


@data_router.get("/projects/{project_id}/activity")
def get_project_activity(
    project_id: str, user_id: str,
    category: str = None, event_type: str = None,
    since: str = None, before_timestamp: str = None, limit: int = 20,
):
    _set_user(user_id)
    from agent.api.views import ActivityEventView
    from agent.domain.activity_log import activity_events_to_view_data, list_recent_activity_entries

    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id, GardeningProject.user_id == user_id
        ).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        since_dt = datetime.fromisoformat(since) if since else None
        before_dt = datetime.fromisoformat(before_timestamp) if before_timestamp else None
        events = list_recent_activity_entries(
            session, project_id=project_id, category=category, event_type=event_type,
            since=since_dt, before_timestamp=before_dt, limit=limit,
        )
        return [ActivityEventView(**data) for data in activity_events_to_view_data(session, events)]
    finally:
        session.close()


# --- Monitor ---

@data_router.get("/monitor/runs")
def list_monitor_runs(user_id: str, limit: int = 20):
    uid = _set_user(user_id)
    from db.models import MonitorRun
    session = SessionLocal()
    try:
        rows = (
            session.query(MonitorRun)
            .filter(MonitorRun.user_id == uid)
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
    uid = _set_user(user_id)
    from db.models import MonitorRun
    session = SessionLocal()
    try:
        run = session.query(MonitorRun).filter(
            MonitorRun.id == run_id, MonitorRun.user_id == uid
        ).first()
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
    session = SessionLocal()
    try:
        profile = session.query(GardenProfile).filter(GardenProfile.user_id == user_id).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Garden profile not found")
        return profile.to_view()
    finally:
        session.close()


@data_router.patch("/garden/profile")
def update_garden_profile(user_id: str, body: dict = None):
    _set_user(user_id)
    from agent.tools.garden.profile import update_garden_profile as _update
    result = _update.invoke(body or {})
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    session = SessionLocal()
    try:
        profile = session.query(GardenProfile).filter(GardenProfile.user_id == user_id).first()
        return profile.to_view()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Garden — beds
# ---------------------------------------------------------------------------

@data_router.get("/garden/beds")
def list_beds(user_id: str, available: str = None):
    _set_user(user_id)
    session = SessionLocal()
    try:
        query = session.query(Bed).filter(Bed.user_id == user_id)
        if available == "true":
            busy_bed_ids = {bid for (bid,) in session.query(ProjectBed.bed_id).join(
                GardeningProject, ProjectBed.project_id == GardeningProject.id
            ).filter(
                GardeningProject.user_id == user_id,
                GardeningProject.status.in_(["active", "maintaining"]),
            ).all()}
            query = query.filter(~Bed.id.in_(busy_bed_ids))
        return [b.to_view() for b in query.all()]
    finally:
        session.close()


@data_router.post("/garden/beds")
def create_bed(user_id: str, body: CreateBedRequest):
    _set_user(user_id)
    session = SessionLocal()
    try:
        profile = session.query(GardenProfile).filter(GardenProfile.user_id == user_id).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Garden profile not found")
        import re
        sqft = None
        if body.size:
            m = re.search(r"([\d.]+)", body.size)
            if m:
                sqft = float(m.group(1))
        bed = Bed(
            user_id=user_id,
            garden_profile_id=profile.id,
            name=body.name,
            location=body.location,
            dimensions_sqft=sqft,
            sunlight=body.sunlight,
            soil_type=body.soil_type,
            notes=body.notes,
        )
        session.add(bed)
        session.commit()
        session.refresh(bed)
        return bed.to_view()
    finally:
        session.close()


@data_router.get("/garden/beds/{bed_id}")
def get_bed(bed_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        bed = session.query(Bed).filter(Bed.id == bed_id, Bed.user_id == user_id).first()
        if not bed:
            raise HTTPException(status_code=404, detail="Bed not found")
        return bed.to_view()
    finally:
        session.close()


@data_router.patch("/garden/beds/{bed_id}")
def update_bed(bed_id: str, user_id: str, body: dict = None):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import update_bed as _update
    result = _update.invoke({"bed_id": bed_id, **(body or {})})
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    session = SessionLocal()
    try:
        bed = session.query(Bed).filter(Bed.id == bed_id, Bed.user_id == user_id).first()
        return bed.to_view()
    finally:
        session.close()


@data_router.delete("/garden/beds/{bed_id}")
def delete_bed(bed_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import delete_bed as _delete
    return _result_or_404(_delete.invoke({"bed_id": bed_id}))


@data_router.get("/garden/beds/{bed_id}/care/state")
def get_bed_care_state(bed_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        bed = session.query(Bed).filter(Bed.id == bed_id, Bed.user_id == user_id).first()
        if not bed:
            raise HTTPException(status_code=404, detail="Bed not found")
        return bed.to_care_state_view()
    finally:
        session.close()


@data_router.get("/garden/beds/{bed_id}/care/history")
def get_bed_care_history(bed_id: str, user_id: str, limit: int = 10):
    _set_user(user_id)
    from agent.tools.operations.care import get_recent_care_history
    return {"result": get_recent_care_history.invoke({"subject_type": "bed", "subject_id": bed_id, "limit": limit})}


@data_router.get("/garden/beds/{bed_id}/activity")
def get_bed_activity(bed_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.api.views import ActivityEventView
    from agent.domain.activity_log import activity_events_to_view_data, get_activity_for_subject

    session = SessionLocal()
    try:
        bed = session.query(Bed).filter(Bed.id == bed_id, Bed.user_id == user_id).first()
        if not bed:
            raise HTTPException(status_code=404, detail="Bed not found")
        events = get_activity_for_subject(session, subject_type="bed", subject_id=bed_id, limit=limit)
        return [ActivityEventView(**data) for data in activity_events_to_view_data(session, events)]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Garden — containers
# ---------------------------------------------------------------------------

@data_router.get("/garden/containers")
def list_containers(user_id: str, available: str = None):
    _set_user(user_id)
    session = SessionLocal()
    try:
        query = session.query(Container).filter(Container.user_id == user_id)
        if available == "true":
            busy_ids = {cid for (cid,) in session.query(ProjectContainer.container_id).join(
                GardeningProject, ProjectContainer.project_id == GardeningProject.id
            ).filter(
                GardeningProject.user_id == user_id,
                GardeningProject.status.in_(["active", "maintaining"]),
            ).all()}
            query = query.filter(~Container.id.in_(busy_ids))
        return [c.to_view() for c in query.all()]
    finally:
        session.close()


@data_router.get("/garden/containers/{container_id}")
def get_container(container_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        container = session.query(Container).filter(
            Container.id == container_id, Container.user_id == user_id).first()
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
        return container.to_view()
    finally:
        session.close()


@data_router.post("/garden/containers")
def add_container(user_id: str, body: dict):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import add_container as _add
    result = _add.invoke(body)
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    container_id = _extract_id_after(result, "with id")
    session = SessionLocal()
    try:
        container = session.query(Container).filter(
            Container.id == container_id, Container.user_id == user_id
        ).first()
        return container.to_view()
    finally:
        session.close()


@data_router.patch("/garden/containers/{container_id}")
def update_container(container_id: str, user_id: str, body: dict = None):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import update_container as _update
    result = _update.invoke({"container_id": container_id, **(body or {})})
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    session = SessionLocal()
    try:
        container = session.query(Container).filter(
            Container.id == container_id, Container.user_id == user_id
        ).first()
        return container.to_view()
    finally:
        session.close()



@data_router.delete("/garden/containers/{container_id}")
def remove_container(container_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import remove_container as _remove
    return _result_or_404(_remove.invoke({"container_id": container_id}))


@data_router.get("/garden/containers/{container_id}/care/state")
def get_container_care_state(container_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        container = session.query(Container).filter(
            Container.id == container_id, Container.user_id == user_id).first()
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
        return container.to_care_state_view()
    finally:
        session.close()


@data_router.get("/garden/containers/{container_id}/care/history")
def get_container_care_history(container_id: str, user_id: str, limit: int = 10):
    _set_user(user_id)
    from agent.tools.operations.care import get_recent_care_history
    return {"result": get_recent_care_history.invoke({"subject_type": "container", "subject_id": container_id, "limit": limit})}


@data_router.get("/garden/containers/{container_id}/activity")
def get_container_activity(container_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.api.views import ActivityEventView
    from agent.domain.activity_log import activity_events_to_view_data, get_activity_for_subject

    session = SessionLocal()
    try:
        container = session.query(Container).filter(
            Container.id == container_id, Container.user_id == user_id
        ).first()
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
        events = get_activity_for_subject(session, subject_type="container", subject_id=container_id, limit=limit)
        return [ActivityEventView(**data) for data in activity_events_to_view_data(session, events)]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Garden — plants
# ---------------------------------------------------------------------------

@data_router.get("/garden/plants")
def list_plants(
    user_id: str, status: str = None, project_id: str = None, batch_id: str = None,
    bed_id: str = None, container_id: str = None, location: str = None,
):
    _set_user(user_id)
    session = SessionLocal()
    try:
        query = session.query(Plant).filter(Plant.user_id == user_id)
        if status:
            query = query.filter(Plant.status == status)
        else:
            query = query.filter(Plant.status != "removed")
        if batch_id:
            query = query.filter(Plant.batch_id == batch_id)
        if bed_id:
            query = query.filter(Plant.bed_id == bed_id)
        if container_id:
            query = query.filter(Plant.container_id == container_id)
        if project_id:
            query = query.join(ProjectPlant, Plant.id == ProjectPlant.plant_id).filter(
                ProjectPlant.project_id == project_id, ProjectPlant.removed_at == None)
        if location:
            # Filter plants whose bed or container is at the given location
            location_bed_ids = {bid for (bid,) in session.query(Bed.id).filter(
                Bed.user_id == user_id, Bed.location == location).all()}
            location_container_ids = {cid for (cid,) in session.query(Container.id).filter(
                Container.user_id == user_id, Container.location == location).all()}
            from sqlalchemy import or_
            query = query.filter(or_(
                Plant.bed_id.in_(location_bed_ids),
                Plant.container_id.in_(location_container_ids),
            ))
        plants = query.all()
        # Bulk-fetch location names to avoid N+1
        bed_ids_set = {p.bed_id for p in plants if p.bed_id}
        container_ids_set = {p.container_id for p in plants if p.container_id}
        bed_names = {b.id: b.name for b in session.query(Bed).filter(Bed.id.in_(bed_ids_set)).all()} if bed_ids_set else {}
        container_names = {c.id: c.name for c in session.query(Container).filter(
            Container.id.in_(container_ids_set)).all()} if container_ids_set else {}
        def _location_name(p):
            if p.bed_id:
                return bed_names.get(p.bed_id)
            if p.container_id:
                return container_names.get(p.container_id)
            return None
        return [p.to_summary_view(location_name=_location_name(p)) for p in plants]
    finally:
        session.close()


@data_router.get("/garden/plants/{plant_id}")
def get_plant(plant_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        plant = session.query(Plant).filter(Plant.id == plant_id, Plant.user_id == user_id).first()
        if not plant:
            raise HTTPException(status_code=404, detail="Plant not found")
        bed_name = None
        container_name = None
        if plant.bed_id:
            bed = session.query(Bed).filter(Bed.id == plant.bed_id).first()
            bed_name = bed.name if bed else None
        elif plant.container_id:
            container = session.query(Container).filter(Container.id == plant.container_id).first()
            container_name = container.name if container else None
        location_name = bed_name or container_name
        return plant.to_detail_view(location_name=location_name)
    finally:
        session.close()


@data_router.post("/garden/plants")
def add_plant(user_id: str, body: dict):
    _set_user(user_id)
    from agent.tools.garden.plants import add_plant as _add
    result = _add.invoke(body)
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    plant_id = _extract_id_after(result, "with id")
    session = SessionLocal()
    try:
        plant = session.query(Plant).filter(Plant.id == plant_id, Plant.user_id == user_id).first()
        return plant.to_detail_view()
    finally:
        session.close()


@data_router.post("/garden/plants/batch")
def batch_add_plants(user_id: str, body: dict):
    _set_user(user_id)
    from agent.api.views import PlantBatchResultView
    from agent.tools.garden.plants import batch_add_plant_type
    result = batch_add_plant_type.invoke(body)
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    match = re.search(rf"\(id: ({_UUID_RE})\)", result)
    batch_id = match.group(1) if match else None
    session = SessionLocal()
    try:
        batch = session.query(PlantBatch).filter(
            PlantBatch.id == batch_id, PlantBatch.user_id == user_id
        ).first()
        plants = session.query(Plant).filter(Plant.batch_id == batch_id).all()
        return PlantBatchResultView(
            batch_id=batch.id,
            batch_name=batch.name,
            plant_name=batch.plant_name,
            variety=batch.variety,
            quantity_sown=batch.quantity_sown,
            project_id=batch.project_id,
            created_at=batch.created_at,
            plants=[p.to_summary_view() for p in plants],
        )
    finally:
        session.close()


# NOTE: these /garden/plants/batch* routes must be registered before the
# /garden/plants/{plant_id} routes below — Starlette matches path routes in
# registration order, and {plant_id} happily matches the literal "batch"
# segment, which would otherwise shadow these routes entirely.
@data_router.patch("/garden/plants/batch")
def batch_update_plants(user_id: str, body: dict):
    _set_user(user_id)
    from agent.tools.garden.plants import batch_update_plants as _batch_update

    # Capture which plants match the filter *before* mutating, using the same
    # predicate the tool applies, so we know exactly which rows it touched —
    # the tool's return string doesn't include plant ids.
    session = SessionLocal()
    try:
        query = session.query(Plant).filter(
            Plant.user_id == user_id,
            Plant.name.ilike(f"%{body.get('name', '')}%"),
            Plant.status != "removed",
        )
        if body.get("variety"):
            query = query.filter(Plant.variety.ilike(f"%{body['variety']}%"))
        if body.get("current_status"):
            query = query.filter(Plant.status == body["current_status"])
        if body.get("project_id"):
            query = query.join(ProjectPlant, Plant.id == ProjectPlant.plant_id).filter(
                ProjectPlant.project_id == body["project_id"],
                ProjectPlant.removed_at == None,
            )
        candidates = query.order_by(Plant.created_at.asc()).all()
        if body.get("quantity") is not None and body["quantity"] <= len(candidates):
            candidates = candidates[: body["quantity"]]
        affected_ids = [p.id for p in candidates]
    finally:
        session.close()

    result = _batch_update.invoke(body)
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)

    session = SessionLocal()
    try:
        plants = session.query(Plant).filter(Plant.id.in_(affected_ids)).all() if affected_ids else []
        return [p.to_summary_view() for p in plants]
    finally:
        session.close()


@data_router.patch("/garden/plants/batch/remove")
def batch_remove_plants(user_id: str, body: dict):
    """Soft delete for multiple plants — marks all as removed with a required reason."""
    _set_user(user_id)
    from agent.tools.garden.plants import batch_remove_plants as _batch_remove

    session = SessionLocal()
    try:
        query = session.query(Plant).filter(
            Plant.user_id == user_id,
            Plant.name.ilike(f"%{body.get('name', '')}%"),
            Plant.status != "removed",
        )
        if body.get("variety"):
            query = query.filter(Plant.variety.ilike(f"%{body['variety']}%"))
        if body.get("current_status"):
            query = query.filter(Plant.status == body["current_status"])
        if body.get("project_id"):
            query = query.join(ProjectPlant, Plant.id == ProjectPlant.plant_id).filter(
                ProjectPlant.project_id == body["project_id"],
                ProjectPlant.removed_at == None,
            )
        candidates = query.order_by(Plant.created_at.asc()).all()
        if body.get("quantity") is not None and body["quantity"] <= len(candidates):
            candidates = candidates[: body["quantity"]]
        affected_ids = [p.id for p in candidates]
    finally:
        session.close()

    result = _batch_remove.invoke(body)
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)

    session = SessionLocal()
    try:
        plants = (
            session.query(Plant)
            .filter(Plant.id.in_(affected_ids), Plant.user_id == user_id)
            .order_by(Plant.created_at.asc())
            .all()
            if affected_ids
            else []
        )
        return [p.to_summary_view() for p in plants]
    finally:
        session.close()


@data_router.patch("/garden/plants/{plant_id}")
def update_plant(plant_id: str, user_id: str, body: dict = None):
    _set_user(user_id)
    from agent.tools.garden.plants import update_plant as _update
    result = _update.invoke({"plant_id": plant_id, **(body or {})})
    status = _mutation_error_status(result)
    if status:
        raise HTTPException(status_code=status, detail=result)
    session = SessionLocal()
    try:
        plant = session.query(Plant).filter(Plant.id == plant_id, Plant.user_id == user_id).first()
        return plant.to_detail_view()
    finally:
        session.close()


@data_router.patch("/garden/plants/{plant_id}/remove")
def remove_plant(plant_id: str, user_id: str, reason: str = None):
    """Soft delete — marks plant as removed (died, harvested, rehomed). Keeps the record."""
    _set_user(user_id)
    from agent.tools.garden.plants import remove_plant as _remove
    return _result_or_404(_remove.invoke({"plant_id": plant_id, "reason": reason or "removed via API"}))


@data_router.delete("/garden/plants/{plant_id}")
def delete_plant(plant_id: str, user_id: str):
    """Hard delete — permanently removes the plant record. Use for data entry mistakes only."""
    _set_user(user_id)
    from agent.tools.garden.plants import delete_plant as _delete
    return _result_or_404(_delete.invoke({"plant_id": plant_id}))


@data_router.get("/garden/plants/{plant_id}/care/state")
def get_plant_care_state(plant_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        plant = session.query(Plant).filter(Plant.id == plant_id, Plant.user_id == user_id).first()
        if not plant:
            raise HTTPException(status_code=404, detail="Plant not found")
        return plant.to_care_state_view()
    finally:
        session.close()


@data_router.get("/garden/plants/{plant_id}/care/history")
def get_plant_care_history(plant_id: str, user_id: str, limit: int = 10):
    _set_user(user_id)
    from agent.tools.operations.care import get_recent_care_history
    return {"result": get_recent_care_history.invoke({"subject_type": "plant", "subject_id": plant_id, "limit": limit})}


@data_router.get("/garden/plants/{plant_id}/activity")
def get_plant_activity(plant_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.api.views import ActivityEventView
    from agent.domain.activity_log import activity_events_to_view_data, get_activity_for_subject

    session = SessionLocal()
    try:
        plant = session.query(Plant).filter(Plant.id == plant_id, Plant.user_id == user_id).first()
        if not plant:
            raise HTTPException(status_code=404, detail="Plant not found")
        events = get_activity_for_subject(session, subject_type="plant", subject_id=plant_id, limit=limit)
        return [ActivityEventView(**data) for data in activity_events_to_view_data(session, events)]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Quick care recording (find-or-create + complete in one call)
# ---------------------------------------------------------------------------

# care_type (request) → CARE_ACTIONS key
_CARE_TYPE_MAP = {
    "watered": "water",
    "fertilized": "fertilize",
    "amended": "amend",
    "inspected": "inspect",
    "treated": "treat",
    "pruned": "prune",
}


def _record_care(session, subject_type: str, obj, user_id: str, body: RecordCareRequest):
    """Shared implementation for plant/bed/container quick-care endpoints."""
    from agent.domain.care import CARE_ACTIONS
    from agent.domain.activity_log import record_activity_event
    from db.database import current_user_id

    care_key = _CARE_TYPE_MAP.get(body.care_type)
    if not care_key or subject_type not in CARE_ACTIONS.get(care_key, {}):
        raise HTTPException(
            status_code=400,
            detail=f"care_type '{body.care_type}' is not valid for {subject_type}s",
        )

    event_type, field_name = CARE_ACTIONS[care_key][subject_type]
    care_ts = (
        datetime.fromisoformat(body.recorded_at)
        if body.recorded_at
        else datetime.now(timezone.utc).replace(tzinfo=None)
    )

    # Find an existing pending/in_progress task linked to this subject
    from agent.domain.care import infer_care_action
    user_pids = {pid for (pid,) in session.query(GardeningProject.id).filter(
        GardeningProject.user_id == user_id).all()}
    existing_task = None
    if user_pids:
        candidates = session.query(Task).filter(
            Task.project_id.in_(user_pids),
            Task.status.in_(["pending", "in_progress"]),
        ).all()
        for t in candidates:
            if infer_care_action(t) == care_key:
                for s in (t.linked_subjects or []):
                    if s.get("subject_type") == subject_type and s.get("subject_id") == obj.id:
                        existing_task = t
                        break
            if existing_task:
                break

    # Apply care timestamp directly (works regardless of task)
    setattr(obj, field_name, care_ts)
    if body.notes:
        existing = getattr(obj, "care_state_notes", None)
        setattr(obj, "care_state_notes", f"{existing}\n{body.notes}".strip() if existing else body.notes)

    # If we found an existing task, complete it too
    task_view = None
    if existing_task:
        existing_task.status = "done"
        existing_task.completed_at = care_ts
        if body.notes:
            existing_task.notes = (
                f"{existing_task.notes}\n{body.notes}".strip()
                if existing_task.notes else body.notes
            )
        task_view = existing_task.to_summary_view()

    # Record care activity event
    record_activity_event(
        session,
        actor_type="user",
        actor_label="quick_care",
        event_type=event_type,
        category=subject_type,
        summary=f"{obj.__class__.__name__} {body.care_type}" + (f": {body.notes}" if body.notes else "."),
        metadata={"care_type": body.care_type, "recorded_at": care_ts.isoformat()},
        subjects=[{"subject_type": subject_type, "subject_id": obj.id, "role": "primary"}],
    )

    session.commit()
    session.refresh(obj)
    return {"task": task_view, "care_state": obj.to_care_state_view()}


@data_router.post("/garden/plants/{plant_id}/care")
def record_plant_care(plant_id: str, user_id: str, body: RecordCareRequest):
    _set_user(user_id)
    session = SessionLocal()
    try:
        plant = session.query(Plant).filter(Plant.id == plant_id, Plant.user_id == user_id).first()
        if not plant:
            raise HTTPException(status_code=404, detail="Plant not found")
        return _record_care(session, "plant", plant, user_id, body)
    finally:
        session.close()


@data_router.post("/garden/beds/{bed_id}/care")
def record_bed_care(bed_id: str, user_id: str, body: RecordCareRequest):
    _set_user(user_id)
    session = SessionLocal()
    try:
        bed = session.query(Bed).filter(Bed.id == bed_id, Bed.user_id == user_id).first()
        if not bed:
            raise HTTPException(status_code=404, detail="Bed not found")
        return _record_care(session, "bed", bed, user_id, body)
    finally:
        session.close()


@data_router.post("/garden/containers/{container_id}/care")
def record_container_care(container_id: str, user_id: str, body: RecordCareRequest):
    _set_user(user_id)
    session = SessionLocal()
    try:
        container = session.query(Container).filter(
            Container.id == container_id, Container.user_id == user_id).first()
        if not container:
            raise HTTPException(status_code=404, detail="Container not found")
        return _record_care(session, "container", container, user_id, body)
    finally:
        session.close()


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
    return _result_or_404(_delete.invoke({"batch_id": batch_id}))


@data_router.get("/garden/batches/{batch_id}/activity")
def get_batch_activity(batch_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.api.views import ActivityEventView
    from agent.domain.activity_log import activity_events_to_view_data, get_activity_for_subject

    session = SessionLocal()
    try:
        batch = session.query(PlantBatch).filter(
            PlantBatch.id == batch_id, PlantBatch.user_id == user_id
        ).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        events = get_activity_for_subject(session, subject_type="batch", subject_id=batch_id, limit=limit)
        return [ActivityEventView(**data) for data in activity_events_to_view_data(session, events)]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Garden — search
# ---------------------------------------------------------------------------

@data_router.get("/garden/search")
def search_garden(user_id: str, query: str, subject_type: str = None):
    _set_user(user_id)
    from agent.tools.garden.search import search_garden as _search
    return {"result": _search.invoke({"query": query, "subject_type": subject_type})}


@data_router.get("/search")
def unified_search(
    user_id: str,
    q: str,
    types: str = None,
    limit: int = 5,
):
    from agent.api.views import SearchResultItemView, SearchResultsView
    from agent.domain.search import search_entities

    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")
    if limit < 1 or limit > 20:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 20")

    type_list = [t.strip() for t in types.split(",")] if types else None
    _set_user(user_id)
    session = SessionLocal()
    try:
        data = search_entities(session, user_id=user_id, query=q.strip(), types=type_list, limit_per_type=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        session.close()

    return SearchResultsView(
        results=[SearchResultItemView(**r) for r in data["results"]],
        by_type=data["by_type"],
    )


@data_router.get("/garden/locations/{location}")
def list_by_location(location: str, user_id: str):
    _set_user(user_id)
    from agent.api.views import LocationResultsView

    session = SessionLocal()
    try:
        loc = f"%{location}%"
        beds = session.query(Bed).filter(Bed.user_id == user_id, Bed.location.ilike(loc)).all()
        containers = session.query(Container).filter(
            Container.user_id == user_id, Container.location.ilike(loc)
        ).all()

        bed_ids = [b.id for b in beds]
        container_ids = [c.id for c in containers]
        plants = []
        if bed_ids or container_ids:
            from sqlalchemy import or_
            plants = session.query(Plant).filter(
                Plant.user_id == user_id,
                Plant.status != "removed",
                or_(Plant.bed_id.in_(bed_ids), Plant.container_id.in_(container_ids)),
            ).all()

        bed_names = {b.id: b.name for b in beds}
        container_names = {c.id: c.name for c in containers}

        def _location_name(p):
            if p.container_id:
                return container_names.get(p.container_id)
            return bed_names.get(p.bed_id)

        return LocationResultsView(
            beds=[b.to_view() for b in beds],
            containers=[c.to_view() for c in containers],
            plants=[p.to_summary_view(location_name=_location_name(p)) for p in plants],
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------

@data_router.get("/triage/latest")
def get_triage_snapshot(user_id: str):
    _set_user(user_id)
    from agent.api.views import TriageSnapshotView
    from agent.domain.triage import get_latest_triage_snapshot, triage_snapshot_to_view_data

    session = SessionLocal()
    try:
        snapshot = get_latest_triage_snapshot(session)
        if not snapshot:
            return None
        return TriageSnapshotView(**triage_snapshot_to_view_data(session, snapshot))
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

@data_router.get("/weather/latest")
def get_weather_snapshot(user_id: str):
    _set_user(user_id)
    from agent.api.views import WeatherSnapshotView
    from agent.domain.weather import get_latest_weather_snapshot, weather_snapshot_to_view_data

    session = SessionLocal()
    try:
        snapshot = get_latest_weather_snapshot(session)
        if not snapshot:
            return None
        return WeatherSnapshotView(**weather_snapshot_to_view_data(snapshot))
    finally:
        session.close()


@data_router.post("/weather/refresh")
def refresh_weather(user_id: str):
    _set_user(user_id)
    from agent.api.views import WeatherSnapshotView
    from agent.domain.weather import refresh_weather_snapshot as _refresh, weather_snapshot_to_view_data

    session = SessionLocal()
    try:
        snapshot = _refresh(session)
        session.commit()
        return WeatherSnapshotView(**weather_snapshot_to_view_data(snapshot))
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        session.close()


@data_router.get("/weather/tasks/impacted")
def weather_impacted_tasks(user_id: str, project_id: str = None):
    _set_user(user_id)
    from agent.api.views import WeatherImpactedTaskView
    from agent.domain.weather import evaluate_weather_task_impacts

    session = SessionLocal()
    try:
        impacts = evaluate_weather_task_impacts(session, project_id=project_id)
        return [WeatherImpactedTaskView(**impact) for impact in impacts]
    finally:
        session.close()


@data_router.patch("/weather/changesets/{changeset_id}/approve")
def approve_weather_changes(changeset_id: str, user_id: str):
    _set_user(user_id)
    from agent.api.views import WeatherTaskChangeSetView
    from agent.domain.weather import approve_weather_task_changes as _approve

    session = SessionLocal()
    try:
        change_set = _approve(session, changeset_id)
        session.commit()
        task_ids = [item.get("task_id") for item in (change_set.proposed_changes or []) if item.get("task_id")]
        tasks = session.query(Task).filter(Task.id.in_(task_ids or [""])).all() if task_ids else []
        return WeatherTaskChangeSetView(
            id=change_set.id,
            status=change_set.status,
            summary=change_set.summary,
            weather_snapshot_id=change_set.weather_snapshot_id,
            created_at=change_set.created_at,
            approved_at=change_set.approved_at,
            affected_tasks=[t.to_summary_view() for t in tasks],
        )
    except ValueError as e:
        session.rollback()
        message = str(e)
        status = 404 if message.lower().startswith("no ") else 400
        raise HTTPException(status_code=status, detail=message)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Incidents & treatment plans
# ---------------------------------------------------------------------------

def _get_incident_for_user(session, incident_id: str, user_id: str):
    """Return the incident if it belongs to the user, else None."""
    return session.query(IncidentReport).filter(
        IncidentReport.id == incident_id,
        IncidentReport.user_id == user_id,
    ).first()


@data_router.get("/incidents")
def list_incidents(
    user_id: str,
    project_id: str = None,
    status: str = None,
    severity: str = None,
    incident_type: str = None,
    since: str = None,
    before: str = None,
    subject_type: str = None,
    subject_id: str = None,
):
    _set_user(user_id)
    from agent.api.views import IncidentView
    from agent.domain.incidents import incident_to_view_data

    session = SessionLocal()
    try:
        query = session.query(IncidentReport).filter(IncidentReport.user_id == user_id)
        if project_id:
            query = query.filter(IncidentReport.project_id == project_id)
        if status:
            query = query.filter(IncidentReport.status == status)
        if severity:
            query = query.filter(IncidentReport.severity == severity)
        if incident_type:
            query = query.filter(IncidentReport.incident_type == incident_type)
        if since:
            query = query.filter(IncidentReport.created_at >= datetime.fromisoformat(since))
        if before:
            query = query.filter(IncidentReport.created_at < datetime.fromisoformat(before))
        if subject_type and subject_id:
            from db.models import IncidentSubject
            query = query.join(IncidentSubject, IncidentReport.id == IncidentSubject.incident_id).filter(
                IncidentSubject.subject_type == subject_type,
                IncidentSubject.subject_id == subject_id,
            )
        incidents = query.order_by(IncidentReport.created_at.desc()).all()
        return [IncidentView(**incident_to_view_data(inc)) for inc in incidents]
    finally:
        session.close()


@data_router.post("/incidents")
def report_incident(user_id: str, body: ReportIncidentRequest):
    _set_user(user_id)
    from agent.api.views import IncidentView
    from agent.domain.incidents import create_incident_report, incident_to_view_data

    session = SessionLocal()
    try:
        incident = create_incident_report(
            session,
            project_id=None,
            incident_type=body.incident_type,
            severity=body.severity,
            summary=body.summary,
            notes=body.notes,
            subjects=body.subjects,
        )
        session.commit()
        session.refresh(incident)
        return IncidentView(**incident_to_view_data(incident))
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        session.close()


@data_router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, user_id: str):
    _set_user(user_id)
    from agent.api.views import IncidentDetailView
    from agent.domain.incidents import incident_detail_to_view_data

    session = SessionLocal()
    try:
        incident = _get_incident_for_user(session, incident_id, user_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")
        return IncidentDetailView(**incident_detail_to_view_data(session, incident))
    finally:
        session.close()


@data_router.patch("/incidents/{incident_id}")
def update_incident(incident_id: str, user_id: str, body: UpdateIncidentRequest):
    _set_user(user_id)
    from agent.api.views import IncidentView
    from agent.domain.incidents import incident_to_view_data

    session = SessionLocal()
    try:
        incident = _get_incident_for_user(session, incident_id, user_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")
        if body.summary is not None:
            incident.summary = body.summary
        if body.severity is not None:
            incident.severity = body.severity
        if body.notes is not None:
            incident.notes = body.notes
        if body.incident_type is not None:
            incident.incident_type = body.incident_type
        session.commit()
        return IncidentView(**incident_to_view_data(incident))
    finally:
        session.close()


@data_router.delete("/incidents/{incident_id}")
def delete_incident(incident_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        incident = _get_incident_for_user(session, incident_id, user_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")
        # Block if there is an approved treatment plan
        plan = session.query(TreatmentPlan).filter(
            TreatmentPlan.incident_id == incident_id,
            TreatmentPlan.status == "approved",
        ).first()
        if plan:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete incident with an approved treatment plan. Resolve the incident first.",
            )
        session.delete(incident)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


@data_router.patch("/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: str, user_id: str, body: ResolveIncidentRequest = None):
    _set_user(user_id)
    from agent.api.views import IncidentView
    from agent.domain.incidents import incident_to_view_data
    from agent.domain.incidents import resolve_incident as _resolve_incident

    session = SessionLocal()
    try:
        incident = _resolve_incident(session, incident_id, notes=body.notes if body else None)
        session.commit()
        session.refresh(incident)
        return IncidentView(**incident_to_view_data(incident))
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        session.close()


@data_router.get("/incidents/{incident_id}/treatment")
def get_treatment_plan(incident_id: str, user_id: str):
    """Latest treatment plan for an incident.

    Bypasses the `get_treatment_plan` tool entirely — that tool takes a
    `treatment_plan_id`, not an `incident_id`, so calling it from this route
    (as the previous implementation did) raised a pydantic ValidationError on
    every request (#135, same shape of bug as #136's `resolve_interaction`
    mismatch). Querying directly here sidesteps the parameter mismatch rather
    than papering over it.
    """
    _set_user(user_id)
    from agent.api.views import TreatmentPlanView
    from agent.domain.incidents import treatment_plan_to_view_data

    session = SessionLocal()
    try:
        incident = _get_incident_for_user(session, incident_id, user_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")
        plan = (
            session.query(TreatmentPlan)
            .filter(TreatmentPlan.incident_id == incident_id)
            .order_by(TreatmentPlan.created_at.desc())
            .first()
        )
        if not plan:
            raise HTTPException(status_code=404, detail="No treatment plan found for this incident")
        return TreatmentPlanView(**treatment_plan_to_view_data(plan))
    finally:
        session.close()


@data_router.post("/incidents/{incident_id}/treatment/manual")
def create_manual_treatment_plan(incident_id: str, user_id: str, body: CreateManualTreatmentPlanRequest):
    _set_user(user_id)
    from agent.api.views import TreatmentPlanView
    from agent.domain.incidents import treatment_plan_to_view_data

    session = SessionLocal()
    try:
        incident = _get_incident_for_user(session, incident_id, user_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")
        existing = session.query(TreatmentPlan).filter(
            TreatmentPlan.incident_id == incident_id,
            TreatmentPlan.status == "draft",
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="A draft treatment plan already exists for this incident")
        plan = TreatmentPlan(
            incident_id=incident_id,
            status="draft",
            approach_summary=body.approach_summary,
            recommended_steps=body.recommended_steps,
            # AI-drafted plans always store follow_up_strategy as a list of
            # {"title": ...} dicts (agent/domain/incidents.py's
            # _treatment_steps) — wrap the manual string the same way instead
            # of as a bare string, which crashed get_treatment_plan's prose
            # renderer (`follow_up['title']` on a str) (#135).
            follow_up_strategy=[{"title": body.follow_up_strategy}] if body.follow_up_strategy else [],
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)
        return TreatmentPlanView(**treatment_plan_to_view_data(plan))
    finally:
        session.close()


@data_router.patch("/treatment-plans/{plan_id}")
def update_treatment_plan(plan_id: str, user_id: str, body: UpdateTreatmentPlanRequest):
    _set_user(user_id)
    from agent.api.views import TreatmentPlanView
    from agent.domain.incidents import treatment_plan_to_view_data

    session = SessionLocal()
    try:
        plan = session.query(TreatmentPlan).filter(TreatmentPlan.id == plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Treatment plan not found")
        incident = _get_incident_for_user(session, plan.incident_id, user_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Treatment plan not found")
        if plan.status != "draft":
            raise HTTPException(status_code=400, detail="Cannot edit an approved treatment plan")
        if body.approach_summary is not None:
            plan.approach_summary = body.approach_summary
        if body.recommended_steps is not None:
            plan.recommended_steps = body.recommended_steps
        if body.follow_up_strategy is not None:
            plan.follow_up_strategy = (
                [{"title": body.follow_up_strategy}]
                if isinstance(body.follow_up_strategy, str)
                else body.follow_up_strategy
            )
        session.commit()
        session.refresh(plan)
        return TreatmentPlanView(**treatment_plan_to_view_data(plan))
    finally:
        session.close()


@data_router.delete("/treatment-plans/{plan_id}")
def delete_treatment_plan(plan_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        plan = session.query(TreatmentPlan).filter(TreatmentPlan.id == plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Treatment plan not found")
        incident = _get_incident_for_user(session, plan.incident_id, user_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Treatment plan not found")
        if plan.status == "approved":
            raise HTTPException(status_code=400, detail="Cannot delete an approved treatment plan")
        session.delete(plan)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


@data_router.patch("/treatment-plans/{plan_id}/approve")
def approve_treatment_plan(plan_id: str, user_id: str):
    _set_user(user_id)
    from agent.api.views import TreatmentPlanView
    from agent.domain.incidents import approve_treatment_plan as _approve_treatment_plan
    from agent.domain.incidents import treatment_plan_to_view_data

    session = SessionLocal()
    try:
        plan = _approve_treatment_plan(session, plan_id)
        session.commit()
        session.refresh(plan)
        return TreatmentPlanView(**treatment_plan_to_view_data(plan))
    except ValueError as e:
        session.rollback()
        status = 404 if "no treatment plan found" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))
    finally:
        session.close()


@data_router.get("/incidents/{incident_id}/activity")
def get_incident_activity(incident_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.api.views import ActivityEventView
    from agent.domain.activity_log import activity_events_to_view_data, get_activity_for_subject

    session = SessionLocal()
    try:
        incident = _get_incident_for_user(session, incident_id, user_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")
        events = get_activity_for_subject(session, subject_type="incident_report", subject_id=incident_id, limit=limit)
        return [ActivityEventView(**data) for data in activity_events_to_view_data(session, events)]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Interactions
# ---------------------------------------------------------------------------

@data_router.get("/interactions/pending")
def get_pending_interaction(user_id: str):
    _set_user(user_id)
    from agent.api.views import InteractionEnvelopeView
    from agent.domain.interactions import get_pending_interaction_record, interaction_record_to_view_data

    session = SessionLocal()
    try:
        record = get_pending_interaction_record(session)
        if not record:
            return None
        return InteractionEnvelopeView(**interaction_record_to_view_data(record))
    finally:
        session.close()


@data_router.get("/interactions/recent")
def list_recent_interactions(user_id: str, limit: int = 10, interaction_type: str = None, project_id: str = None):
    _set_user(user_id)
    from agent.api.views import InteractionEnvelopeView
    from agent.domain.interactions import interaction_record_to_view_data, list_recent_interaction_records

    session = SessionLocal()
    try:
        records = list_recent_interaction_records(
            session, limit=limit, interaction_type=interaction_type, project_id=project_id,
        )
        return [InteractionEnvelopeView(**interaction_record_to_view_data(r)) for r in records]
    finally:
        session.close()


@data_router.get("/interactions/{interaction_id}")
def get_interaction(interaction_id: str, user_id: str):
    _set_user(user_id)
    from agent.api.views import InteractionEnvelopeView
    from agent.domain.interactions import get_interaction_record_for_user, interaction_record_to_view_data

    session = SessionLocal()
    try:
        record = get_interaction_record_for_user(session, interaction_id)
        if not record:
            raise HTTPException(status_code=404, detail="Interaction record not found")
        return InteractionEnvelopeView(**interaction_record_to_view_data(record))
    finally:
        session.close()


@data_router.post("/interactions/{interaction_id}/resolve")
def resolve_interaction(interaction_id: str, user_id: str, body: ResolveInteractionRequest):
    _set_user(user_id)
    from agent.api.views import InteractionEnvelopeView
    from agent.domain.interactions import get_interaction_record_for_user, interaction_record_to_view_data
    from agent.tools.operations.interactions import resolve_interaction as _resolve

    session = SessionLocal()
    try:
        record = get_interaction_record_for_user(session, interaction_id)
        if not record:
            raise HTTPException(status_code=404, detail="Interaction record not found")
    finally:
        session.close()

    # NOTE: ResolveInteractionRequest uses `action`/`notes` (frontend-facing names);
    # the tool's parameters are `action_id`/`inputs`. This translation was previously
    # missing here, so every call to this endpoint raised a pydantic ValidationError
    # and 500'd before even reaching the tool body (#136 audit).
    _resolve.invoke({
        "interaction_id": interaction_id,
        "action_id": body.action,
        "inputs": {"note": body.notes} if body.notes else {},
    })

    session = SessionLocal()
    try:
        record = get_interaction_record_for_user(session, interaction_id)
        return InteractionEnvelopeView(**interaction_record_to_view_data(record))
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Threads — conversation management
# ---------------------------------------------------------------------------

_VALID_SUBJECT_TYPES = {"plant", "bed", "container", "task", "project", "incident"}


class AddThreadContextRequest(_BaseModel):
    subject_type: str
    subject_id: str


def _verify_entity_owner(session, user_id: str, subject_type: str, subject_id: str) -> bool:
    if subject_type == "plant":
        return session.query(Plant).filter(Plant.id == subject_id, Plant.user_id == user_id).first() is not None
    if subject_type == "bed":
        return session.query(Bed).filter(Bed.id == subject_id, Bed.user_id == user_id).first() is not None
    if subject_type == "container":
        return session.query(Container).filter(Container.id == subject_id, Container.user_id == user_id).first() is not None
    if subject_type == "project":
        return session.query(GardeningProject).filter(
            GardeningProject.id == subject_id, GardeningProject.user_id == user_id
        ).first() is not None
    if subject_type == "task":
        return (
            session.query(Task)
            .join(GardeningProject, Task.project_id == GardeningProject.id)
            .filter(Task.id == subject_id, GardeningProject.user_id == user_id)
            .first()
        ) is not None
    if subject_type == "incident":
        return session.query(IncidentReport).filter(
            IncidentReport.id == subject_id, IncidentReport.user_id == user_id
        ).first() is not None
    return False


@data_router.post("/threads")
def create_thread(user_id: str, body: CreateThreadRequest):
    """Register a thread ID generated by Cambium before the first chat turn."""
    uid = _set_user(user_id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if body.initial_context and len(body.initial_context) > 10:
        raise HTTPException(status_code=400, detail="initial_context cannot exceed 10 items")
    session = SessionLocal()
    try:
        existing = session.query(Thread).filter(Thread.id == body.thread_id).first()
        if existing:
            return {"thread_id": existing.id, "created": False}
        initial_pinned: list[dict] = []
        for item in (body.initial_context or []):
            stype = item.get("subject_type", "")
            sid = item.get("subject_id", "")
            if stype not in _VALID_SUBJECT_TYPES:
                raise HTTPException(status_code=400, detail=f"Invalid subject_type: {stype!r}")
            if not _verify_entity_owner(session, uid, stype, sid):
                raise HTTPException(status_code=400, detail=f"Entity not found or not accessible: {stype}/{sid}")
            initial_pinned.append({"subject_type": stype, "subject_id": sid})
        session.add(Thread(
            id=body.thread_id,
            user_id=uid,
            title=body.title,
            project_id=body.project_id,
            pinned_context=initial_pinned,
            created_at=now,
            last_active_at=now,
        ))
        session.commit()
        return {"thread_id": body.thread_id, "created": True}
    finally:
        session.close()


@data_router.get("/threads")
def list_threads(user_id: str, limit: int = 20):
    """List user's conversation threads, most recently active first."""
    from agent.api.views import ThreadView
    uid = _set_user(user_id)
    session = SessionLocal()
    try:
        rows = (
            session.query(Thread)
            .filter(Thread.user_id == uid)
            .order_by(Thread.last_active_at.desc().nullslast())
            .limit(limit)
            .all()
        )
        return [ThreadView(**r.to_view()) for r in rows]
    finally:
        session.close()


@data_router.get("/threads/{thread_id}")
def get_thread(thread_id: str, user_id: str):
    """Get metadata for a specific thread."""
    from agent.api.views import ThreadView
    uid = _set_user(user_id)
    session = SessionLocal()
    try:
        thread = (
            session.query(Thread)
            .filter(Thread.id == thread_id, Thread.user_id == uid)
            .first()
        )
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        return ThreadView(**thread.to_view())
    finally:
        session.close()


def _request_fields_set(model) -> set[str]:
    fields = getattr(model, "model_fields_set", None)
    if fields is not None:
        return set(fields)
    return set(getattr(model, "__fields_set__", set()))


@data_router.get("/threads/{thread_id}/session-context")
def get_thread_session_context(thread_id: str, user_id: str):
    """Get structured startup/session context for a thread."""
    from agent.api.views import SessionContextView
    from agent.domain.session_context import session_context_to_view_data

    uid = _set_user(user_id)
    session = SessionLocal()
    try:
        thread = (
            session.query(Thread)
            .filter(Thread.id == thread_id, Thread.user_id == uid)
            .first()
        )
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        return SessionContextView(**session_context_to_view_data(session, uid, thread.session_context))
    finally:
        session.close()


@data_router.patch("/threads/{thread_id}/session-context")
def update_thread_session_context(thread_id: str, user_id: str, body: UpdateSessionContextRequest):
    """Update user-controlled startup/session context for a thread."""
    from agent.api.views import SessionContextView
    from agent.domain.session_context import apply_session_context_patch, session_context_to_view_data

    uid = _set_user(user_id)
    session = SessionLocal()
    try:
        thread = (
            session.query(Thread)
            .filter(Thread.id == thread_id, Thread.user_id == uid)
            .first()
        )
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        fields = _request_fields_set(body)
        if not fields:
            raise HTTPException(status_code=400, detail="No session context fields provided")
        updates = {field: getattr(body, field) for field in fields}
        focus_project_id = updates.get("focus_project_id")
        if focus_project_id is not None:
            project = (
                session.query(GardeningProject)
                .filter(GardeningProject.id == focus_project_id, GardeningProject.user_id == uid)
                .first()
            )
            if project is None:
                raise HTTPException(status_code=400, detail="focus_project_id is not accessible")

        thread.session_context = apply_session_context_patch(
            session,
            uid,
            thread.session_context,
            updates,
        )
        session.commit()
        return SessionContextView(**session_context_to_view_data(session, uid, thread.session_context))
    finally:
        session.close()


@data_router.get("/threads/{thread_id}/messages")
def get_thread_messages(thread_id: str, user_id: str):
    """
    Return the full message history for a thread from the LangGraph checkpoint.
    This is the source of truth for conversation content — no duplication needed.
    """
    uid = _set_user(user_id)
    from agent.core.graph import agent
    config = {"configurable": {"thread_id": thread_id, "user_id": uid}}
    state = agent.get_state(config)
    messages = []
    for msg in state.values.get("messages", []):
        if not hasattr(msg, "type"):
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        messages.append({
            "role": "user" if msg.type == "human" else "assistant",
            "content": content,
            "type": msg.type,
        })
    return {"thread_id": thread_id, "messages": messages}


@data_router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, user_id: str):
    """Delete thread metadata. LangGraph checkpoint data is retained for now."""
    uid = _set_user(user_id)
    session = SessionLocal()
    try:
        thread = (
            session.query(Thread)
            .filter(Thread.id == thread_id, Thread.user_id == uid)
            .first()
        )
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        session.delete(thread)
        session.commit()
        return {"status": "deleted", "thread_id": thread_id}
    finally:
        session.close()


@data_router.post("/threads/{thread_id}/context")
def add_thread_context(thread_id: str, user_id: str, body: AddThreadContextRequest):
    """Pin an entity to a thread for persistent context injection."""
    uid = _set_user(user_id)
    if body.subject_type not in _VALID_SUBJECT_TYPES:
        raise HTTPException(status_code=400, detail=f"subject_type must be one of {sorted(_VALID_SUBJECT_TYPES)}")
    session = SessionLocal()
    try:
        thread = session.query(Thread).filter(Thread.id == thread_id, Thread.user_id == uid).first()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        pinned = list(thread.pinned_context or [])
        if len(pinned) >= 10:
            raise HTTPException(status_code=400, detail="Thread context limit reached (max 10 items)")
        if any(p["subject_type"] == body.subject_type and p["subject_id"] == body.subject_id for p in pinned):
            raise HTTPException(status_code=409, detail="Entity already in thread context")
        if not _verify_entity_owner(session, uid, body.subject_type, body.subject_id):
            raise HTTPException(status_code=400, detail="Entity not found or not accessible")
        pinned.append({"subject_type": body.subject_type, "subject_id": body.subject_id})
        thread.pinned_context = pinned
        session.commit()
        return {"thread_id": thread_id, "pinned_context": thread.pinned_context}
    finally:
        session.close()


@data_router.delete("/threads/{thread_id}/context/{subject_type}/{subject_id}")
def remove_thread_context(thread_id: str, subject_type: str, subject_id: str, user_id: str):
    """Remove a pinned entity from a thread's context."""
    uid = _set_user(user_id)
    session = SessionLocal()
    try:
        thread = session.query(Thread).filter(Thread.id == thread_id, Thread.user_id == uid).first()
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        pinned = list(thread.pinned_context or [])
        updated = [p for p in pinned if not (p["subject_type"] == subject_type and p["subject_id"] == subject_id)]
        if len(updated) == len(pinned):
            raise HTTPException(status_code=404, detail="Context entry not found")
        thread.pinned_context = updated
        session.commit()
        return {"thread_id": thread_id, "pinned_context": thread.pinned_context}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Activity — global feed
# ---------------------------------------------------------------------------

@data_router.get("/activity")
def list_recent_activity(
    user_id: str,
    category: str = None, event_type: str = None,
    project_id: str = None, subject_type: str = None,
    since: str = None, before_timestamp: str = None, limit: int = 20,
):
    _set_user(user_id)
    from agent.api.views import ActivityEventView
    from agent.domain.activity_log import activity_events_to_view_data, list_recent_activity_entries

    session = SessionLocal()
    try:
        try:
            since_dt = datetime.fromisoformat(since) if since else None
            before_dt = datetime.fromisoformat(before_timestamp) if before_timestamp else None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")
        events = list_recent_activity_entries(
            session,
            project_id=project_id,
            subject_type=subject_type,
            event_type=event_type,
            category=category,
            since=since_dt,
            before_timestamp=before_dt,
            limit=limit,
        )
        return [ActivityEventView(**data) for data in activity_events_to_view_data(session, events)]
    finally:
        session.close()


@data_router.get("/activity/stats")
def get_activity_stats(
    user_id: str,
    since: str,
    before: str = None,
    event_types: str = None,
    project_id: str = None,
    group_by: str = "day",
):
    _set_user(user_id)
    from datetime import datetime
    from agent.domain.activity_log import get_activity_stats as _stats
    since_dt = datetime.fromisoformat(since)
    before_dt = datetime.fromisoformat(before) if before else None
    event_types_list = [e.strip() for e in event_types.split(",")] if event_types else None
    session = SessionLocal()
    try:
        return _stats(
            session,
            since=since_dt,
            before=before_dt,
            event_types=event_types_list,
            project_id=project_id,
            group_by=group_by,
        )
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Calendar annotations
# ---------------------------------------------------------------------------

@data_router.get("/calendar/annotations")
def list_calendar_annotations(user_id: str, since: str = None, before: str = None):
    _set_user(user_id)
    if not since or not before:
        raise HTTPException(status_code=400, detail="since and before are required")
    from datetime import date as _date
    session = SessionLocal()
    try:
        since_d = _date.fromisoformat(since)
        before_d = _date.fromisoformat(before)
        annotations = session.query(CalendarAnnotation).filter(
            CalendarAnnotation.user_id == user_id,
            CalendarAnnotation.date >= since_d,
            CalendarAnnotation.date <= before_d,
        ).order_by(CalendarAnnotation.date.asc()).all()
        return [a.to_view() for a in annotations]
    finally:
        session.close()


@data_router.post("/calendar/annotations")
def create_calendar_annotation(user_id: str, body: CreateCalendarAnnotationRequest):
    _set_user(user_id)
    from datetime import date as _date
    session = SessionLocal()
    try:
        annotation = CalendarAnnotation(
            user_id=user_id,
            date=_date.fromisoformat(body.date),
            content=body.content,
            category=body.category,
            color=body.color,
        )
        session.add(annotation)
        session.commit()
        session.refresh(annotation)
        return annotation.to_view()
    finally:
        session.close()


@data_router.patch("/calendar/annotations/{annotation_id}")
def update_calendar_annotation(annotation_id: str, user_id: str, body: UpdateCalendarAnnotationRequest):
    _set_user(user_id)
    session = SessionLocal()
    try:
        annotation = session.query(CalendarAnnotation).filter(
            CalendarAnnotation.id == annotation_id,
            CalendarAnnotation.user_id == user_id,
        ).first()
        if not annotation:
            raise HTTPException(status_code=404, detail="Annotation not found")
        if body.content is not None:
            annotation.content = body.content
        if body.category is not None:
            annotation.category = body.category
        if body.color is not None:
            annotation.color = body.color
        session.commit()
        session.refresh(annotation)
        return annotation.to_view()
    finally:
        session.close()


@data_router.delete("/calendar/annotations/{annotation_id}")
def delete_calendar_annotation(annotation_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        annotation = session.query(CalendarAnnotation).filter(
            CalendarAnnotation.id == annotation_id,
            CalendarAnnotation.user_id == user_id,
        ).first()
        if not annotation:
            raise HTTPException(status_code=404, detail="Annotation not found")
        session.delete(annotation)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Project expenses
# ---------------------------------------------------------------------------

@data_router.get("/projects/{project_id}/expenses")
def list_project_expenses(project_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id, GardeningProject.user_id == user_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        expenses = session.query(ProjectExpense).filter(
            ProjectExpense.project_id == project_id).order_by(ProjectExpense.created_at.asc()).all()
        return [e.to_view() for e in expenses]
    finally:
        session.close()


@data_router.post("/projects/{project_id}/expenses")
def create_project_expense(project_id: str, user_id: str, body: CreateProjectExpenseRequest):
    _set_user(user_id)
    from datetime import date as _date
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id, GardeningProject.user_id == user_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        expense = ProjectExpense(
            user_id=user_id,
            project_id=project_id,
            name=body.name,
            category=body.category,
            estimated_cost=body.estimated_cost,
            actual_cost=body.actual_cost,
            quantity=body.quantity,
            unit=body.unit,
            supplier=body.supplier,
            purchased_at=_date.fromisoformat(body.purchased_at) if body.purchased_at else None,
            status=body.status or "needed",
            notes=body.notes,
        )
        session.add(expense)
        session.commit()
        session.refresh(expense)
        return expense.to_view()
    finally:
        session.close()


@data_router.patch("/projects/{project_id}/expenses/{expense_id}")
def update_project_expense(project_id: str, expense_id: str, user_id: str, body: UpdateProjectExpenseRequest):
    _set_user(user_id)
    from datetime import date as _date
    session = SessionLocal()
    try:
        expense = session.query(ProjectExpense).filter(
            ProjectExpense.id == expense_id,
            ProjectExpense.project_id == project_id,
            ProjectExpense.user_id == user_id,
        ).first()
        if not expense:
            raise HTTPException(status_code=404, detail="Expense not found")
        for field in ("name", "category", "estimated_cost", "actual_cost",
                      "quantity", "unit", "supplier", "status", "notes"):
            val = getattr(body, field, None)
            if val is not None:
                setattr(expense, field, val)
        if body.purchased_at is not None:
            expense.purchased_at = _date.fromisoformat(body.purchased_at) if body.purchased_at else None
        session.commit()
        session.refresh(expense)
        return expense.to_view()
    finally:
        session.close()


@data_router.delete("/projects/{project_id}/expenses/{expense_id}")
def delete_project_expense(project_id: str, expense_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        expense = session.query(ProjectExpense).filter(
            ProjectExpense.id == expense_id,
            ProjectExpense.project_id == project_id,
            ProjectExpense.user_id == user_id,
        ).first()
        if not expense:
            raise HTTPException(status_code=404, detail="Expense not found")
        session.delete(expense)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


@data_router.get("/projects/{project_id}/expenses/summary")
def get_project_expense_summary(project_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id, GardeningProject.user_id == user_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        # Get proposal estimate from accepted proposal
        from db.models import ProjectProposal
        accepted = session.query(ProjectProposal).filter(
            ProjectProposal.project_id == project_id,
            ProjectProposal.status == "accepted",
        ).first()
        proposal_estimate = None
        if accepted and accepted.cost_estimate:
            proposal_estimate = accepted.cost_estimate.get("total_estimated_cost")

        expenses = session.query(ProjectExpense).filter(
            ProjectExpense.project_id == project_id).all()
        total_estimated = sum(e.estimated_cost or 0 for e in expenses)
        total_actual = sum(e.actual_cost or 0 for e in expenses)
        by_category: dict = {}
        for e in expenses:
            cat = e.category
            if cat not in by_category:
                by_category[cat] = {"estimated": 0.0, "actual": 0.0}
            by_category[cat]["estimated"] += e.estimated_cost or 0
            by_category[cat]["actual"] += e.actual_cost or 0
        return {
            "proposal_estimate": proposal_estimate,
            "total_estimated": total_estimated,
            "total_actual": total_actual,
            "remaining_estimate": total_estimated - total_actual,
            "by_category": by_category,
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Shopping list
# ---------------------------------------------------------------------------

@data_router.get("/shopping")
def list_shopping_items(
    user_id: str, status: str = None, project_id: str = None,
    category: str = None, priority: str = None,
):
    _set_user(user_id)
    session = SessionLocal()
    try:
        query = session.query(ShoppingItem).filter(ShoppingItem.user_id == user_id)
        if status:
            query = query.filter(ShoppingItem.status == status)
        if project_id:
            query = query.filter(ShoppingItem.project_id == project_id)
        if category:
            query = query.filter(ShoppingItem.category == category)
        if priority:
            query = query.filter(ShoppingItem.priority == priority)
        items = query.order_by(ShoppingItem.created_at.desc()).all()
        return [i.to_view() for i in items]
    finally:
        session.close()


@data_router.post("/shopping")
def create_shopping_item(user_id: str, body: CreateShoppingItemRequest):
    _set_user(user_id)
    session = SessionLocal()
    try:
        if body.project_id:
            project = session.query(GardeningProject).filter(
                GardeningProject.id == body.project_id,
                GardeningProject.user_id == user_id,
            ).first()
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
        item = ShoppingItem(
            user_id=user_id,
            project_id=body.project_id,
            name=body.name,
            category=body.category,
            quantity=body.quantity,
            unit=body.unit,
            estimated_cost=body.estimated_cost,
            supplier=body.supplier,
            notes=body.notes,
            priority=body.priority or "normal",
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return item.to_view()
    finally:
        session.close()


@data_router.patch("/shopping/{item_id}")
def update_shopping_item(item_id: str, user_id: str, body: UpdateShoppingItemRequest):
    _set_user(user_id)
    session = SessionLocal()
    try:
        item = session.query(ShoppingItem).filter(
            ShoppingItem.id == item_id, ShoppingItem.user_id == user_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Shopping item not found")
        for field in ("name", "category", "project_id", "quantity", "unit",
                      "estimated_cost", "supplier", "notes", "status", "priority"):
            val = getattr(body, field, None)
            if val is not None:
                setattr(item, field, val)
        session.commit()
        session.refresh(item)
        return item.to_view()
    finally:
        session.close()


@data_router.delete("/shopping/{item_id}")
def delete_shopping_item(item_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        item = session.query(ShoppingItem).filter(
            ShoppingItem.id == item_id, ShoppingItem.user_id == user_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Shopping item not found")
        session.delete(item)
        session.commit()
        return {"status": "deleted"}
    finally:
        session.close()


@data_router.post("/shopping/{item_id}/purchase")
def purchase_shopping_item(item_id: str, user_id: str):
    _set_user(user_id)
    session = SessionLocal()
    try:
        item = session.query(ShoppingItem).filter(
            ShoppingItem.id == item_id, ShoppingItem.user_id == user_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Shopping item not found")
        item.status = "purchased"
        # Optionally create a linked ProjectExpense
        if item.project_id and item.estimated_cost is not None:
            expense = ProjectExpense(
                user_id=user_id,
                project_id=item.project_id,
                name=item.name,
                category=item.category,
                estimated_cost=item.estimated_cost,
                actual_cost=item.estimated_cost,
                quantity=item.quantity,
                unit=item.unit,
                supplier=item.supplier,
                status="purchased",
            )
            session.add(expense)
            session.flush()
            item.expense_id = expense.id
        session.commit()
        session.refresh(item)
        return item.to_view()
    finally:
        session.close()


@data_router.get("/projects/{project_id}/shopping")
def list_project_shopping(project_id: str, user_id: str, status: str = None):
    _set_user(user_id)
    session = SessionLocal()
    try:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == project_id, GardeningProject.user_id == user_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        query = session.query(ShoppingItem).filter(
            ShoppingItem.project_id == project_id, ShoppingItem.user_id == user_id)
        if status:
            query = query.filter(ShoppingItem.status == status)
        return [i.to_view() for i in query.order_by(ShoppingItem.created_at.desc()).all()]
    finally:
        session.close()
