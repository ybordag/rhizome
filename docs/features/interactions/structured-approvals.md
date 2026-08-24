# Structured Approvals

Structured approvals are review cards for multi-step decisions where prose is
not enough. They give Cambium and Verdant the source IDs, summary, and allowed
actions needed to render and resolve the decision.

## Current Behavior

Uses LangGraph interrupts and `InteractionEnvelope` cards for project proposal
review, treatment plan review, weather change review, and triage views.

## Supported Approval Surfaces

- Project proposal review.
- Treatment plan review.
- Weather task change review.
- Triage view review and acknowledgement.

## Contract Notes

- An approval envelope should include interaction ID, type, source type, source
  ID, summary, payload, and allowed actions.
- Approval actions should be explicit and typed; frontends should not infer
  destructive intent from labels alone.
- Approving a persisted source object should resume the correct domain function
  without relying on chat text.
- Rejection and cancellation should resolve the interaction and preserve an
  audit event.

## Related Docs

- [Interaction Records and Reuse](interaction-records-reuse.md)
- [Agent Loop](../../architecture/agent-loop.md)
