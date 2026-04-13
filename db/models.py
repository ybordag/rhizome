# db/models.py
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, Integer, Float, DateTime, Text, JSON, Boolean, ForeignKey, Index
from datetime import datetime
import uuid
from typing import Optional

def _fmt_date(d) -> str:
    return d.strftime("%B %d, %Y") if d else "not set"

# Step 1: define the base class all models inherit from
class Base(DeclarativeBase):
    pass


# Step 2: define your first model — one class = one table
class GardenProfile(Base):
    __tablename__ = "garden_profile"   # the actual table name in SQLite

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, nullable=False)
    climate_zone = Column(String, nullable=False)       # e.g. "9b"
    frost_date_last_spring = Column(String)             # e.g. "January 15"
    frost_date_first_fall = Column(String)              # e.g. "November 30"
    soil_type = Column(String)                          # e.g. "hard clay"
    tray_capacity = Column(Integer)                     # total trays available
    tray_indoor_capacity = Column(Integer)              # trays under grow lights
    location_label = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    hard_constraints = Column(JSON)                     # JSON string for now
    soft_preferences = Column(JSON)                     # JSON string for now
    notes = Column(Text)                                # anything that doesn't fit above
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<GardenProfile zone={self.climate_zone}>"
    
    def to_summary(self) -> str:
        return (
            f"[Garden] Zone {self.climate_zone} | "
            f"Last frost: {self.frost_date_last_spring or 'not set'} | "
            f"First frost: {self.frost_date_first_fall or 'not set'}\n"
            f"  Soil: {self.soil_type or 'unknown'}\n"
            f"  Trays: {self.tray_indoor_capacity if self.tray_indoor_capacity is not None else 'unknown'} indoor, "
            f"{self.tray_capacity if self.tray_capacity is not None else 'unknown'} total\n"
            f"  Weather location: {self.location_label or 'not set'}\n"
            f"  Created at: {_fmt_date(self.created_at)}"
        )
    
    def to_detailed(self) -> str:
        return (
            self.to_summary()
            + f"\n  Updated at: {_fmt_date(self.updated_at)}"
            + f"\n  Log:\n{self.notes or '  none'}"
        )


class GardeningProject(Base):
    __tablename__ = "gardening_project"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, nullable=False)
    garden_profile_id = Column(String, ForeignKey("garden_profile.id"), nullable=False)
    name = Column(String, nullable=False)
    goal = Column(String, nullable=False)
    status = Column(String, nullable=False, default="planning")
    tray_slots = Column(Integer)
    budget_ceiling = Column(Float)
    approved_plan = Column(JSON, nullable=True)
    negotiation_history = Column(JSON, default=list)
    iterations = Column(JSON, default=list)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<GardeningProject name={self.name}>"
    
    def to_summary(
        self,
        plant_count: int = 0,
        bed_count: int = 0,
        container_count: int = 0,
        batch_count: int = 0
    ) -> str:
        return (
            f"[Project] {self.name} (id: {self.id})\n"
            f"  Status: {self.status} | "
            f"Plants: {plant_count} | "
            f"Batches: {batch_count} | "
            f"Beds: {bed_count} | "
            f"Containers: {container_count}\n"
            f"  Goal: {self.goal}\n"
            f"  Created at: {_fmt_date(self.created_at)}"
        )

    def to_detailed(
        self,
        plant_count: int = 0,
        bed_count: int = 0,
        container_count: int = 0,
        batch_count: int = 0
    ) -> str:
        return (
            self.to_summary(
                plant_count=plant_count,
                bed_count=bed_count,
                container_count=container_count,
                batch_count=batch_count
            )
            + f"\n  Budget: ${self.budget_ceiling if self.budget_ceiling is not None else 'not set'} | "
            f"Tray slots: {self.tray_slots if self.tray_slots is not None else 0}\n"
            f"  Plan: {self.approved_plan.get('notes', 'none') if self.approved_plan else 'none'}\n"
            f"  Updated at: {_fmt_date(self.updated_at)}\n"
            f"  Notes: {self.notes or 'none'}"
        )


