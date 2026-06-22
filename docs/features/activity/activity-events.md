# Activity Events

Activity events are the durable audit entries Rhizome writes when user-visible
state changes or an important decision is made.

## Current Behavior

Records creates, updates, deletes, and domain activity with actor, category,
event type, summary, metadata, project link, thread link, revision link, and
subjects.

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

## Related Docs

- [Per-Entity History](per-entity-history.md)
- [Project Timeline](project-timeline.md)
