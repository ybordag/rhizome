# Rhizome Activity Log Specification

**Status:** Proposed  
**Last updated:** 2026-04-11

---

## Purpose

This document defines the intended activity log design for Rhizome.

The activity log is meant to provide meaningful historical context across the
garden system, especially for:

- projects
- tasks
- beds
- containers
- plants

It should support both:

- user-facing history and explainability
- internal debugging, planning traceability, and later task/planner integration

This document is a specification, not an implementation plan.

---

## Core design principle

Rhizome should not treat the activity log as a raw stream of low-level database
mutations.

Instead, the activity log should primarily record **meaningful domain events**.

Examples:

- `project_plan_approved`
- `plant_transplanted`
- `bed_soil_amended`
- `container_watered`
- `task_completed`

This is different from simply logging:

- field `x` changed from `a` to `b`

Low-level field diffs are still useful, but they should be attached as metadata
to meaningful events rather than defining the entire history model.

---

## Why not just log every object change?

A pure running object-change log is not sufficient because:

- it captures mutation but not intent
- it is noisy and quickly becomes unreadable
- it does not represent multi-object actions well
- it does not explain causality
- it is weak for planner/tracker workflows where revisions and task generation
  are more important than individual field updates

For Rhizome, we want the history system to answer:

- what happened?
- why did it happen?
- what objects were affected?
- who or what triggered it?
- what task, plan, or revision caused it?

That requires an event model, not just a database audit trail.

---

## Proposed data model

The activity log should be built around two core tables:

1. `ActivityEvent`
2. `ActivitySubject`

### `ActivityEvent`

One row per meaningful event.

Suggested shape:

```python
class ActivityEvent(Base):
    __tablename__ = "activity_event"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # who/what caused the event
    actor_type = Column(String, nullable=False)     # 'user', 'agent', 'system'
    actor_label = Column(String, nullable=True)     # free text for now

    # event identity
    event_type = Column(String, nullable=False)     # e.g. 'plant_transplanted'
    category = Column(String, nullable=False)       # 'project', 'task', 'plant', 'bed', 'container', 'garden'

    # display
    summary = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)

    # grouping / causality
    project_id = Column(String, ForeignKey("gardening_project.id"), nullable=True)
    task_id = Column(String, ForeignKey("task.id"), nullable=True)
    caused_by_event_id = Column(String, ForeignKey("activity_event.id"), nullable=True)
    conversation_id = Column(String, ForeignKey("conversation.id"), nullable=True)
    thread_id = Column(String, nullable=True)
    revision_id = Column(String, nullable=True)

    # structured detail
    metadata = Column(JSON, nullable=True)
```

### `ActivitySubject`

An event may affect more than one object, so the event should not belong to
only one row/object.

Suggested shape:

```python
class ActivitySubject(Base):
    __tablename__ = "activity_subject"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id = Column(String, ForeignKey("activity_event.id"), nullable=False)

    subject_type = Column(String, nullable=False)   # 'project', 'task', 'plant', 'bed', 'container', 'batch'
    subject_id = Column(String, nullable=False)

    role = Column(String, nullable=True)            # 'primary', 'affected', 'generated_from', 'target'
```

This allows one event to reference:

- the primary object being acted on
- additional affected objects
- a task that caused the event
- a project the event belongs to

---

## Event metadata conventions

`ActivityEvent.metadata` should remain flexible, but the shape should be
consistent enough for future querying and rendering.

Recommended common keys:

```json
{
  "before": {},
  "after": {},
  "changed_fields": [],
  "reason": "",
  "timing": {},
  "measurements": {},
  "task_effect": {}
}
```

Not every event needs all of these keys.

### Recommended usage

- `before`
  - selected pre-change snapshot fields
- `after`
  - selected post-change snapshot fields
- `changed_fields`
  - list of fields materially changed
- `reason`
  - human reason or machine reason for the event
- `timing`
  - dates and timestamps relevant to the event
- `measurements`
  - watering amounts, fertilizer strength, amendment quantities, etc.
- `task_effect`
  - used when a completed task causes downstream care/logging events

---

## Object-specific event taxonomy

The following event types are the intended design vocabulary.

This list does not need to be fully implemented at once, but it should guide
schema and helper design.

### Projects

Suggested event types:

- `project_created`
- `project_updated`
- `project_status_changed`
- `project_plan_proposed`
- `project_plan_approved`
- `project_plan_rejected`
- `project_plan_revised`
- `project_budget_changed`
- `project_constraint_changed`
- `project_timeline_changed`
- `project_completed`
- `project_deleted`

Useful metadata:

- changed fields
- old/new budget
- target completion date
- constraints diff
- revision summary
- replanning rationale

### Tasks

Suggested event types:

- `task_created`
- `task_updated`
- `task_status_changed`
- `task_started`
- `task_completed`
- `task_skipped`
- `task_deferred`
- `task_blocked`
- `task_unblocked`
- `task_superseded`
- `task_dependency_added`
- `task_dependency_removed`
- `task_regenerated`

Useful metadata:

- status before/after
- scheduled/deadline changes
- estimated minutes
- completion notes
- blocker reason
- generated/manual source