class ProjectBrief(Base):
    __tablename__ = "project_brief"
    __table_args__ = (
        Index("ix_project_brief_project_id", "project_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=False)
    status = Column(String, nullable=False, default="draft")
    goal = Column(Text, nullable=False)
    desired_outcome = Column(Text, nullable=True)
    target_start = Column(DateTime, nullable=True)
    target_completion = Column(DateTime, nullable=True)
    budget_cap = Column(Float, nullable=True)
    effort_preference = Column(String, nullable=True)
    propagation_preference = Column(String, nullable=True)
    priority_preferences = Column(JSON, default=list)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_summary(self) -> str:
        return (
            f"[Project Brief] {self.project_id} (id: {self.id})\n"
            f"  Status: {self.status}\n"
            f"  Goal: {self.goal}\n"
            f"  Desired outcome: {self.desired_outcome or 'not set'}\n"
            f"  Budget cap: ${self.budget_cap if self.budget_cap is not None else 'not set'}\n"
            f"  Target start: {_fmt_date(self.target_start)} | "
            f"Target completion: {_fmt_date(self.target_completion)}"
        )


class ProjectProposal(Base):
    __tablename__ = "project_proposal"
    __table_args__ = (
        Index("ix_project_proposal_project_id", "project_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=False)
    brief_id = Column(String, ForeignKey("project_brief.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="proposed")
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    recommended_approach = Column(Text, nullable=False)
    selected_locations = Column(JSON, default=list)
    selected_plants = Column(JSON, default=list)
    material_strategy = Column(JSON, default=dict)
    propagation_strategy = Column(JSON, default=dict)
    assumptions = Column(JSON, default=list)
    tradeoffs = Column(JSON, default=list)
    risks = Column(JSON, default=list)
    feasibility_notes = Column(JSON, default=list)
    cost_estimate = Column(JSON, default=dict)
    timeline_estimate = Column(JSON, default=dict)
    effort_estimate = Column(JSON, default=dict)
    maintenance_assumptions = Column(JSON, default=dict)
    resource_assumptions = Column(JSON, default=dict)
    budget_assumptions = Column(JSON, default=dict)
    timing_anchors = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_summary(self) -> str:
        total_cost = (self.cost_estimate or {}).get("total_estimated_cost", "not set")
        completion = (self.timeline_estimate or {}).get("expected_completion_date", "not set")
        effort = (self.effort_estimate or {}).get("total_hours", "not set")
        return (
            f"[Project Proposal] {self.title} (id: {self.id})\n"
            f"  Status: {self.status} | Version: {self.version}\n"
            f"  Estimated cost: ${total_cost}\n"
            f"  Expected completion: {completion}\n"
            f"  Estimated effort: {effort} hours\n"
            f"  Summary: {self.summary}"
        )


class ProjectRevision(Base):
    __tablename__ = "project_revision"
    __table_args__ = (
        Index("ix_project_revision_project_id", "project_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=False)
    source_proposal_id = Column(String, ForeignKey("project_proposal.id"), nullable=False)
    revision_number = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="active")
    approved_plan = Column(JSON, nullable=False, default=dict)
    approved_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    superseded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_summary(self) -> str:
        return (
            f"[Project Revision] {self.project_id} (id: {self.id})\n"
            f"  Revision: {self.revision_number} | Status: {self.status}\n"
            f"  Approved at: {_fmt_date(self.approved_at)}"
        )


class ProjectExecutionSpec(Base):
    __tablename__ = "project_execution_spec"
    __table_args__ = (
        Index("ix_project_execution_spec_project_id", "project_id"),
        Index("ix_project_execution_spec_revision_id", "revision_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=False)
    revision_id = Column(String, ForeignKey("project_revision.id"), nullable=False)
    status = Column(String, nullable=False, default="active")
    selected_plants = Column(JSON, default=list)
    selected_locations = Column(JSON, default=list)
    propagation_strategy = Column(JSON, default=dict)
    timing_windows = Column(JSON, default=dict)
    maintenance_assumptions = Column(JSON, default=dict)
    resource_assumptions = Column(JSON, default=dict)
    budget_assumptions = Column(JSON, default=dict)
    preferred_completion_target = Column(DateTime, nullable=True)
    plant_categories = Column(JSON, default=list)
    timing_anchors = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_summary(self) -> str:
        timing_modes = (self.timing_anchors or {}).get("modes", [])
        return (
            f"[Execution Spec] {self.project_id} (id: {self.id})\n"
            f"  Revision: {self.revision_id} | Status: {self.status}\n"
            f"  Plants: {len(self.selected_plants or [])} | "
            f"Locations: {len(self.selected_locations or [])}\n"
            f"  Timing modes: {', '.join(timing_modes) if timing_modes else 'calendar'}"
        )


class TaskGenerationRun(Base):
    __tablename__ = "task_generation_run"
    __table_args__ = (
        Index("ix_task_generation_run_project_id", "project_id"),
        Index("ix_task_generation_run_revision_id", "revision_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=False)
    revision_id = Column(String, ForeignKey("project_revision.id"), nullable=False)
    run_type = Column(String, nullable=False, default="initial")
    status = Column(String, nullable=False, default="complete")
    source_event_id = Column(String, ForeignKey("activity_event.id"), nullable=True)
    summary = Column(Text, nullable=False)
    run_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_summary(self) -> str:
        return (
            f"[Task Generation Run] {self.project_id} (id: {self.id})\n"
            f"  Revision: {self.revision_id} | Type: {self.run_type} | Status: {self.status}\n"
            f"  Summary: {self.summary}"
        )


class Task(Base):
    __tablename__ = "task"
    __table_args__ = (
        Index("ix_task_project_id", "project_id"),
        Index("ix_task_revision_id", "revision_id"),
        Index("ix_task_generation_run_id", "generation_run_id"),
        Index("ix_task_series_id", "series_id"),
        Index("ix_task_status", "status"),
        Index("ix_task_scheduled_date", "scheduled_date"),
        Index("ix_task_deadline", "deadline"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=False)
    revision_id = Column(String, ForeignKey("project_revision.id"), nullable=False)
    generation_run_id = Column(String, ForeignKey("task_generation_run.id"), nullable=False)
    parent_task_id = Column(String, ForeignKey("task.id"), nullable=True)
    series_id = Column(String, ForeignKey("task_series.id", use_alter=True), nullable=True)
    source_type = Column(String, nullable=False, default="generated")
    generator_key = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String, nullable=False, default="milestone")
    status = Column(String, nullable=False, default="pending")
    scheduled_date = Column(DateTime, nullable=True)
    earliest_start = Column(DateTime, nullable=True)
    window_start = Column(DateTime, nullable=True)
    window_end = Column(DateTime, nullable=True)
    deadline = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    deferred_until = Column(DateTime, nullable=True)
    estimated_minutes = Column(Integer, nullable=False, default=0)
    actual_minutes = Column(Integer, nullable=True)
    reversible = Column(Boolean, default=True)
    what_happens_if_skipped = Column(Text, nullable=True)
    what_happens_if_delayed = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    linked_subjects = Column(JSON, default=list)
    event_anchor_type = Column(String, nullable=True)
    event_anchor_subject_type = Column(String, nullable=True)
    event_anchor_subject_id = Column(String, nullable=True)
    event_anchor_offset_days = Column(Integer, nullable=True)
    is_user_modified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_summary(self) -> str:
        date_bits = []
        if self.scheduled_date:
            date_bits.append(f"scheduled {_fmt_date(self.scheduled_date)}")
        if self.deadline:
            date_bits.append(f"deadline {_fmt_date(self.deadline)}")
        timing = " | ".join(date_bits) if date_bits else "no date set"
        return (
            f"[Task] {self.title} (id: {self.id})\n"
            f"  Type: {self.type} | Status: {self.status}\n"
            f"  Timing: {timing}\n"
            f"  Estimated: {self.estimated_minutes} minutes"
        )


class TaskDependency(Base):
    __tablename__ = "task_dependency"
    __table_args__ = (
        Index("ix_task_dependency_blocking_task_id", "blocking_task_id"),
        Index("ix_task_dependency_blocked_task_id", "blocked_task_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    blocking_task_id = Column(String, ForeignKey("task.id"), nullable=False)
    blocked_task_id = Column(String, ForeignKey("task.id"), nullable=False)
    dependency_type = Column(String, nullable=False, default="finish_to_start")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaskSeries(Base):
    __tablename__ = "task_series"
    __table_args__ = (
        Index("ix_task_series_project_id", "project_id"),
        Index("ix_task_series_revision_id", "revision_id"),
        Index("ix_task_series_generation_run_id", "generation_run_id"),
        Index("ix_task_series_next_generation_date", "next_generation_date"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=False)
    revision_id = Column(String, ForeignKey("project_revision.id"), nullable=False)
    generation_run_id = Column(String, ForeignKey("task_generation_run.id"), nullable=False)
    parent_task_id = Column(String, ForeignKey("task.id"), nullable=True)
    source_type = Column(String, nullable=False, default="generated")
    generator_key = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    type = Column(String, nullable=False, default="maintenance")
    cadence = Column(String, nullable=False)
    cadence_days = Column(Integer, nullable=True)
    start_condition = Column(JSON, default=dict)
    end_condition = Column(JSON, default=dict)
    linked_subjects = Column(JSON, default=list)
    default_estimated_minutes = Column(Integer, nullable=False, default=0)
    next_generation_date = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_summary(self) -> str:
        return (
            f"[Task Series] {self.title} (id: {self.id})\n"
            f"  Type: {self.type} | Cadence: {self.cadence}\n"
            f"  Next generation: {_fmt_date(self.next_generation_date)} | Active: {self.active}"
        )


class Bed(Base):
    __tablename__ = "bed"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, nullable=False)
    garden_profile_id = Column(String, ForeignKey("garden_profile.id"), nullable=False)
    name = Column(String, nullable=False)
    location = Column(String)
    sunlight = Column(String)
    soil_type = Column(String)
    dimensions_sqft = Column(Float)
    last_watered_at = Column(DateTime, nullable=True)
    last_fertilized_at = Column(DateTime, nullable=True)
    last_amended_at = Column(DateTime, nullable=True)
    last_inspected_at = Column(DateTime, nullable=True)
    care_state_notes = Column(Text, nullable=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Bed name={self.name}>"
    
    def to_summary(self) -> str:
        return (
            f"[Bed] {self.name} (id: {self.id})\n"
            f"  Location: {self.location or 'unknown'} | "
            f"Sunlight: {self.sunlight or 'unknown'}\n"
            f"  Size: {self.dimensions_sqft if self.dimensions_sqft is not None else 'unknown'} sqft | "
            f"Soil: {self.soil_type or 'unknown'}\n"
            f"  Last watered: {_fmt_date(self.last_watered_at)} | "
            f"Last amended: {_fmt_date(self.last_amended_at)}\n"
            f"  Created at: {_fmt_date(self.created_at)}"
        )

    # beds don't have much more to say yet — to_detailed is the same
    # until we add the amendment log in Step 4
    def to_detailed(self) -> str:
        return (
            self.to_summary()
            + f"\n  Updated at: {_fmt_date(self.updated_at)}"
            f"\n  Notes: {self.notes or 'none'}"
        )


class Container(Base):
    __tablename__ = "container"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, nullable=False)
    garden_profile_id = Column(String, ForeignKey("garden_profile.id"), nullable=False)
    name = Column(String, nullable=False)
    container_type = Column(String)
    size_gallons = Column(Float)
    location = Column(String)
    is_mobile = Column(Boolean, default=True)
    last_watered_at = Column(DateTime, nullable=True)
    last_fertilized_at = Column(DateTime, nullable=True)
    last_amended_at = Column(DateTime, nullable=True)
    last_inspected_at = Column(DateTime, nullable=True)
    care_state_notes = Column(Text, nullable=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Container name={self.name}>"
    
    def to_summary(self) -> str:
        return (
            f"[Container] {self.name} (id: {self.id})\n"
            f"  Type: {self.container_type or 'unknown'} | "
            f"Size: {self.size_gallons if self.size_gallons is not None else 'unknown'} gal | "
            f"Location: {self.location or 'unknown'}"
            f"\n  Mobile: {self.is_mobile}\n"
            f"  Last watered: {_fmt_date(self.last_watered_at)} | "
            f"Last amended: {_fmt_date(self.last_amended_at)}\n"
            f"  Created at: {_fmt_date(self.created_at)}"
        )

    def to_detailed(self) -> str:
        return (
            self.to_summary()
            + f"\n  Updated at: {_fmt_date(self.updated_at)}\n"
            f"  Notes: {self.notes or 'none'}"
        )


class ProjectBed(Base):
    __tablename__ = "project_bed"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=False)
    bed_id = Column(String, ForeignKey("bed.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProjectContainer(Base):
    __tablename__ = "project_container"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=False)
    container_id = Column(String, ForeignKey("container.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Plant(Base):
    __tablename__ = "plant"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    garden_profile_id = Column(String, ForeignKey("garden_profile.id"), nullable=False)
    batch_id = Column(String, ForeignKey("plant_batch.id"), nullable=True)
    user_id = Column(Integer, nullable=False)

    name = Column(String, nullable=False)
    variety = Column(String)
    quantity = Column(Integer, default=1)

    # location
    container_id = Column(String, ForeignKey("container.id"), nullable=True)
    bed_id = Column(String, ForeignKey("bed.id"), nullable=True)

    # lifecycle
    source = Column(String)
    status = Column(String, default="planned")
    propagated_from = Column(String)

    # timing
    sow_date = Column(DateTime, nullable=True)
    red_cup_date = Column(DateTime, nullable=True)
    transplant_date = Column(DateTime, nullable=True)

    # growth state
    is_flowering = Column(Boolean, default=False)
    is_fruiting = Column(Boolean, default=False)

    # fertilizing
    fertilizing_schedule = Column(String, nullable=True)  # e.g. "every 2 weeks"
    last_watered_at = Column(DateTime, nullable=True)
    last_fertilized_at = Column(DateTime, nullable=True)
    last_inspected_at = Column(DateTime, nullable=True)
    last_treated_at = Column(DateTime, nullable=True)
    last_pruned_at = Column(DateTime, nullable=True)
    care_state_notes = Column(Text, nullable=True)

    # instructions
    special_instructions = Column(Text, nullable=True)

    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Plant {self.name} {self.variety or ''}>"

    def _state_text(self) -> str:
        states = []
        if self.is_flowering:
            states.append("flowering")
        if self.is_fruiting:
            states.append("fruiting")
        return ", ".join(states) if states else "not flowering/fruiting"

    def _location_text(self, location_name: Optional[str] = None) -> str:
        if location_name:
            return location_name
        if self.container_id:
            return f"container: {self.container_id}"
        if self.bed_id:
            return f"bed: {self.bed_id}"
        return "unassigned"

    def to_summary(self, location_name: Optional[str] = None) -> str:
        return (
            f"[Plant] {self.name} {self.variety or ''} (id: {self.id})\n"
            f"  Status: {self.status} | {self._state_text()}\n"
            f"  Location: {self._location_text(location_name)} | "
            f"Source: {self.source or 'unknown'}\n"
            f"  Created at: {_fmt_date(self.created_at)}"
        )

    def to_detailed(self, location_name: Optional[str] = None) -> str:
        return (
            self.to_summary(location_name)
            + (f"\n  Propagated from: {self.propagated_from}" if self.propagated_from else "")
            + f"\n  Batch: {self.batch_id or 'none'}"
            + f"\n  Sow: {_fmt_date(self.sow_date)} | "
            f"Red cup: {_fmt_date(self.red_cup_date)} | "
            f"Transplant: {_fmt_date(self.transplant_date)}\n"
            f"  Last watered: {_fmt_date(self.last_watered_at)} | "
            f"  Fertilizing: {self.fertilizing_schedule or 'not set'} | "
            f"Last fertilized: {_fmt_date(self.last_fertilized_at)}\n"
            f"  Last inspected: {_fmt_date(self.last_inspected_at)} | "
            f"Last treated: {_fmt_date(self.last_treated_at)} | "
            f"Last pruned: {_fmt_date(self.last_pruned_at)}\n"
            f"  Instructions: {self.special_instructions or 'none'}\n"
            f"  Care notes: {self.care_state_notes or 'none'}\n"
            f"  Notes: {self.notes or 'none'}\n"
            f"  Updated: {_fmt_date(self.updated_at)}"
        )


class PlantBatch(Base):
    __tablename__ = "plant_batch"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, nullable=False)
    garden_profile_id = Column(String, ForeignKey("garden_profile.id"), nullable=False)
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=True)

    name = Column(String, nullable=False)        # e.g. "Cosmos Spring 2026"
    plant_name = Column(String, nullable=False)
    variety = Column(String, nullable=True)
    quantity_sown = Column(Integer, nullable=False)

    # source — same values as Plant.source
    # 'seed', 'cutting', 'propagation', 'transplant', 'existing'
    source = Column(String, nullable=True)
    sow_date = Column(DateTime, nullable=True)   # for transplants, this is acquisition date

    # supplier info — works for seed packets, nurseries, friends, etc.
    supplier = Column(String, nullable=True)     # e.g. "Baker Creek", "OSH", "friend's garden"
    supplier_reference = Column(String, nullable=True)  # seed lot #, receipt #, variety tag, etc.

    # growing conditions — free text labels, no tables yet
    grow_light = Column(String, nullable=True)   # e.g. "light_1", "south window"
    tray = Column(String, nullable=True)         # e.g. "tray_A", "72-cell flat"

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_summary(self) -> str:
        date_str = self.sow_date.strftime("%B %d, %Y") if self.sow_date else "unknown"
        action = "acquired" if self.source in ("transplant", "existing") else "sown"
        return (
            f"[Batch] {self.name} (id: {self.id})\n"
            f"  Plant: {self.plant_name} {self.variety or ''} | "
            f"Source: {self.source or 'unknown'}\n"
            f"  Quantity {action}: {self.quantity_sown} on {date_str}\n"
            f"  Supplier: {self.supplier or 'not recorded'} | "
            f"Ref: {self.supplier_reference or 'none'}\n"
            f"  Light: {self.grow_light or 'not recorded'} | "
            f"Tray: {self.tray or 'not recorded'}\n"
            f"  Created at: {_fmt_date(self.created_at)}"
        )
    
    def to_detailed(self) -> str:
        return (
            self.to_summary()
            + f"\n  Updated at: {_fmt_date(self.updated_at)}"
            f"\n  Log:\n{self.notes or '  none'}"
        )
    
class ProjectPlant(Base):
    __tablename__ = "project_plant"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=False)
    plant_id = Column(String, ForeignKey("plant.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    removed_at = Column(DateTime, nullable=True)  # when decoupled, not deleted
    notes = Column(Text, nullable=True)           # why it was added/removed


class Conversation(Base):
    __tablename__ = "conversation"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, nullable=False)
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    summary = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Conversation id={self.id}>"


class ActivityEvent(Base):
    __tablename__ = "activity_event"
    __table_args__ = (
        Index("ix_activity_event_created_at", "created_at"),
        Index("ix_activity_event_project_id", "project_id"),
        Index("ix_activity_event_event_type", "event_type"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    actor_type = Column(String, nullable=False)
    actor_label = Column(String, nullable=True)

    event_type = Column(String, nullable=False)
    category = Column(String, nullable=False)

    summary = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)

    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=True)
    caused_by_event_id = Column(String, ForeignKey("activity_event.id"), nullable=True)
    conversation_id = Column(String, ForeignKey("conversation.id"), nullable=True)
    thread_id = Column(String, nullable=True)
    revision_id = Column(String, nullable=True)

    event_metadata = Column("metadata", JSON, nullable=True)


class ActivitySubject(Base):
    __tablename__ = "activity_subject"
    __table_args__ = (
        Index("ix_activity_subject_event_id", "event_id"),
        Index("ix_activity_subject_type_id", "subject_type", "subject_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id = Column(String, ForeignKey("activity_event.id"), nullable=False)

    subject_type = Column(String, nullable=False)
    subject_id = Column(String, nullable=False)
    role = Column(String, nullable=True)


class WeatherSnapshot(Base):
    __tablename__ = "weather_snapshot"
    __table_args__ = (
        Index("ix_weather_snapshot_created_at", "created_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    timezone = Column(String, nullable=False)
    location_label = Column(String, nullable=False)
    forecast_start_date = Column(DateTime, nullable=False)
    forecast_end_date = Column(DateTime, nullable=False)
    conditions_summary = Column(Text, nullable=False)
    alerts_summary = Column(Text, nullable=True)
    derived_impacts = Column(JSON, default=list)
    recommended_actions = Column(JSON, default=list)
    source = Column(String, nullable=False, default="open-meteo")
    raw_payload = Column(JSON, default=dict)


class WeatherTaskChangeSet(Base):
    __tablename__ = "weather_task_change_set"
    __table_args__ = (
        Index("ix_weather_task_change_set_weather_snapshot_id", "weather_snapshot_id"),
        Index("ix_weather_task_change_set_project_id", "project_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    weather_snapshot_id = Column(String, ForeignKey("weather_snapshot.id"), nullable=False)
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=True)
    status = Column(String, nullable=False, default="draft")
    summary = Column(Text, nullable=False)
    proposed_changes = Column(JSON, default=list)
    notes = Column(Text, nullable=True)
    approved_at = Column(DateTime, nullable=True)


class TriageSnapshot(Base):
    __tablename__ = "triage_snapshot"
    __table_args__ = (
        Index("ix_triage_snapshot_created_at", "created_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    timezone = Column(String, nullable=False)
    session_context = Column(JSON, default=dict)
    temporal_context = Column(JSON, default=dict)
    weather_snapshot_id = Column(String, ForeignKey("weather_snapshot.id"), nullable=True)
    recommended_task_ids = Column(JSON, default=list)
    urgent_task_ids = Column(JSON, default=list)
    routine_task_ids = Column(JSON, default=list)
    project_task_ids = Column(JSON, default=list)
    reasoning_summary = Column(Text, nullable=False)
    user_focus_summary = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)


class IncidentReport(Base):
    __tablename__ = "incident_report"
    __table_args__ = (
        Index("ix_incident_report_project_id", "project_id"),
        Index("ix_incident_report_status", "status"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=True)
    incident_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="reported")
    severity = Column(String, nullable=True)
    summary = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    reported_by = Column(String, nullable=False, default="user")
    detected_at = Column(DateTime, nullable=True)


class IncidentSubject(Base):
    __tablename__ = "incident_subject"
    __table_args__ = (
        Index("ix_incident_subject_incident_id", "incident_id"),
        Index("ix_incident_subject_type_id", "subject_type", "subject_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    incident_id = Column(String, ForeignKey("incident_report.id"), nullable=False)
    subject_type = Column(String, nullable=False)
    subject_id = Column(String, nullable=False)
    role = Column(String, nullable=True)


class TreatmentPlan(Base):
    __tablename__ = "treatment_plan"
    __table_args__ = (
        Index("ix_treatment_plan_incident_id", "incident_id"),
        Index("ix_treatment_plan_status", "status"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    incident_id = Column(String, ForeignKey("incident_report.id"), nullable=False)
    status = Column(String, nullable=False, default="draft")
    approach_summary = Column(Text, nullable=False)
    recommended_steps = Column(JSON, default=list)
    follow_up_strategy = Column(JSON, default=list)
    monitoring_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    approved_at = Column(DateTime, nullable=True)
