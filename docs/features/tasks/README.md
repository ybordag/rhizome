# Task Management

Task management is Rhizome's durable work graph. Tasks may be created directly
by the user, generated from accepted project plans, created by treatment or
weather approvals, or materialized from recurring task series.

The task layer should make daily execution simple while preserving enough
structure for dependencies, recurrence, regeneration, triage, and activity
history.

## Feature Sets

- [Task Generation](task-generation.md)
- [Task Lifecycle](task-lifecycle.md)
- [Dependencies and Event Anchors](dependencies-anchors.md)
- [Recurring Tasks and Regeneration](recurrence-regeneration.md)

## User Capabilities

- Create, inspect, update, start, complete, skip, defer, and delete tasks.
- View daily, due, blocked, upcoming, project, and generated task lists.
- Track dependencies so tasks wait for prerequisite tasks or event anchors.
- Materialize recurring task instances from a `TaskSeries`.
- Regenerate project tasks from an accepted execution spec without losing user
  edits.
- Connect task completion to care state, project progress, incidents, weather
  changes, and activity history.

## Owned Domain Objects

- `Task`
- `TaskDependency`
- `TaskSeries`
- `TaskGenerationRun`
- task activity events and task-related interaction records

## Invariants

- Blocked tasks are returned as structured `TaskSummaryView[]` with
  `blocked: true`, urgency, and due-date fields populated where available.
- A task is blocked when an unfinished dependency or unresolved event anchor
  prevents execution.
- Task lifecycle changes should be idempotent where possible and should emit
  activity events for meaningful state changes.
- Completing a task may update care state or project progress when the task is
  linked to those entities.
- Skipping a task requires an explicit reason. Deferring a task should preserve
  the reason and cascade only where the dependency model calls for it.
- Generated task regeneration must supersede replaceable generated tasks while
  preserving tasks the user has modified.
- Task reads and writes must enforce `user_id` through the task, project, or
  owning garden record.

## Runtime Surfaces

- Agent tools expose task creation, lifecycle changes, daily planning, blocked
  work, recurring work, and project task generation.
- Internal data routes expose structured task lists and task detail responses
  for Cambium and Verdant.
- Triage, weather, incidents, projects, and activity all consume task state.

See [Daily Triage](../triage/README.md), [Project Planning](../projects/README.md),
and [API Reference](../../architecture/api-reference.md) for the most common
cross-feature paths.
