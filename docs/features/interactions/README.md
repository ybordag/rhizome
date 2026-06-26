# Human-in-the-Loop Interactions

Human-in-the-loop interactions are Rhizome's safety and review layer. They let
the agent pause before consequential changes, persist the pending decision, and
resume the correct domain operation after the user approves, rejects, or edits
the proposal.

## Feature Sets

- [Structured Approvals](structured-approvals.md)
- [Destructive Confirmations](destructive-confirmations.md)
- [Interaction Records and Reuse](interaction-records-reuse.md)

## User Capabilities

- Review project proposals, treatment plans, weather-driven task changes, and
  triage summaries as structured UI payloads.
- Confirm or cancel destructive or irreversible operations.
- Resume a pending interaction after a chat interruption or frontend reload.
- View recent resolved interactions as part of activity and decision history.
- Avoid duplicate review prompts when the same pending interaction already
  exists.

## Owned Domain Objects

- `InteractionRecord`
- interaction envelopes in graph state
- interaction-related activity events

## Interaction Types

- `confirmation_request` for destructive or consequential operations.
- `proposal_review` for project proposal acceptance and revision decisions.
- `treatment_plan_review` for incident treatment approval.
- `weather_change_review` for forecast-driven task changes.
- `triage_view` for reviewable priority summaries.

## Invariants

- Consequential changes should either be low-risk and explicit, or pass through
  an interaction record before execution.
- Pending interactions are persisted so they survive process restarts and
  frontend reloads.
- Duplicate pending interactions should be reused rather than creating parallel
  approval records for the same source object.
- Non-blocking `triage_view` records should only surface as the current pending
  interaction when they correspond to the latest non-empty triage snapshot.
  Stale or empty triage cards are skipped so the frontend review panel does not
  display old "no work" summaries as current state.
- Destructive confirmations route back through the tool node after approval.
- Structured review tools execute inside the interaction node after approval
  when they already have enough persisted source data.
- Resolving an interaction should record the decision in activity history.

## Runtime Surfaces

- The LangGraph agent uses interrupts and `GardenState.pending_interaction` to
  pause and resume work.
- Internal agent endpoints expose pending and resolved interaction state to
  Cambium.
- Domain tools create interaction records for proposal, treatment, weather, and
  destructive flows.

See [Agent Loop](../../architecture/agent-loop.md) and
[API Reference](../../architecture/api-reference.md) for runtime details.
