# Task Lifecycle

TODO: Document task status transitions and user workflows.

## Current Capability

Tasks move through `pending`, `in_progress`, `done`, `skipped`, `deferred`,
`blocked`, and `superseded`. Completing tasks can unblock dependents and apply
care side effects.

## To Document

- Status transition rules
- Start/complete/skip/defer behavior
- User-modified task handling
- Care side effects
- Error cases
- Open questions
