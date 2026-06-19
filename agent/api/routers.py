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
    ResumeRequest,
    ResolveInteractionRequest,
    TaskActionRequest,
    UpdateBriefRequest,
    UpdateCalendarAnnotationRequest,
    UpdateIncidentRequest,
    UpdateProjectExpenseRequest,
    UpdateProjectRequest,
    UpdateShoppingItemRequest,
    UpdateTaskRequest,
    UpdateTaskSeriesRequest,
    UpdateTreatmentPlanRequest,
)
from agent.core.graph import agent
from db.database import SessionLocal, current_user_id
from db.models import (
    Bed, CalendarAnnotation, Container, GardenProfile, GardeningProject,
    IncidentReport, MonitorAlert, Plant, PlantBatch, ProjectBed, ProjectContainer, ProjectPlant,
    ProjectExpense, ShoppingItem, Task, TaskDependency, TaskSeries, TreatmentPlan,
)
from sqlalchemy import func, or_

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
            "user_id": req.user_id,
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
    config = {"configurable": {"thread_id": req.thread_id, "user_id": req.user_id}}

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
    from agent.tools.projects.tracker import list_blocked_tasks as _list_blocked_tasks
    return {"result": _list_blocked_tasks.invoke({"project_id": project_id})}


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
    return _result_or_404(_update_task.invoke(params))


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
    from agent.tools.operations.activity import get_task_activity as _get_task_activity
    return _result_or_404(_get_task_activity.invoke({"task_id": task_id, "limit": limit}))


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
    return _result_or_404(_update_series.invoke(params))


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
    from agent.tools.projects.projects import get_project_progress
    return _result_or_404(get_project_progress.invoke({"project_id": project_id}))


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
    return _result_or_404(_update.invoke(params))


