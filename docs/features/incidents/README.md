# Incidents and Treatment

Incidents capture garden problems such as pests, disease, damage, stress, and
other observations that need follow-up. Treatment plans turn those reports into
reviewable, approval-gated work.

## Feature Sets

- [Incident Reports](incident-reports.md)
- [Treatment Plans](treatment-plans.md)

## User Capabilities

- Report an incident against plants, batches, beds, containers, projects, or the
  whole garden.
- Filter, inspect, update, resolve, and delete incident reports.
- Draft a treatment plan from an incident or create a manual treatment plan.
- Review, update, approve, and delete draft treatment plans.
- Generate treatment tasks only after approval.
- View incident and treatment activity in entity histories and project
  timelines.

## Owned Domain Objects

- `IncidentReport`
- `IncidentSubject`
- `TreatmentPlan`
- treatment-generated tasks and activity records

## Invariants

- Incidents and treatment plans are scoped by the owning user's garden records
  and projects.
- An incident can reference multiple subjects; subject links should be preserved
  for search, history, and task context.
- A draft or approved treatment plan should prevent duplicate draft plans for
  the same unresolved incident unless the user intentionally revises the plan.
- Treatment approval is a structured approval flow and is the point where tasks
  are generated.
- Approved treatment plans are historical decisions. Destructive edits or
  deletion should be constrained once work has been generated.
- Incident and treatment routes return structured views, not tool prose.

## Runtime Surfaces

- Agent tools expose incident reporting, treatment drafting, approval, and
  follow-up actions.
- Structured interactions carry treatment-plan review envelopes.
- Internal data routes expose incident lists, incident detail, treatment plans,
  treatment approval, and activity history.

See [Human-in-the-Loop Interactions](../interactions/README.md),
[Task Management](../tasks/README.md), and [Activity History](../activity/README.md)
for the connected review and execution behavior.
