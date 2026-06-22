# Triage Snapshots

Triage snapshots persist the reasoning Rhizome uses to summarize what matters
at the start of a session or monitor pass.

## Current Behavior

Builds a persisted snapshot at session start with reasoning summary,
recommended task IDs, urgent/routine/project groupings, weather context, and
temporal context.

## Inputs

- Active, due, blocked, and project-linked tasks.
- Garden profile and temporal context.
- Weather snapshot and monitor alerts when available.
- Session context from the thread opening or explicit user override.
- Recent activity that affects priority or urgency.

## Contract Notes

- Structured responses resolve task IDs into `TaskSummaryView[]` groups.
- The snapshot can include LLM-authored reasoning, but task membership and
  ownership should come from structured domain queries.
- Missing inputs should lower confidence or narrow the summary rather than
  failing the session.
- Snapshot records are historical; a new pass should create or update a fresh
  current snapshot instead of rewriting unrelated old records.

## Related Docs

- [Daily Priority Work List](daily-priority-work-list.md)
- [Agent Loop](../../architecture/agent-loop.md)
