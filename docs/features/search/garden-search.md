# Garden Search

Garden search finds existing garden records so the agent and frontend can
resolve user references before creating or changing state.

## Current Behavior

Searches beds, containers, and plants by name with optional entity type,
location, and status filters.

## Search Inputs

- Query text.
- Optional entity type filters.
- Optional location and status filters.
- User ID supplied by Cambium or internal trusted context.

## Contract Notes

- Search is user-scoped and should never return another user's records.
- Empty or too-short queries should return validation feedback instead of a
  broad result dump.
- Active records should rank before removed or historical records unless the
  caller explicitly requests historical state.
- Current search is structured database matching. Full-text and vector retrieval
  are future intelligence work, not a replacement for ownership checks.

## Related Docs

- [Plants and Batches](../garden/plants-batches.md)
- [Location Navigation](location-navigation.md)
