# Action History

Action history is Rhizome's append-only record of meaningful state changes,
care events, generated work, decisions, and project progress. It provides the
audit trail that lets users and the agent answer "what happened?" without
reconstructing history from the current row state.

## Feature Sets

- [Activity Events](activity-events.md)
- [Per-Entity History](per-entity-history.md)
- [Project Timeline](project-timeline.md)

## User Capabilities

- View a global activity feed across the garden.
- View history for a specific project, task, plant, batch, bed, container,
  incident, treatment plan, weather change set, or interaction.
- Review project timeline events alongside planning, task, and execution state.
- See before and after context for important changes.
- Use activity history as context for future chat planning and troubleshooting.

## Owned Domain Objects

- `ActivityEvent`
- `ActivitySubject`
- event metadata snapshots and subject links

## Invariants

- Activity events are scoped by `user_id`.
- Activity writes should happen in the same transaction as the domain mutation
  whenever practical.
- Events should be append-only. Corrections should produce new events rather
  than mutating past history, except for narrow data repair cases.
- Subject links should point to every entity that a user would reasonably
  expect to find the event under.
- Structured API routes return `ActivityEventView[]`, not prose summaries.
- Pagination and filtering should be stable enough for frontend feeds and
  project timelines.

## Runtime Surfaces

- Domain helpers record activity for garden, project, task, incident, weather,
  and interaction operations.
- Agent tools can summarize activity for the user.
- Internal data routes expose global, project, and per-entity activity feeds.

See [Data Model](../../architecture/data-model.md), [API Reference](../../architecture/api-reference.md),
and the connected feature docs for event-producing workflows.
