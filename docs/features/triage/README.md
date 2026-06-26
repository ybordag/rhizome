# Daily Triage

Daily triage decides what deserves the user's attention now. It combines tasks,
weather, seasonality, session context, monitor alerts, and garden state into a
small set of priorities that the agent can explain and the frontend can render.

Triage is not a separate planning system. It summarizes and ranks existing work
and context so the user can act without re-reading the whole garden state.

## Feature Sets

- [Triage Snapshots](triage-snapshots.md)
- [Daily Priority Work List](daily-priority-work-list.md)

## User Capabilities

- Start a chat session with an immediate sense of urgent, routine, and
  project-related work.
- View the latest triage snapshot through a structured API response.
- Request daily work, due work, blocked work, or a refreshed monitor pass.
- See weather and monitor alerts folded into the reasoning behind priorities.
- Keep session context explicit so the agent can distinguish planning,
  catch-up, harvest, maintenance, and emergency modes without forcing the
  user's words into numeric/enum filters.

## Owned Domain Objects

- `TriageSnapshot`
- text-first session-context fields on `Thread`
- monitor alert references included in graph state

## Invariants

- `GET /triage/latest` returns grouped `TaskSummaryView[]` objects for urgent,
  routine, and project tasks rather than bare task IDs or prose.
- The old `GET /triage/recommendations` contract has been removed. Consumers
  should use `GET /triage/latest`, task list routes, or chat triage envelopes.
- Triage snapshots should be scoped to the current user and derived from that
  user's profile, tasks, projects, weather, and monitor alerts.
- Thread session context is prompt context, not an automatic task filter:
  `focus_text`, `time_text`, `energy_text`, and `focus_context` should not
  hard-filter candidate tasks unless a future explicit triage filter contract
  is added.
- Missing profile, weather, or task data should produce an honest low-context
  snapshot rather than a failed session.
- Triage explanations should identify the reasoning without duplicating the
  full task list in prose.

## Runtime Surfaces

- The graph builds or loads triage context during session startup.
- Agent responses may include a structured `triage_view` interaction envelope
  when the user needs a reviewable priority list.
- Internal data routes expose latest triage, daily tasks, due tasks, blocked
  tasks, and monitor-triggered refreshes.

See [Agent Loop](../../architecture/agent-loop.md), [Task Management](../tasks/README.md),
and [Weather](../weather/README.md) for the main inputs to triage.
