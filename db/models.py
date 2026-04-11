# db/models.py
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, String, Integer, Float, DateTime, Text, JSON, Boolean, ForeignKey
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
    last_fertilized_at = Column(DateTime, nullable=True)

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
            f"  Fertilizing: {self.fertilizing_schedule or 'not set'} | "
            f"Last fertilized: {_fmt_date(self.last_fertilized_at)}\n"
            f"  Instructions: {self.special_instructions or 'none'}\n"
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
