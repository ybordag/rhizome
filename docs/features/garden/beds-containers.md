# Beds and Containers

Beds and containers represent the usable growing locations inside a garden.
They provide capacity, sunlight, soil, mobility, and assignment context for
planning and task work.

## Current Behavior

Tracks named beds and containers, including location, size/capacity, sunlight,
soil, mobility, notes, project assignment, and care history.

## User Workflows

- Add, inspect, update, and remove beds or containers.
- Assign locations to projects and review assignment conflicts before accepting
  a plan.
- Use location metadata to choose suitable plants and task timing.
- Record bed or container care such as watering, amending, moving, or cleaning.
- Navigate from a location to plants, batches, tasks, projects, and activity.

## Contract Notes

- Bed and container records are scoped to the owning user's garden profile.
- Location names are user-facing labels and should not be treated as global
  identifiers.
- Planning should consider active project assignments when determining
  availability.
- Removal should preserve historical activity and linked records where domain
  rules allow it.
- Structured location endpoints should verify ownership before returning related
  plants or activity.

## Related Docs

- [Location Navigation](../search/location-navigation.md)
- [Project Planning Context](../projects/planning-context.md)
- [Care State](care-state.md)