### Beds

Suggested event types:

- `bed_created`
- `bed_updated`
- `bed_soil_changed`
- `bed_soil_amended`
- `bed_mulched`
- `bed_watered`
- `bed_fertilized`
- `bed_planted`
- `bed_cleared`
- `bed_deleted`

Useful metadata:

- soil type before/after
- amendment type
- amendment amount
- mulch type
- watering method/amount
- affected plants
- condition notes

Example metadata:

```json
{
  "before": {"soil_type": "hard clay"},
  "after": {"soil_type": "clay loam"},
  "reason": "improve drainage",
  "measurements": {
    "amendment_type": "compost",
    "amount": "2 bags"
  }
}
```

### Containers

Suggested event types:

- `container_created`
- `container_updated`
- `container_moved`
- `container_filled`
- `container_soil_amended`
- `container_watered`
- `container_fertilized`
- `container_planted`
- `container_emptied`
- `container_removed`

Useful metadata:

- old/new location
- soil changes
- watering/fertilizing details
- container notes
- affected plants

### Plants

Suggested event types:

- `plant_created`
- `plant_updated`
- `plant_status_changed`
- `plant_sown`
- `plant_germinated`
- `plant_potted_up`
- `plant_transplanted`
- `plant_flowering_started`
- `plant_fruiting_started`
- `plant_fertilized`
- `plant_watered`
- `plant_pruned`
- `plant_harvested`
- `plant_issue_recorded`
- `plant_removed`
- `plant_deleted`

Useful metadata:

- sow date
- red-cup / pot-up date
- transplant date
- old/new location
- old/new status
- issue type
- harvest quantity
- care notes

Example transplant metadata:

```json
{
  "reason": "roots filling tray cells",
  "timing": {
    "transplant_date": "2026-04-11"
  },
  "before": {
    "location_type": "tray"
  },
  "after": {
    "location_type": "container",
    "location_id": "container-123"
  }
}
```

---

## Automatic care events from task completion

The activity log is expected to integrate with the task system later.

Important design rule:

- completing a care task should create a `task_completed` event
- and may also create one or more downstream physical-world care events

Examples:

- completing a watering task may create:
  - `task_completed`
  - `bed_watered`
  - `container_watered`
  - `plant_watered`

- completing a fertilizing task may create:
  - `task_completed`
  - `bed_fertilized`
  - `container_fertilized`
  - `plant_fertilized`

The care event should reference the task event via `caused_by_event_id` so the
history remains causal and traceable.

### Example

Event 1:

- `event_type = "task_completed"`
- primary subject = task

Event 2:

- `event_type = "container_watered"`
- primary subject = container
- affected subjects = plants in that container
- `caused_by_event_id = <task_completed_event_id>`

This allows Rhizome to answer:

- when was this task completed?
- when was this container last watered?
- which task caused that watering record?

---

## Standard care-event metadata

For watering, fertilizing, pruning, and similar recurring care events, metadata
should use a consistent shape where possible.

### Watering

```json
{
  "timing": {
    "performed_at": "2026-04-11T18:30:00Z"
  },
  "measurements": {
    "method": "hand watering",
    "amount": "moderate"
  },
  "notes": "top inch was dry",
  "task_effect": {
    "source_task_id": "task-123"
  }
}
```

### Fertilizing

```json
{
  "timing": {
    "performed_at": "2026-04-11T18:30:00Z"
  },
  "measurements": {
    "fertilizer": "liquid kelp",
    "strength": "half strength"
  },
  "notes": "weekly feed"
}
```

---

## Current-state fields vs historical events

For some care actions, Rhizome will likely want both:

1. a current-state field on the main object
2. a historical event in the activity log

Examples:

- `plant.last_fertilized_at`
- `plant.last_watered_at`
- `bed.last_amended_at`
- `container.last_watered_at`

The rule should be:

- object fields support current-state reasoning
- activity events support history, explainability, and auditability

Both are useful and are not redundant.

---

## Recommended first implementation slice

The first pass does not need to cover the full taxonomy.

A practical v1 event set should include:

### Projects

- `project_created`
- `project_updated`
- `project_status_changed`

### Tasks

- `task_created`
- `task_completed`
- `task_skipped`
- `task_deferred`

### Beds

- `bed_created`
- `bed_updated`
- `bed_soil_amended`
- `bed_watered`

### Containers

- `container_created`
- `container_updated`
- `container_moved`
- `container_watered`
- `container_soil_amended`

### Plants

- `plant_created`
- `plant_status_changed`
- `plant_sown`
- `plant_potted_up`
- `plant_transplanted`
- `plant_watered`
- `plant_fertilized`
- `plant_removed`

This first pass is enough to validate:

- the schema
- the event-writing helper API
- object-specific histories
- future task/care integration

---

## Intended future usage

Once implemented, the activity log should support:

- a project history view
- a plant history view
- a bed/container maintenance timeline
- task-driven care history
- planner/tracker revision traceability
- “what changed and why?” explanations from the agent

This activity log is intended to become one of the temporal foundations of
Rhizome alongside the planner and task tracker.
