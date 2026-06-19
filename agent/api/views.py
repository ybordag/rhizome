"""
Pydantic view models for all data API responses.

Tools continue to return strings for the agent. These models define the
JSON shapes returned by data endpoints consumed by the frontend.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Garden — Profile
# ---------------------------------------------------------------------------

class GardenProfileView(BaseModel):
    id: str
    climate_zone: str
    frost_date_last_spring: Optional[str] = None
    frost_date_first_fall: Optional[str] = None
    soil_type: Optional[str] = None
    tray_capacity: Optional[int] = None
    tray_indoor_capacity: Optional[int] = None
    location_label: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    hard_constraints: Optional[list] = None
    soft_preferences: Optional[list] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Garden — Beds
# ---------------------------------------------------------------------------

class BedView(BaseModel):
    id: str
    name: str
    location: Optional[str] = None
    sunlight: Optional[str] = None
    soil_type: Optional[str] = None
    dimensions_sqft: Optional[float] = None
    last_watered_at: Optional[datetime] = None
    last_fertilized_at: Optional[datetime] = None
    last_amended_at: Optional[datetime] = None
    last_inspected_at: Optional[datetime] = None
    care_state_notes: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    available: Optional[bool] = None  # populated on project-scoped list endpoints


# ---------------------------------------------------------------------------
# Garden — Containers
# ---------------------------------------------------------------------------

class ContainerView(BaseModel):
    id: str
    name: str
    container_type: Optional[str] = None
    size_gallons: Optional[float] = None
    location: Optional[str] = None
    is_mobile: bool = True
    last_watered_at: Optional[datetime] = None
    last_fertilized_at: Optional[datetime] = None
    last_amended_at: Optional[datetime] = None
    last_inspected_at: Optional[datetime] = None
    care_state_notes: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    available: Optional[bool] = None  # populated on project-scoped list endpoints


# ---------------------------------------------------------------------------
# Garden — Plants
# ---------------------------------------------------------------------------

class PlantSummaryView(BaseModel):
    id: str
    name: str
    variety: Optional[str] = None
    quantity: int = 1
    status: str
    source: Optional[str] = None
    bed_id: Optional[str] = None
    container_id: Optional[str] = None
    batch_id: Optional[str] = None
    location_name: Optional[str] = None
    is_flowering: bool = False
    is_fruiting: bool = False
    sow_date: Optional[datetime] = None
    transplant_date: Optional[datetime] = None
    created_at: datetime


class PlantDetailView(PlantSummaryView):
    propagated_from: Optional[str] = None
    red_cup_date: Optional[datetime] = None
    fertilizing_schedule: Optional[str] = None
    special_instructions: Optional[str] = None
    last_watered_at: Optional[datetime] = None
    last_fertilized_at: Optional[datetime] = None
    last_inspected_at: Optional[datetime] = None
    last_treated_at: Optional[datetime] = None
    last_pruned_at: Optional[datetime] = None
    care_state_notes: Optional[str] = None
    notes: Optional[str] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Care state (shared across bed / container / plant)
# ---------------------------------------------------------------------------

class CareStateView(BaseModel):
    subject_type: str
    subject_id: str
    last_watered_at: Optional[datetime] = None
    last_fertilized_at: Optional[datetime] = None
    last_amended_at: Optional[datetime] = None
    last_inspected_at: Optional[datetime] = None
    last_treated_at: Optional[datetime] = None
    last_pruned_at: Optional[datetime] = None
    care_state_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class TaskSummaryView(BaseModel):
    id: str
    project_id: str
    title: str
    type: str
    status: str
    priority: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    earliest_start: Optional[datetime] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    deadline: Optional[datetime] = None
    estimated_minutes: int = 0
    is_user_modified: bool = False
    created_at: datetime
    # Computed fields — present in daily/due priority views
    urgency: Optional[str] = None
    blocked: Optional[bool] = None
    due_date: Optional[datetime] = None
    score: Optional[int] = None


class TaskDetailView(TaskSummaryView):
    description: Optional[str] = None
    series_id: Optional[str] = None
    source_type: str = "generated"
    generator_key: str = ""
    completed_at: Optional[datetime] = None
    deferred_until: Optional[datetime] = None
    actual_minutes: Optional[int] = None
    reversible: bool = True
    what_happens_if_skipped: Optional[str] = None
    what_happens_if_delayed: Optional[str] = None
    linked_subjects: list = []
    notes: Optional[str] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectSummaryView(BaseModel):
    id: str
    name: str
    goal: str
    status: str
    tray_slots: Optional[int] = None
    budget_ceiling: Optional[float] = None
    notes: Optional[str] = None
    plant_count: int = 0
    bed_count: int = 0
    container_count: int = 0
    batch_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None


class ProjectDetailView(ProjectSummaryView):
    approved_plan: Optional[Any] = None
