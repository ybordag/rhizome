# Recurring Tasks and Regeneration

Recurring tasks model repeated care work. Regeneration reconciles generated
tasks after a project plan changes without destroying user edits.

## Current Behavior

`TaskSeries` defines recurring care work. Materialization rolls out task
instances on a fixed horizon. Regeneration supersedes replaceable generated
tasks while preserving user-modified tasks.

## User Workflows

- Create recurring care work from an accepted project plan.
- Materialize upcoming task instances on a rolling horizon.
- Update a project plan and regenerate its generated work.
- Preserve manually edited tasks while replacing stale generated tasks.
- Inspect which generation run produced a task.

## Contract Notes

- Series materialization should be idempotent for an unchanged horizon.
- Generated task rows should retain source metadata for project, revision,
  series, and generation run.
- Regeneration should mark replaced tasks `superseded` instead of deleting
  historical rows.
- User-modified tasks are not replaceable generated rows.
- Activity should make regeneration visible without overwhelming the feed.

## Related Docs

- [Task Generation](task-generation.md)
- [Project Timeline](../activity/project-timeline.md)
