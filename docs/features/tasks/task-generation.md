# Task Generation

Task generation turns an accepted project execution spec into durable work. It
is the write-side counterpart to schedule preview.

## Current Behavior

Creates section headers, milestones, maintenance tasks, recurring series, event
anchors, dependencies, and an initial rolling horizon from an accepted project
execution spec.

## Generated Work

- Section and milestone tasks for project structure.
- One-time setup, planting, transplant, maintenance, harvest, and cleanup tasks.
- Recurring `TaskSeries` records plus the initial materialized task horizon.
- Dependency edges between prerequisite and dependent work.
- Event anchors for biological milestones such as germination or transplant
  readiness.

## Contract Notes

- Generation requires an accepted proposal or active execution spec.
- Generated tasks should link back to project, revision, generation run, and
  relevant garden subjects.
- Activity should record the generation run, not every derived row as a separate
  high-noise event unless it is user-meaningful.
- Regeneration should supersede replaceable generated tasks and preserve user
  edits.

## Related Docs

- [Proposals and Revisions](../projects/proposals-revisions.md)
- [Recurring Tasks and Regeneration](recurrence-regeneration.md)
