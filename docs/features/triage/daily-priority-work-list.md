# Daily Priority Work List

The daily priority work list ranks actionable tasks for the current day. It is
the operational view behind "what should I do now?"

## Current Behavior

Scores active tasks using urgency, task type, priority, blocker effects, triage
alignment, and blocked-state penalties.

## Ranking Inputs

- Task status, due date, priority, type, and project context.
- Blocked state and blocker effects.
- Weather impacts and monitor alerts.
- Session context, such as maintenance, harvest, planning, or emergency mode.
- Recent activity and care state.

## Contract Notes

- Daily and due routes should return structured `TaskSummaryView[]`.
- Blocked tasks may be shown separately so the user understands why work is not
  currently actionable.
- Ranking should be deterministic for the same persisted state unless an LLM
  triage snapshot is explicitly refreshed.
- Limits and filters should preserve the highest-priority urgent work before
  routine work.

## Related Docs

- [Task Management](../tasks/README.md)
- [Weather Task Impacts](../weather/weather-task-impacts.md)
