# Phase 3: Task Tracker and Persistent Task Generation

## Status

Implemented on `geranium`.

Phase 3 adds the persistent task tracker on top of the completed planner and activity-log foundations. It turns accepted project revisions into stored task graphs, supports recurring care through `TaskSeries` plus rolling task instances, and exposes lifecycle/query tools the agent can use during execution.

This phase intentionally stops short of full daily triage. Urgency is computed at runtime, and event-driven scheduling support is intentionally basic.

## Scope

Implemented in this phase:
- `Task`, `TaskDependency`, `TaskSeries`, and `TaskGenerationRun`
- persistent task generation from accepted `ProjectRevision` and active `ProjectExecutionSpec`
- milestone-task generation
- dependency creation
- recurring care series creation
- rolling recurring-task materialization
- task lifecycle tools
- runtime urgency computation
- task activity-log integration
- unit and integration tests for tracker behavior

Explicitly deferred:
- full daily triage / prioritization workflow
- advanced weather-aware scheduling
- broad activity-log-triggered replanning
- rich downstream care-event emission beyond the current task history layer
- frontend task UI

## Persistence Model

Phase 3 introduces four new tables in [models.py](/Users/yashi/Documents/Work/Code/Gardening%20Agent/rhizome/db/models.py):

- `Task`
  - concrete actionable work item
  - supports milestone and recurring-instance tasks
  - stores timing fields, lifecycle state, provenance, and optional event-anchor fields

- `TaskDependency`
  - links one task to another using a `finish_to_start` dependency model

- `TaskSeries`
  - stores recurring care rules
  - tracks cadence, linked subjects, and `next_generation_date`

- `TaskGenerationRun`
  - records each generation or regeneration pass
  - provides provenance for generated tasks and recurring series

Lifecycle/status model:
- `pending`
- `in_progress`
- `done`
- `skipped`
- `deferred`
- `blocked`
- `superseded`

Important implementation decisions:
- urgency is not stored as a primary DB field
- `TaskSeries` stores recurring rules; only near-term `Task` instances are materialized
- `is_user_modified` protects edited tasks from blind regeneration overwrites
- regeneration supersedes replaceable future tasks rather than deleting history

## Generation Pipeline

The tracker consumes accepted `ProjectRevision` and `ProjectExecutionSpec` records through [tracker.py](/Users/yashi/Documents/Work/Code/Gardening%20Agent/rhizome/agent/tracker.py).

Implemented generation steps:

1. `TaskGenerationRun` creation
2. stable section-task creation for:
   - Setup
   - Propagation
   - Establishment
   - Ongoing care
   - Maintenance mode / harvest
3. milestone-task generation
4. dependency creation
5. recurring-series generation
6. rolling materialization of near-term recurring instances

Current milestone generation includes:
- location preparation
- seed sowing
- pot-up / red-cup transition
- start acquisition
- transplanting
- support installation
- harvest-window checks
- basic event-anchored follow-ups when supported anchor events are present

Current recurring-series generation includes:
- watering
- inspection
- fertilizing
- pruning for fruiting-vine profiles

Recurring materialization rules:
- default rolling horizon: 14 days
- no duplicate future instances are created for the same series/date
- `next_generation_date` advances as instances are materialized

## Query and Lifecycle Tools

Tracker tools live in [tracker.py](/Users/yashi/Documents/Work/Code/Gardening%20Agent/rhizome/agent/tools/tracker.py).

Generation and regeneration:
- `generate_project_tasks`
- `regenerate_project_tasks`
- `materialize_recurring_tasks`

Read/query:
- `list_project_tasks`
- `get_task`
- `list_due_tasks`
- `list_blocked_tasks`
- `list_task_series`
- `explain_task_blockers`

Lifecycle updates:
- `start_task`
- `complete_task`
- `skip_task`
- `defer_task`
- `update_task`
- `update_task_series`

Runtime helpers:
- `compute_task_urgency`
- `compute_task_blocked_state`
- `list_materializable_series`
- `build_due_task_view`

Urgency model:
- `backlog`
- `scheduled`
- `time_sensitive`
- `blocker`

Urgency is computed from:
- `deadline`
- `window_end`
- `scheduled_date`
- `deferred_until`
- dependency state

## Activity-Log Integration

Phase 3 extends the existing activity log with tracker events:

- `task_generation_run_created`
- `task_created`
- `task_updated`
- `task_started`
- `task_completed`
- `task_skipped`
- `task_deferred`
- `task_blocked`
- `task_superseded`
- `task_series_created`
- `task_series_updated`
- `task_instances_materialized`

These events are queryable through the existing activity-history tools, so project history now includes planner, task-generation, and task-lifecycle actions in one timeline.

## Test Coverage

Tracker tests were added in:
- [test_tracker.py](/Users/yashi/Documents/Work/Code/Gardening%20Agent/rhizome/tests/db/test_tracker.py)
- [test_task_tracker_tools.py](/Users/yashi/Documents/Work/Code/Gardening%20Agent/rhizome/tests/tools/test_task_tracker_tools.py)

Covered behaviors include:
- model creation and linking
- urgency boundaries
- defer/reappear behavior
- dependency blocking
- recurring-series materialization without duplication
- event-anchor task generation
- milestone generation for seed-start vs starts-based plans
- regeneration supersession while preserving completed history
- task lifecycle tools
- recurring-series updates
- activity-log emission and rollback behavior

## Follow-On Work

The next major phase remains daily triage and richer reactive planning.

Still open for later:
- [#20](https://github.com/ybordag/rhizome/issues/20) daily triage
- [#57](https://github.com/ybordag/rhizome/issues/57) richer task-driven care events and current-state care fields
- [#12](https://github.com/ybordag/rhizome/issues/12) task-field expansion
- [#13](https://github.com/ybordag/rhizome/issues/13) richer weather-aware scheduling
