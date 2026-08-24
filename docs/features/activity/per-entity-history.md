# Per-Entity History

Per-entity history filters the activity log down to one subject so the user can
understand what happened to a specific plant, task, project, incident, or other
record.

## Current Behavior

Provides filtered activity views for plants, beds, containers, batches, tasks,
incidents, and projects.

## Supported Subjects

- Plants and plant batches.
- Beds and containers.
- Tasks and task series.
- Projects, proposals, revisions, and generation runs.
- Incidents and treatment plans.
- Weather change sets and interactions.

## Contract Notes

- The requested subject must be owned by the current user.
- A missing or unowned subject should return not found rather than an empty
  history that hides authorization mistakes.
- History should include events where the subject is direct or meaningfully
  linked through `ActivitySubject`.
- Cursor pagination should be stable across frontend refreshes.

## Related Docs

- [Activity Events](activity-events.md)
- [Garden Model](../garden/README.md)
