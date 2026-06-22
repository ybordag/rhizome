# Weather Change Approvals

Weather change approvals protect the task graph from silent forecast-driven
mutation. Rhizome can draft changes, but the user approves them before normal
task updates are applied.

## Current Behavior

Drafts task change sets from weather impacts and applies them only after
structured user approval, except critical monitor paths handled by background
monitoring policy.

## Change-Set Content

- Source weather snapshot.
- Summary of why changes are recommended.
- Affected task IDs and proposed date, priority, or status changes.
- Status, creation time, approval time, and activity links.

## Contract Notes

- Draft change sets should not mutate tasks.
- Approval returns a structured `WeatherTaskChangeSetView` with affected
  `TaskSummaryView[]`.
- Already-approved change sets should fail instead of applying twice.
- Rejection or cancellation should preserve the record for audit without
  changing tasks.
- Any auto-apply monitor path must be narrow, documented, and visible through
  activity or monitor alerts.

## Related Docs

- [Structured Approvals](../interactions/structured-approvals.md)
- [Task Lifecycle](../tasks/task-lifecycle.md)
