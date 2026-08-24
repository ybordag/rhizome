# Dependencies and Event Anchors

Dependencies and event anchors prevent Rhizome from presenting work before the
garden is ready for it.

## Current Behavior

Tasks can depend on other tasks or wait for biological event anchors such as
germination or transplant readiness.

## Dependency Types

- Direct task dependencies, where one task blocks another until completion.
- Event anchors, where a task waits for a garden event or biological milestone.
- Generated dependencies derived from a project execution spec.
- Manual dependencies added or changed by the user.

## Contract Notes

- Blocked-state computation should consider unfinished dependency tasks and
  unresolved event anchors.
- Blocked tasks remain visible through blocked-task routes and explanations.
- Deferring a task should cascade only to direct dependents when the domain
  rules require preserving relative timing.
- Completing or resolving a blocker should make dependents eligible without
  requiring manual repair.
- Dependency reads must include enough IDs for frontend graph rendering.

## Related Docs

- [Task Lifecycle](task-lifecycle.md)
- [Daily Priority Work List](../triage/daily-priority-work-list.md)
