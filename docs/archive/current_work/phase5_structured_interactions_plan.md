# Phase 5: Structured Interaction Layer and CLI App Simulation

**Status:** Historical implementation record  
**Last updated:** April 29th, 2026

> This document remains useful as the implementation record for Phase 5.
>
> For current roadmap sequencing and epic prioritization, use
> [long_term_roadmap.md](/Users/yashi/Documents/Work/Code/Gardening%20Agent/rhizome/docs/roadmap/long_term_roadmap.md).

---

## Summary

Phase 5 adds a backend interaction contract on top of Rhizome's existing
planner, tracker, triage, treatment, and weather workflows. The interaction
layer is designed to be UI-neutral:

- the backend now emits typed interaction envelopes for approvals and review
  moments
- the terminal can render and step through those interactions for manual UX
  simulation
- a future app can query interaction summaries and resolve actions through the
  same contract

This phase does **not** attempt to build the final product UI. The terminal
renderer is a simulation surface for manual testing and product iteration.

---

## Implemented in Phase 5

### Generic interaction contract

Rhizome now has a shared interaction model with:

- `InteractionEnvelope`
- `InteractionAction`
- `InteractionResolution`

Supported v1 interaction types:

- `confirmation_request`
- `proposal_review`
- `treatment_plan_review`
- `weather_change_review`
- `triage_view`

### Persisted interaction summaries

Interaction summaries are stored in `InteractionRecord` so the system can
answer questions like:

- what was the user asked to approve?
- what action did they take?
- what proposal or treatment plan was this tied to?
- what interactions are still pending?

The persisted record is intentionally lighter than the live interaction
payload. Runtime/checkpoint state still owns the full in-flight interaction
envelope when the graph is paused.

### Structured approval/review flows

The following flows now use the shared interaction layer:

- destructive confirmations
- project proposal acceptance review
- treatment plan approval review
- weather task change approval review
- triage presentation

For destructive and approval-gated flows, the graph pauses with a structured
interaction payload instead of a one-off confirmation string.

### CLI simulation renderer

`main.py` now renders structured interactions in the terminal and lets the user
choose actions interactively. This makes it possible to manually simulate the
core app flows before the frontend exists.

Supported CLI simulation behavior:

- action selection by number or action id
- lightweight form inputs for actions that need notes or selection inputs
- structured resume payloads for graph interrupts
- optional triage interaction handling after a normal response

### Query/resolve API surface

Rhizome now exposes interaction-oriented tools for later frontend use:

- `get_pending_interaction`
- `list_recent_interactions`
- `get_interaction_record`
- `resolve_interaction`

These provide a simple app-facing bridge without binding the future frontend to
the terminal renderer.

---

## Design choices locked by this phase

- The interaction layer is **backend first**, not terminal first.
- The terminal renderer is for **simulation**, not polished UX.
- Domain tools remain the source of truth for planner, tracker, incident, and
  weather behavior.
- Structured interactions wrap approval/review seams instead of replacing
  domain logic.
- Persisted interaction history stores **summaries and decisions**, not full
  replayable UI payloads.

---

## Follow-on work enabled by this phase

- app-native rendering of proposals, triage cards, weather reviews, and
  treatment-plan approvals
- richer interaction analytics or audit views
- more guided multi-step interactions if needed
- moving additional user-facing review moments from plain text into typed
  interaction flows
