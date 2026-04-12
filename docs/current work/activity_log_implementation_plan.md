# Activity Log Implementation Plan

**Status:** Phase 1 implemented  
**Last updated:** 2026-04-11

---

## Purpose

This document turns the activity log specification into a concrete phase 1
implementation plan for the current Rhizome codebase.

Phase 1 is intentionally limited to entities that already exist and are fully
managed by Rhizome today:

- projects
- beds
- containers
- plants
- batches
- project assignment/link changes

This phase is meant to establish the activity log as a usable backend feature:

- events are recorded at write time
- the agent can query history for a specific object
- a future frontend can call into stable history-query APIs

---

## Current status

Phase 1 of the activity log has been implemented in Rhizome.

Completed work:

- added `ActivityEvent` and `ActivitySubject` persistence models
- added centralized activity-log writer/query helpers
- instrumented current project, bed, container, plant, batch, and assignment
  mutation paths
- added history query tools for projects, plants, beds, containers, and batches
- added automated test coverage for schema, helper behavior, write-path
  instrumentation, and queries

GitHub tracking:

- issue [#58](https://github.com/ybordag/rhizome/issues/58) is complete and
  closed
- follow-up issue [#57](https://github.com/ybordag/rhizome/issues/57) remains
  open for later task-driven care events and current-state care fields

This document now serves as both the phase 1 implementation record and the
reference for what remains deferred.

---

## Phase 1 scope

### Included

- `ActivityEvent` persistence model
- `ActivitySubject` join model
- centralized helper module for writing and querying events
- instrumentation of current mutation tools
- history-query tools for projects, plants, beds, containers, and batches
- tests for schema, helper behavior, write-path instrumentation, and queries

### Explicitly deferred

- task model support
- task-completion-driven care events
- planner revisions and revision history
- current-state care fields like `last_watered_at` and `last_amended_at`
- frontend timeline UI
- profile/garden-wide history unless needed later

Task-driven care events will later connect through `caused_by_event_id`.

---

## Event taxonomy for phase 1

### Projects

- `project_created`
- `project_updated`
- `project_status_changed`
- `project_deleted`
- `project_bed_assigned`
- `project_bed_unassigned`
- `project_container_assigned`
- `project_container_unassigned`
- `project_plant_added`
- `project_plant_removed`

### Beds

- `bed_updated`
- `bed_deleted`

### Containers

- `container_created`
- `container_updated`
- `container_moved`
- `container_removed`

### Plants

- `plant_created`
- `plant_updated`
- `plant_status_changed`
- `plant_sown`
- `plant_transplanted`
- `plant_fertilized`
- `plant_removed`
- `plant_deleted`

### Batches

- `batch_created`
- `batch_updated`
- `batch_deleted`

Rules:

- prefer the most specific semantic event when a clear one exists
- fall back to generic `*_updated` when multiple fields change together
- include `reason` in metadata when removal or deletion tools accept it

---

## Write-path integration points

### Project tools

Write events in:

- `create_project`
- `update_project`
- `assign_bed_to_project`
- `assign_container_to_project`
- `unassign_bed_from_project`
- `unassign_container_from_project`
- `add_plant_to_project`
- `remove_plant_from_project`
- `delete_project`

### Bed and container tools

Write events in:

- `update_bed`
- `add_container`
- `update_container`
- `remove_container`
- `delete_bed`

### Plant and batch tools

Write events in:

- `add_plant`
- `update_plant`
- `remove_plant`
- `batch_add_plant_type`
- `batch_update_plants`
- `batch_remove_plants`
- `delete_plant`
- `delete_batch`

### Write-path rules

- record events using the same SQLAlchemy session as the object mutation
- do not persist events when the underlying write rolls back
- use coarse actor defaults for now:
  - `actor_type="agent"`
  - `actor_label="rhizome_tool"`

---

## History query API / tool surface

Phase 1 should expose the following history entry points:

- `get_project_activity(project_id, limit=20, event_type=None)`
- `get_plant_activity(plant_id, limit=20, event_type=None)`
- `get_bed_activity(bed_id, limit=20, event_type=None)`
- `get_container_activity(container_id, limit=20, event_type=None)`
- `get_batch_activity(batch_id, limit=20, event_type=None)`
- `list_recent_activity(project_id=None, subject_type=None, limit=50)`

These outputs should remain:

- stable
- human-readable
- simple to wrap in a future frontend API

Each activity entry should include:

- timestamp
- event type
- summary
- optional notes
- optional affected-subject hints

---

## Rollout order

1. add schema
   Status: complete
2. add activity-log helper module
   Status: complete
3. add query helpers and history tools
   Status: complete
4. instrument current mutation tools
   Status: complete
5. add tests for models/helpers
   Status: complete
6. add tests for write-path instrumentation
   Status: complete
7. add tests for history queries
   Status: complete

---

## Acceptance criteria

Phase 1 acceptance criteria have been met:

- Rhizome records meaningful activity events for current mutation tools
- object history can be fetched for projects, plants, beds, containers, and
  batches
- recent project-scoped activity can be fetched
- event writes roll back with failed writes
- history formatting is stable enough for agent use and future frontend
  wrapping
- phase 1 was completed without introducing task models or frontend UI work

---

## Future hook for tasks

When task tracking is implemented later:

- task completion will write a `task_completed` event
- downstream care events like `plant_watered` or `container_watered` will
  reference the triggering event through `caused_by_event_id`

This means the phase 1 schema should support causality now, even though
task-specific activity is deferred.
