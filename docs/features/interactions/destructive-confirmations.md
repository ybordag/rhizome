# Destructive Confirmations

Destructive confirmations protect operations that remove, delete, supersede, or
otherwise hide user-visible work or garden records.

## Current Behavior

Routes delete and removal tools through an explicit confirmation interaction
before execution.

## Covered Operations

- Project deletion when allowed by task and project invariants.
- Task deletion when the change is consequential.
- Plant, bed, container, incident, treatment, or interaction deletion paths that
  would remove visible state.
- Batch removals and other bulk operations where the affected set must be clear.

## Contract Notes

- Confirmation payloads should identify the target, consequence, and affected
  count or linked records where available.
- Approval should route back to the original tool path with validated source
  data.
- Cancellation should leave domain state unchanged and resolve the interaction.
- Duplicate pending confirmations for the same source should be reused.

## Related Docs

- [Plants and Batches](../garden/plants-batches.md)
- [Interaction Records and Reuse](interaction-records-reuse.md)
