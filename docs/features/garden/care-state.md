# Care State

Care state captures the most recent maintenance activity for plants, beds, and
containers so Rhizome can answer what needs attention and explain why.

## Current Behavior

Plants, beds, and containers track last care timestamps and notes. Completing
care-related tasks updates linked subjects automatically.

## User Workflows

- Record watering, fertilizing, pruning, treatment, harvest, repotting, moving,
  and removal events.
- Complete care-related tasks and have linked care fields update automatically.
- Review care history for an entity through activity feeds.
- Let triage rank care work using due dates, recent care state, weather, and
  task urgency.

## Contract Notes

- Care state is the current summary; activity history is the durable event log.
- Task completion side effects should be explicit and limited to linked
  subjects.
- Repeating an already-applied care action should avoid duplicate activity when
  no meaningful state changed.
- Care timestamps should remain nullable so imported or partial records are
  usable.

## Related Docs

- [Task Lifecycle](../tasks/task-lifecycle.md)
- [Daily Priority Work List](../triage/daily-priority-work-list.md)
- [Per-Entity History](../activity/per-entity-history.md)
