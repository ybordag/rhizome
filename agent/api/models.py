"""Pydantic request/response models for the internal API."""

from typing import Optional
from pydantic import BaseModel


class AgentRequest(BaseModel):
    user_id: str
    thread_id: str
    message: str
    provider: Optional[str] = None
    provider_key: Optional[str] = None
    model: Optional[str] = None


class AgentResponse(BaseModel):
    thread_id: str
    response: str
    # interaction contains the interrupt payload when the graph pauses for user input
    interaction: Optional[dict] = None


class ResumeRequest(BaseModel):
    user_id: str
    thread_id: str
    resolution: str


class DismissAlertRequest(BaseModel):
    pass


class TaskActionRequest(BaseModel):
    notes: Optional[str] = None


class DeferTaskRequest(BaseModel):
    defer_until: str  # ISO date string
    notes: Optional[str] = None


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    scheduled_date: Optional[str] = None
    deadline: Optional[str] = None
    estimated_minutes: Optional[int] = None
    notes: Optional[str] = None


class CreateProjectRequest(BaseModel):
    name: str
    goal: str
    budget_ceiling: Optional[float] = None
    tray_slots: Optional[int] = None
    notes: Optional[str] = None


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    goal: Optional[str] = None
    status: Optional[str] = None
    budget_ceiling: Optional[float] = None
    tray_slots: Optional[int] = None
    notes: Optional[str] = None


class UpdateBriefRequest(BaseModel):
    goal: Optional[str] = None
    desired_outcome: Optional[str] = None
    target_start: Optional[str] = None
    target_completion: Optional[str] = None
    budget_cap: Optional[float] = None
    effort_preference: Optional[str] = None
    propagation_preference: Optional[str] = None
    notes: Optional[str] = None


class AssignLocationsRequest(BaseModel):
    bed_ids: Optional[list[str]] = None
    container_ids: Optional[list[str]] = None


class ReportIncidentRequest(BaseModel):
    incident_type: str
    severity: Optional[str] = None
    summary: str
    subjects: Optional[list[dict]] = None
    notes: Optional[str] = None


class ResolveInteractionRequest(BaseModel):
    action: str
    notes: Optional[str] = None


class UpdateTaskSeriesRequest(BaseModel):
    cadence: Optional[str] = None
    cadence_days: Optional[int] = None
    active: Optional[bool] = None
    notes: Optional[str] = None


class CreateThreadRequest(BaseModel):
    thread_id: str
    title: Optional[str] = None
    project_id: Optional[str] = None


class CreateTaskRequest(BaseModel):
    project_id: str
    title: str
    type: str  # milestone | maintenance | emergency | opportunistic
    priority: Optional[str] = "normal"
    scheduled_date: Optional[str] = None
    earliest_start: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    deadline: Optional[str] = None
    estimated_minutes: Optional[int] = 0
    notes: Optional[str] = None
    linked_subjects: Optional[list] = None
    reversible: Optional[bool] = True


class CreateBedRequest(BaseModel):
    name: str
    location: Optional[str] = None
    size: Optional[str] = None
    sunlight: Optional[str] = None
    soil_type: Optional[str] = None
    notes: Optional[str] = None
