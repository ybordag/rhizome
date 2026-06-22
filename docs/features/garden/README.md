# Garden Model

The garden model is Rhizome's persistent representation of the user's physical
growing space. It gives the agent and API a shared source of truth for garden
profile settings, beds, containers, plants, batches, and care state.

The model is intentionally operational rather than catalog-like: records should
answer what exists, where it is, what condition it is in, what project or task
owns the next action, and what has happened to it recently.

## Feature Sets

- [Garden Profile](profile.md)
- [Beds and Containers](beds-containers.md)
- [Plants and Batches](plants-batches.md)
- [Care State](care-state.md)

## User Capabilities

- Maintain a garden profile with location, climate, household, and preference
  context that informs planning, triage, and weather interpretation.
- Add and update beds, containers, plants, and planted batches.
- Track plant lifecycle state, including active, harvested, failed, and removed
  plants.
- Record care actions such as watering, fertilizing, pruning, treating,
  repotting, harvesting, moving, and removal.
- Search the garden by plant, batch, bed, container, status, and location.
- Link physical garden records to projects and tasks so work can be planned and
  reviewed against the actual space.

## Owned Domain Objects

- `GardenProfile`
- `Bed`
- `Container`
- `Plant`
- `PlantBatch`
- care-state fields on plants, beds, and containers
- activity events and subjects emitted by garden mutations

## Invariants

- Garden records are always scoped by `user_id`; the agent and internal API must
  never read or mutate another user's garden state.
- Each user has at most one garden profile. Missing profile data should degrade
  gracefully in chat, triage, and weather flows.
- Removed plants remain historical records. They should be excluded from active
  work lists unless a caller explicitly asks for removed state.
- Batch updates and batch removals return structured `PlantSummaryView[]`
  responses containing only the plants actually affected.
- Location availability for planning is based on active garden records and
  current project assignments, not stale names in agent prose.
- Garden mutations should emit activity history when the change is meaningful to
  the user or downstream workflows.

## Runtime Surfaces

- Agent tools expose conversational create, update, search, and care workflows.
- Internal data routes expose structured garden profile, bed, container, plant,
  batch, care, and location responses for Cambium and Verdant.
- Garden state is used by projects, tasks, triage, weather, incidents, activity,
  and search.

See [API Reference](../../architecture/api-reference.md), [Data Model](../../architecture/data-model.md), and
[System Overview](../../architecture/system-overview.md) for route and storage
details.
