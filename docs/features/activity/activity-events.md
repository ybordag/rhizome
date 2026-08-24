# Activity Events

Activity events are the durable audit entries Rhizome writes when user-visible
state changes or an important decision is made.

## Current Behavior

Records creates, updates, deletes, and domain activity with actor, category,
event type, summary, metadata, project link, thread link, revision link, and
subjects.

Thread context pin/unpin operations are recorded as activity events:

- `thread_context_pinned`
- `thread_context_unpinned`

These events are linked to the thread and to the pinned/unpinned entity. They
represent metadata changes on `Thread.pinned_context`; they do not imply that
the underlying plant, task, project, incident, bed, container, or batch was
mutated.

## Event Content

- Actor type and label, such as user, agent, monitor, or system.
- Category and event type.
- Summary, notes, and structured metadata.
- Optional project, thread, revision, and source links.
- One or more `ActivitySubject` records for affected entities.

## Contract Notes

- Events should be understandable without rehydrating the entire current domain
  object.
- Before and after metadata should be included for meaningful changes when it
  helps explain what changed.
- Activity writes should be transactionally close to the domain mutation.
- Repeated no-op updates should not create noisy duplicate events.
- Structured API responses use `ActivityEventView` and `ActivitySubjectView`.
- Telemetry payloads for database changes should be structural and sanitized:
  entity type/id, field/action, counts, and activity event ids are appropriate;
  raw prompt text, notes, profile details, and other sensitive free text are not.

## Telemetry Relationship

Activity events are durable product/audit records. Runtime telemetry is separate:
SQLAlchemy session hooks emit sanitized `database_change` snapshots after
committed ORM writes, including tenant context, table/model, record id,
operation, and changed field names for updates. These telemetry snapshots are
useful for operations and debugging, but they are not a substitute for semantic
activity events when the change should be visible in user-facing history.

## Related Docs

- [Per-Entity History](per-entity-history.md)
- [Project Timeline](project-timeline.md)
