# Plants and Batches

Plants and batches track living inventory. A batch describes a group started or
acquired together; individual plant rows represent the actionable entities that
can move, receive care, join projects, or leave the active garden.

## Current Behavior

Tracks individual plants plus batches of plants started or acquired together.
Plants include variety, source, quantity, status, location, timing dates,
growth state, and care fields.

## User Workflows

- Create plants individually or as a planted batch.
- Inspect plant and batch detail, including location, status, timing, care, and
  project context.
- Move plants between locations and update lifecycle status.
- Apply batch updates to matching active plants.
- Mark selected plants in a batch as removed and receive the affected
  `PlantSummaryView[]`.
- Link plants to projects, incidents, tasks, and activity history.

## Contract Notes

- Removed plants remain historical records and should not disappear from
  histories.
- Batch update and remove operations return only plants actually changed.
- Bulk operations must be user-scoped and must not affect plants from another
  user's batch or garden.
- Status changes should be explicit enough for triage and task filtering.
- Plant location summaries are convenience fields; ownership and location
  relationships should still be validated through persisted records.

## Related Docs

- [Garden Search](../search/garden-search.md)
- [Incident Reports](../incidents/incident-reports.md)
- [Activity Events](../activity/activity-events.md)
