# Interaction Records and Reuse

Interaction records persist pending and resolved user decisions so approval
flows survive interruptions and avoid duplicate prompts.

## Current Behavior

Persists pending and resolved interactions as `InteractionRecord`, rebuilds
pending envelopes, and records resolution activity.

## Record Content

- Interaction type and status.
- Source type and source ID.
- Payload needed to rebuild the frontend envelope.
- Thread, project, and user context.
- Resolution action, actor, and timestamps.

## Contract Notes

- Pending lookup should match on user, type, source type, source ID, and active
  status.
- Resolved records should not be reused as pending prompts.
- Rebuilt envelopes should be equivalent enough for frontend resume flows even
  if the original chat turn is gone.
- Resolution should emit activity so the decision appears in project and entity
  histories.
- Interaction storage is not a notification queue by itself, but monitor and
  frontend surfaces may use pending records to alert the user.

## Related Docs

- [Structured Approvals](structured-approvals.md)
- [Activity Events](../activity/activity-events.md)
