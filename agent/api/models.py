"""Pydantic request/response models for the internal API."""

from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator


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
    priority_preferences: Optional[list[str]] = None
    notes: Optional[str] = None
    status: Optional[str] = None


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
    initial_context: Optional[list[dict]] = None


class UpdateSessionContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available_minutes: Optional[int] = None
    energy_level: Optional[str] = None
    focus_project_id: Optional[str] = None
    preferred_location_type: Optional[str] = None
    open_to_outdoor_work: Optional[bool] = None
    wants_quick_wins: Optional[bool] = None

    @field_validator("available_minutes")
    @classmethod
    def _positive_minutes(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("available_minutes must be >= 0")
        return value

    @field_validator("energy_level")
    @classmethod
    def _valid_energy(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in {"low", "medium", "high"}:
            raise ValueError("energy_level must be one of low, medium, high")
        return value

    @field_validator("preferred_location_type")
    @classmethod
    def _valid_location_type(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in {"bed", "container"}:
            raise ValueError("preferred_location_type must be one of bed, container")
        return value


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


class CreateTaskSeriesRequest(BaseModel):
    project_id: str
    title_template: str
    type: str
    priority: Optional[str] = "normal"
    estimated_minutes: Optional[int] = 0
    cadence: str
    window_days: Optional[int] = None
    linked_subjects: Optional[list] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    reversible: Optional[bool] = True


class TaskDateUpdate(BaseModel):
    task_id: str
    scheduled_date: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    deadline: Optional[str] = None


class BulkTaskUpdateRequest(BaseModel):
    updates: list[TaskDateUpdate]


class CreateCalendarAnnotationRequest(BaseModel):
    date: str   # ISO date
    content: str
    category: Optional[str] = None
    color: Optional[str] = None


class UpdateCalendarAnnotationRequest(BaseModel):
    content: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None


class CreateProjectExpenseRequest(BaseModel):
    name: str
    category: str
    estimated_cost: Optional[float] = None
    actual_cost: Optional[float] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    supplier: Optional[str] = None
    purchased_at: Optional[str] = None
    status: Optional[str] = "needed"
    notes: Optional[str] = None


class UpdateProjectExpenseRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    estimated_cost: Optional[float] = None
    actual_cost: Optional[float] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    supplier: Optional[str] = None
    purchased_at: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class CreateShoppingItemRequest(BaseModel):
    name: str
    category: str
    project_id: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    estimated_cost: Optional[float] = None
    supplier: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = "normal"


class UpdateShoppingItemRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    project_id: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    estimated_cost: Optional[float] = None
    supplier: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None


class RecordCareRequest(BaseModel):
    care_type: str  # watered | fertilized | amended | inspected | treated | pruned
    notes: Optional[str] = None
    recorded_at: Optional[str] = None  # ISO datetime; defaults to now


class UpdateIncidentRequest(BaseModel):
    summary: Optional[str] = None
    severity: Optional[str] = None
    notes: Optional[str] = None
    incident_type: Optional[str] = None


class ResolveIncidentRequest(BaseModel):
    notes: Optional[str] = None


class CreateManualTreatmentPlanRequest(BaseModel):
    approach_summary: str
    recommended_steps: list = []
    follow_up_strategy: Optional[str] = None


class UpdateTreatmentPlanRequest(BaseModel):
    approach_summary: Optional[str] = None
    recommended_steps: Optional[list] = None
    follow_up_strategy: Optional[str] = None
