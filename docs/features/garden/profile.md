# Garden Profile

The garden profile stores the stable context Rhizome needs before it can give
useful garden advice: where the garden is, what conditions it has, and what
constraints or preferences should shape plans.

## Current Behavior

Tracks climate zone, frost dates, soil type, tray capacity, location, hard
constraints, soft preferences, and notes.

## User Workflows

- Create or update the profile during setup, chat, or structured API calls.
- Use profile location and climate data to drive weather, triage, and planning.
- Store hard constraints, such as space limits or chemical avoidance, separately
  from softer preferences.
- Retrieve the profile as structured data for frontend settings and dashboards.

## Contract Notes

- Profile reads should return an empty or incomplete profile shape gracefully
  when the user has not finished setup.
- Profile writes are scoped to `user_id`; each user has at most one profile.
- Agent tools may summarize profile gaps, but structured routes should return
  field-level data instead of prose.
- Profile updates should preserve omitted fields unless the request explicitly
  clears them.

## Related Docs

- [Garden Model](README.md)
- [Weather Snapshots](../weather/weather-snapshots.md)
- [Planning Context](../projects/planning-context.md)
