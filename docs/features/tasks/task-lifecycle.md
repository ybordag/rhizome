# Task Lifecycle

Task lifecycle behavior defines how work moves from planned to done, skipped,
deferred, blocked, or superseded.

## Current Behavior

Tasks move through `pending`, `in_progress`, `done`, `skipped`, `deferred`,
`blocked`, and `superseded`. Completing tasks can unblock dependents and apply
care side effects.

## User Workflows

- Start work to mark a task `in_progress`.
- Complete work and apply any linked care or progress side effects.
- Skip work with a reason when it should not be done.
- Defer work to a later date and preserve the reason.
- Delete low-risk tasks or use confirmation flows for consequential removal.

## Contract Notes

- Status transitions should be idempotent when repeated commands do not change
  state.
- Completion should validate that blockers are resolved before applying side
  effects.
- User-modified generated tasks must be preserved during regeneration.
- Lifecycle changes should emit activity with enough metadata to explain the
  before and after state.
- Structured task views should expose status, urgency, blocked state, due date,
  and project context for frontend workflows.

## Related Docs

- [Care State](../garden/care-state.md)
- [Dependencies and Event Anchors](dependencies-anchors.md)
- [Activity Events](../activity/activity-events.md)