@data_router.delete("/projects/{project_id}")
def delete_project(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.projects import delete_project as _delete
    return _result_or_404(_delete.invoke({"project_id": project_id}))


@data_router.get("/projects/{project_id}/brief")
def get_project_brief(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.planning import get_project_brief as _get_brief
    return _result_or_404(_get_brief.invoke({"project_id": project_id}))


@data_router.patch("/projects/{project_id}/brief")
def update_project_brief(project_id: str, user_id: str, body: UpdateBriefRequest = None):
    _set_user(user_id)
    from agent.tools.projects.planning import update_project_brief as _update_brief
    params = {"project_id": project_id}
    if body:
        params.update({k: v for k, v in body.model_dump().items() if v is not None})
    return _result_or_404(_update_brief.invoke(params))


@data_router.get("/projects/{project_id}/proposals")
def list_project_proposals(project_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.planning import list_project_proposals as _list
    return _result_or_404(_list.invoke({"project_id": project_id}))


@data_router.get("/projects/{project_id}/proposals/{proposal_id}")
def get_project_proposal(project_id: str, proposal_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.planning import get_project_proposal as _get
    return _result_or_404(_get.invoke({"proposal_id": proposal_id}))


@data_router.post("/projects/{project_id}/proposals/{proposal_id}/accept")
def accept_project_proposal(project_id: str, proposal_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.projects.planning import accept_project_proposal as _accept
    return _result_or_404(_accept.invoke({"proposal_id": proposal_id}))


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
    from agent.tools.operations.activity import list_project_activity
    return {"result": list_project_activity.invoke({
        "project_id": project_id, "category": category, "event_type": event_type,
        "since": since, "before_timestamp": before_timestamp, "limit": limit,
    })}


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
    return {"result": _update.invoke(body or {})}


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
    return _result_or_404(_update.invoke({"bed_id": bed_id, **(body or {})}))


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
    from agent.tools.operations.activity import get_bed_activity as _get
    return _result_or_404(_get.invoke({"bed_id": bed_id, "limit": limit}))


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
    return {"result": _add.invoke(body)}


@data_router.patch("/garden/containers/{container_id}")
def update_container(container_id: str, user_id: str, body: dict = None):
    _set_user(user_id)
    from agent.tools.garden.beds_containers import update_container as _update
    return _result_or_404(_update.invoke({"container_id": container_id, **(body or {})}))



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
    from agent.tools.operations.activity import get_container_activity as _get
    return _result_or_404(_get.invoke({"container_id": container_id, "limit": limit}))


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
    return {"result": _add.invoke(body)}


@data_router.patch("/garden/plants/{plant_id}")
def update_plant(plant_id: str, user_id: str, body: dict = None):
    _set_user(user_id)
    from agent.tools.garden.plants import update_plant as _update
    return _result_or_404(_update.invoke({"plant_id": plant_id, **(body or {})}))


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


@data_router.patch("/garden/plants/batch/remove")
def batch_remove_plants(user_id: str, body: dict):
    """Soft delete for multiple plants — marks all as removed with a required reason."""
    _set_user(user_id)
    from agent.tools.garden.plants import batch_remove_plants as _batch_remove
    return {"result": _batch_remove.invoke(body)}


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
    from agent.tools.operations.activity import get_plant_activity as _get
    return _result_or_404(_get.invoke({"plant_id": plant_id, "limit": limit}))


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
    from agent.tools.operations.activity import get_batch_activity as _get
    return _result_or_404(_get.invoke({"batch_id": batch_id, "limit": limit}))


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
    return _result_or_404(approve_weather_task_changes.invoke({"change_set_id": changeset_id}))


# ---------------------------------------------------------------------------
# Incidents & treatment plans
# ---------------------------------------------------------------------------

def _get_incident_for_user(session, incident_id: str, user_id: str):
    """Return the incident if it belongs to the user, else None."""
    incident = session.query(IncidentReport).filter(IncidentReport.id == incident_id).first()
    if not incident:
        return None
    if incident.project_id:
        project = session.query(GardeningProject).filter(
            GardeningProject.id == incident.project_id,
            GardeningProject.user_id == user_id,
        ).first()
        if not project:
            return None
    return incident


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
    from agent.tools.operations.incidents import list_incidents as _list
    # Pass base params through the tool, apply additional filters in Python
    result_str = _list.invoke({"project_id": project_id, "status": status})
    # The tool returns a string; for the new filters we query directly
    session = SessionLocal()
    try:
        user_pids = {pid for (pid,) in session.query(GardeningProject.id).filter(
            GardeningProject.user_id == user_id).all()}
        query = session.query(IncidentReport).filter(
            or_(
                IncidentReport.project_id.in_(user_pids),
                IncidentReport.project_id.is_(None),
            )
        )
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
        return [
            {
                "id": inc.id,
                "incident_type": inc.incident_type,
                "status": inc.status,
                "severity": inc.severity,
                "summary": inc.summary,
                "notes": inc.notes,
                "project_id": inc.project_id,
                "detected_at": inc.detected_at,
                "created_at": inc.created_at,
            }
            for inc in incidents
        ]
    finally:
        session.close()


@data_router.post("/incidents")
def report_incident(user_id: str, body: ReportIncidentRequest):
    _set_user(user_id)
    from agent.tools.operations.incidents import report_incident as _report
    return {"result": _report.invoke(body.model_dump(exclude_none=True))}


@data_router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.incidents import get_incident as _get
    return _result_or_404(_get.invoke({"incident_id": incident_id}))


@data_router.patch("/incidents/{incident_id}")
def update_incident(incident_id: str, user_id: str, body: UpdateIncidentRequest):
    _set_user(user_id)
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
        return {
            "id": incident.id,
            "incident_type": incident.incident_type,
            "status": incident.status,
            "severity": incident.severity,
            "summary": incident.summary,
            "notes": incident.notes,
            "project_id": incident.project_id,
            "created_at": incident.created_at,
        }
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
def resolve_incident(incident_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.incidents import resolve_incident as _resolve
    return _result_or_404(_resolve.invoke({"incident_id": incident_id}))


@data_router.get("/incidents/{incident_id}/treatment")
def get_treatment_plan(incident_id: str, user_id: str):
    _set_user(user_id)
    from agent.tools.operations.incidents import get_treatment_plan as _get
    return _result_or_404(_get.invoke({"incident_id": incident_id}))


@data_router.post("/incidents/{incident_id}/treatment/manual")
def create_manual_treatment_plan(incident_id: str, user_id: str, body: CreateManualTreatmentPlanRequest):
    _set_user(user_id)
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
            follow_up_strategy=[body.follow_up_strategy] if body.follow_up_strategy else [],
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)
        return {
            "id": plan.id,
            "incident_id": plan.incident_id,
            "status": plan.status,
            "approach_summary": plan.approach_summary,
            "recommended_steps": plan.recommended_steps,
            "follow_up_strategy": plan.follow_up_strategy,
            "created_at": plan.created_at,
        }
    finally:
        session.close()


@data_router.patch("/treatment-plans/{plan_id}")
def update_treatment_plan(plan_id: str, user_id: str, body: UpdateTreatmentPlanRequest):
    _set_user(user_id)
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
            plan.follow_up_strategy = [body.follow_up_strategy] if isinstance(body.follow_up_strategy, str) else body.follow_up_strategy
        session.commit()
        session.refresh(plan)
        return {
            "id": plan.id,
            "incident_id": plan.incident_id,
            "status": plan.status,
            "approach_summary": plan.approach_summary,
            "recommended_steps": plan.recommended_steps,
            "follow_up_strategy": plan.follow_up_strategy,
            "created_at": plan.created_at,
        }
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
    from agent.tools.operations.incidents import approve_treatment_plan as _approve
    return _result_or_404(_approve.invoke({"treatment_plan_id": plan_id}))


@data_router.get("/incidents/{incident_id}/activity")
def get_incident_activity(incident_id: str, user_id: str, limit: int = 20):
    _set_user(user_id)
    from agent.tools.operations.activity import get_incident_activity as _get
    return _result_or_404(_get.invoke({"incident_id": incident_id, "limit": limit}))


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
    return _result_or_404(get_interaction_record.invoke({"interaction_id": interaction_id}))


@data_router.post("/interactions/{interaction_id}/resolve")
def resolve_interaction(interaction_id: str, user_id: str, body: ResolveInteractionRequest):
    _set_user(user_id)
    from agent.tools.operations.interactions import resolve_interaction as _resolve
    return _result_or_404(_resolve.invoke({"interaction_id": interaction_id, **body.model_dump(exclude_none=True)}))


# ---------------------------------------------------------------------------
# Threads — conversation management
# ---------------------------------------------------------------------------

@data_router.post("/threads")
def create_thread(user_id: str, body: CreateThreadRequest):
    """Register a thread ID generated by Cambium before the first chat turn."""
    uid = _set_user(user_id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session = SessionLocal()
    try:
        from db.models import Thread
        existing = session.query(Thread).filter(Thread.id == body.thread_id).first()
        if existing:
            return {"thread_id": existing.id, "created": False}
        session.add(Thread(
            id=body.thread_id,
            user_id=uid,
            title=body.title,
            project_id=body.project_id,
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
    uid = _set_user(user_id)
    session = SessionLocal()
    try:
        from db.models import Thread
        rows = (
            session.query(Thread)
            .filter(Thread.user_id == uid)
            .order_by(Thread.last_active_at.desc().nullslast())
            .limit(limit)
            .all()
        )
        return [
            {
                "thread_id": r.id,
                "title": r.title,
                "project_id": r.project_id,
                "last_message_preview": r.last_message_preview,
                "last_active_at": r.last_active_at.isoformat() if r.last_active_at else None,
                "message_count": r.message_count,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    finally:
        session.close()


@data_router.get("/threads/{thread_id}")
def get_thread(thread_id: str, user_id: str):
    """Get metadata for a specific thread."""
    uid = _set_user(user_id)
    session = SessionLocal()
    try:
        from db.models import Thread
        thread = (
            session.query(Thread)
            .filter(Thread.id == thread_id, Thread.user_id == uid)
            .first()
        )
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        return {
            "thread_id": thread.id,
            "title": thread.title,
            "project_id": thread.project_id,
            "last_message_preview": thread.last_message_preview,
            "last_active_at": thread.last_active_at.isoformat() if thread.last_active_at else None,
            "message_count": thread.message_count,
            "created_at": thread.created_at.isoformat(),
        }
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
        from db.models import Thread
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
    from agent.tools.operations.activity import list_recent_activity as _list
    return {"result": _list.invoke({
        "category": category, "event_type": event_type,
        "project_id": project_id, "subject_type": subject_type,
        "since": since, "before_timestamp": before_timestamp, "limit": limit,
    })}


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
