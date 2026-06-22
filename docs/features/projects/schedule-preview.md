# Schedule Preview

Schedule preview shows the work Rhizome would create from a proposal or active
revision without writing tasks. It gives the user a chance to inspect workload,
timing, and dependencies before committing.

## Current Behavior

Generates a preview of the task graph and recurring series that would be
created from a proposal or active revision without writing tasks.

## Preview Content

- One-time tasks, section headers, milestones, and maintenance tasks.
- Recurring task series that would be created.
- Dependency edges and event anchors.
- Date windows, priority defaults, and linked garden subjects.

## Contract Notes

- Preview is read-only and should not create tasks, series, generation runs, or
  activity events that imply committed work.
- Preview output should use the same generation logic as acceptance wherever
  practical so the preview is trustworthy.
- Warnings about conflicts, missing dates, or unbound event anchors should be
  visible in the preview response.
- A stale preview should be regenerated after proposal or garden context
  changes.

## Related Docs

- [Task Generation](../tasks/task-generation.md)
- [Dependencies and Event Anchors](../tasks/dependencies-anchors.md)
