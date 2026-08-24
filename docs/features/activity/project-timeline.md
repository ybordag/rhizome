# Project Timeline

The project timeline is the project-scoped view of activity history. It ties
planning, approvals, generated work, task progress, garden changes, incidents,
weather changes, and expenses into one chronological account.

## Current Behavior

Shows cross-object history for a project with category and event-type filters,
cursor pagination, and linked subjects.

## Timeline Content

- Project creation and status changes.
- Brief, proposal, revision, and schedule-preview events.
- Task generation, task lifecycle, and recurring work events.
- Location, plant, incident, treatment, weather, shopping, and expense events
  linked to the project.
- Interaction resolutions related to project decisions.

## Contract Notes

- Timeline ordering should be reverse chronological by default for feeds and
  stable under cursor pagination.
- Filters should support category and event type without changing ownership
  checks.
- Linked subjects should let the frontend navigate from a timeline row to the
  relevant task, plant, incident, proposal, or interaction.
- The timeline should include cross-object events only when they are explicitly
  linked to the project.

## Related Docs

- [Project Planning](../projects/README.md)
- [Activity Events](activity-events.md)
