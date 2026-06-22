# Project Navigation

Project navigation collects the structured context needed to move around a
project: summary, progress, related work, linked garden records, blockers,
timeline, and budget or shopping context.

## Current Behavior

Lists projects, fetches project detail, and summarizes progress, timeline
health, budget, blockers, beds, containers, plants, and batches.

## Navigation Content

- Project list rows with status, priority, timing, and progress summaries.
- Project detail with brief, active proposal or revision, linked locations and
  plants, generated tasks, blockers, timeline health, expenses, and shopping
  items.
- Navigation targets for project tasks, timeline, activity, proposals, and
  linked garden entities.

## Contract Notes

- Project navigation is scoped by project ownership.
- Progress should be derived from structured task and project state, not stored
  prose.
- Blockers should include enough task IDs and dependency context for frontend
  drill-down.
- Budget and shopping summaries should tolerate missing or partial expense data.

## Related Docs

- [Project Planning](../projects/README.md)
- [Project Timeline](../activity/project-timeline.md)
