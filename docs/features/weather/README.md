# Weather

Weather support lets Rhizome interpret forecast conditions against the user's
garden and task plan. It should help the user prepare for heat, frost, rain,
wind, and watering windows without silently changing committed work.

## Feature Sets

- [Weather Snapshots](weather-snapshots.md)
- [Weather Task Impacts](weather-task-impacts.md)
- [Weather Change Approvals](weather-change-approvals.md)

## User Capabilities

- Fetch or view the latest weather snapshot for the garden profile location.
- Understand forecast risks and opportunities in the context of current tasks
  and plants.
- Draft weather-driven task changes when forecast conditions make existing work
  unsafe, urgent, or poorly timed.
- Review and approve weather task change sets before they mutate the task graph.
- Receive persisted monitor alerts for severe or operationally important
  weather conditions.

## Owned Domain Objects

- `WeatherSnapshot`
- `WeatherTaskChangeSet`
- `MonitorAlert`
- weather-related activity events and task links

## Invariants

- Weather snapshots are scoped through the current user's garden profile.
- Forecast fetching should degrade gracefully when a profile location is
  missing or the upstream service is unavailable.
- Weather task changes remain drafts until approved through a structured
  interaction or structured API route.
- Approving a weather task change set should update affected tasks, record
  activity, and return a structured `WeatherTaskChangeSetView`.
- A change set cannot be approved twice.
- Monitor alerts should be persisted so Cambium and Verdant can render them
  outside the live chat session.

## Runtime Surfaces

- Agent tools expose weather summaries, task impact analysis, and approval
  flows.
- The graph can load compact weather context into the system prompt.
- Internal data routes expose weather snapshots, task impacts, change sets,
  approval, monitor alerts, and live monitor streams.

See [Human-in-the-Loop Interactions](../interactions/README.md),
[Task Management](../tasks/README.md), and [API Reference](../../architecture/api-reference.md)
for approval and route details.
