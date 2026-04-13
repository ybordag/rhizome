# Phase 4: Operational Triage, Weather Context, and Reactive Care

## Status

Implemented on `geranium`.

Phase 4 adds the first time-aware operational layer on top of the planner,
tracker, and activity-log foundations. It introduces:

- minimal temporal grounding at session start
- persisted weather snapshots
- persisted triage snapshots
- weather-aware task recommendations
- care-state fields and task-driven semantic care events
- user-reported incident and treatment-plan workflows

This phase still intentionally stops short of:

- a full calendar or event engine
- generalized temporal reasoning across all conversations
- autonomous long-horizon replanning
- image-driven diagnosis
- area-wide external pest monitoring

## Scope

Implemented in this phase:

- `TemporalContext` runtime/session support
- `WeatherSnapshot`, `WeatherTaskChangeSet`, and weather-impact analysis
- `TriageSnapshot` and session-start triage
- care-state timestamps and notes on plants, containers, and beds
- semantic care events written from supported task completions
- incident reporting for pests, blight, and weeds
- approval-gated `TreatmentPlan` workflows
- approval-gated weather draft task changes
- Phase 4 unit and integration tests

Explicitly deferred:

- background triage automation
- image-assisted diagnosis
- autonomous weather-triggered schedule rewrites
- generalized temporal reasoning beyond the session/runtime layer
- broader external pest-report integrations

## Persistence and Runtime Model

### Runtime/session state

Phase 4 extends the graph/runtime with:

- `temporal_context`
- `session_context`
- `weather_context`
- `triage_snapshot`

These are populated through:

1. `session_context_intake`
2. `weather_context_loader`
3. `triage_reasoner`

The runtime now grounds the session in:

- current time/date
- timezone
- today/tomorrow
- latest weather snapshot metadata
- latest triage snapshot metadata

### New persisted records

Phase 4 adds the following persistence types in
[models.py](/Users/yashi/Documents/Work/Code/Gardening%20Agent/rhizome/db/models.py):

- `WeatherSnapshot`
- `WeatherTaskChangeSet`
- `TriageSnapshot`
- `IncidentReport`
- `IncidentSubject`
- `TreatmentPlan`

### Care-state fields

Current-state care fields were added to:

- `Plant`
  - `last_watered_at`
  - `last_fertilized_at`
  - `last_inspected_at`
  - `last_treated_at`
  - `last_pruned_at`
  - `care_state_notes`
- `Container`
  - `last_watered_at`
  - `last_fertilized_at`
  - `last_amended_at`
  - `last_inspected_at`
  - `care_state_notes`
- `Bed`
  - `last_watered_at`
  - `last_fertilized_at`
  - `last_amended_at`
  - `last_inspected_at`
  - `care_state_notes`

The garden profile also now supports weather location grounding through:

- `location_label`
- `latitude`
- `longitude`

## Weather and Triage Behavior

### Weather snapshots

Weather snapshots are refreshed explicitly through the weather tools and then
consumed at session time by the graph/runtime.

Current weather impact derivation supports:

- heat
- frost
- heavy rain
- storm/high wind
- favorable planting window

### Triage

Daily triage now groups recommended work into:

- `Urgent`
- `Routine`
- `Project Work`

The triage flow considers:

- runtime urgency from the tracker
- the user’s available time and energy
- project focus in the opening message
- location preference cues from the opening message
- latest weather impacts

The triage snapshot is persisted so the frontend/API layer can retrieve the
latest operational view directly.

## Reactive Care and Incident Workflows

### Task-driven care events

Completing supported care tasks now updates current-state fields and writes
semantic activity events. Supported care actions in this phase include:

- watering
- fertilizing / feeding
- amendment work
- pruning
- inspection
- simple treatment tasks

### Incident workflow

Phase 4 adds a user-reported incident path for:

- pests
- blight / disease
- weeds

Workflow:

1. report incident
2. create `IncidentReport`
3. link affected objects via `IncidentSubject`
4. draft `TreatmentPlan`
5. require approval
6. create treatment/follow-up tasks on approval
7. feed task completion back into care state and activity history

Treatment recommendations remain organic-first by default.

## Public Tools

New Phase 4 tools:

- `refresh_weather_snapshot`
- `get_latest_weather_snapshot`
- `list_weather_impacted_tasks`
- `draft_weather_task_changes`
- `approve_weather_task_changes`
- `run_daily_triage`
- `get_latest_triage_snapshot`
- `list_triage_recommendations`
- `get_current_care_state`
- `get_recent_care_history`
- `report_incident`
- `draft_treatment_plan`
- `get_treatment_plan`
- `approve_treatment_plan`
- `resolve_incident`

The existing `complete_task` tool was also extended so supported care and
treatment tasks update care-state fields and emit semantic care events.

## Test Coverage

Phase 4 coverage was added in:

- [test_phase4_helpers.py](/Users/yashi/Documents/Work/Code/Gardening%20Agent/rhizome/tests/db/test_phase4_helpers.py)
- [test_phase4_operations.py](/Users/yashi/Documents/Work/Code/Gardening%20Agent/rhizome/tests/tools/test_phase4_operations.py)

Covered behaviors include:

- timezone-aware temporal context
- session-context inference
- weather-impact derivation
- weather-aware triage output
- weather draft/approval workflow
- care-state updates from task completion
- semantic care history queries
- incident reporting and treatment-task generation

## Follow-On Work

The main remaining follow-on areas are:

- richer background automation for weather and triage
- generalized temporal reasoning
- image-driven pest/blight diagnosis
- broader reactive monitoring integrations
- downstream care-event expansion beyond the current supported set
