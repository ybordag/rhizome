# Project Planner Phase 2 Plan

**Status:** Implemented  
**Last updated:** 2026-04-12

---

## Summary

Phase 2 adds a project planner that turns a project idea into structured,
negotiable proposals and persists an accepted plan as:

- a `ProjectRevision`
- a normalized `ProjectExecutionSpec`
- a non-persistent schedule preview derived from that execution spec

This phase does not yet create the persistent task system. That remains Phase
3. The planner is meant to act as a proposal manager rather than a one-shot
generator.

---

## Current status

Phase 2 has been implemented in the codebase.

Completed work:

- planner persistence models were added for briefs, proposals, revisions, and
  execution specs
- deterministic planner helpers were added for feasibility, cost, timeline,
  effort, and schedule-preview generation
- planner tools were added for brief management, context assembly, proposal
  save/list, proposal acceptance, and schedule preview
- planner actions were integrated with the existing activity log
- unit and integration tests were added for the planner workflow and preview
  contract

Current verification status:

- `pytest` passes with 82 tests

GitHub tracking:

- epic [#35](https://github.com/ybordag/rhizome/issues/35) captures the Phase 2
  planner rollout
- child issues [#36](https://github.com/ybordag/rhizome/issues/36) through
  [#42](https://github.com/ybordag/rhizome/issues/42) reflect the implemented
  sub-slices
- the older Step 4 issue [#19](https://github.com/ybordag/rhizome/issues/19)
  has been commented as superseded, but could not be closed from this token

This document now acts as both the implementation record for Phase 2 and the
handoff point into Phase 3 task tracking.

---

## Planner workflow

The implemented workflow is:

1. user describes a potential project
2. Rhizome creates or updates a `ProjectBrief`
3. Rhizome assembles planning context from the project, garden profile,
   locations, plant material, and recent activity
4. Rhizome identifies blocking unknowns
5. if needed, Rhizome asks targeted follow-up questions
6. once enough context exists, Rhizome saves up to three viable proposals
7. the user negotiates changes
8. Rhizome supersedes or revises prior proposals
9. the user accepts one proposal
10. Rhizome creates a `ProjectRevision` and `ProjectExecutionSpec`
11. Rhizome can generate a schedule preview without persisting tasks

Proposal output always includes:

- estimated cost
- estimated timeline
- estimated total hours
- estimated average hours per week
- estimated peak hours per week
- estimated maintenance hours per week

---

## Persistence model

Phase 2 introduces dedicated planner tables:

- `ProjectBrief`
- `ProjectProposal`
- `ProjectRevision`
- `ProjectExecutionSpec`

These are the source of truth for planner state. `GardeningProject.approved_plan`
may still mirror the accepted proposal for convenience, but accepted plans now
live primarily in `ProjectRevision`.

### `ProjectBrief`

Stores the working planning brief for a project:

- goal
- desired outcome
- target start
- target completion
- budget cap
- effort preference
- propagation preference
- priority preferences
- notes
- status

Statuses:

- `draft`
- `ready_for_proposal`
- `superseded`

### `ProjectProposal`

Stores a versioned project proposal tied to a brief:

- title
- summary
- recommended approach
- selected locations
- selected plants
- material strategy
- propagation strategy
- assumptions
- tradeoffs
- risks
- feasibility notes
- cost estimate
- timeline estimate
- effort estimate
- maintenance assumptions
- resource assumptions
- budget assumptions
- timing anchors
- version
- status

Statuses:

- `proposed`
- `accepted`
- `rejected`
- `superseded`

### `ProjectRevision`

Created only when a proposal is accepted.

Stores:

- source proposal
- revision number
- approved plan payload
- approval timestamp
- status

Statuses:

- `active`
- `superseded`

### `ProjectExecutionSpec`

Stores the normalized execution input derived from an accepted revision:

- selected plants
- selected locations
- propagation strategy
- timing windows
- maintenance assumptions
- resource assumptions
- budget assumptions
- preferred completion target
- plant categories
- timing anchors
- status

Statuses:

- `active`
- `superseded`

---

## Tool and helper surface

Phase 2 adds planner tools under `agent/tools/planning.py`:

- `get_or_create_project_brief`
- `update_project_brief`
- `get_project_brief`
- `assemble_planning_context`
- `check_blocking_unknowns`
- `list_candidate_locations`
- `list_candidate_plant_material`
- `save_project_proposal`
- `list_project_proposals`
- `accept_project_proposal`
- `preview_project_schedule`

Deterministic helper APIs in `agent/planner.py` provide:

- `check_plan_feasibility`
- `estimate_plan_cost`
- `estimate_plan_timeline`
- `estimate_plan_effort`
- `generate_schedule_preview`

The LLM is expected to use these tools to:

- gather or refine the brief
- understand active constraints
- decide what clarifying questions are still blocking
- compose and negotiate proposals

The deterministic layer owns:

- hard-constraint checks
- cost estimation
- timeline estimation
- effort estimation
- schedule-preview generation

---

## Schedule preview contract

Phase 2 intentionally stops short of persistent task generation, but it locks
the contract that Phase 3 will consume.

The execution spec supports both timing modes:

- `calendar`
- `event`

This allows later activity-log events such as germination or transplanting to
anchor future follow-up work.

The schedule preview uses the same conceptual generator layers that Phase 3
will later persist:

- milestone generator
- dependency builder
- recurring care generator
- calendar scheduler
- task tree builder

Recurring work is represented as recurring rules, not a full season of task
instances. Phase 3 will later map this into:

- `Task`
- `TaskDependency`
- `TaskSeries`
- `TaskGenerationRun`

Phase 2 preview output can show milestone tasks, dependency edges, recurring
care rules, and example upcoming dates without creating task rows.

---

## Activity-log integration

Planner actions are recorded in the activity log.

Phase 2 event types:

- `project_brief_created`
- `project_brief_updated`
- `project_planning_context_assembled`
- `project_planning_unknowns_identified`
- `project_proposal_created`
- `project_proposal_revised`
- `project_proposal_accepted`
- `project_revision_created`
- `project_schedule_preview_generated`

This provides planning traceability before the task system exists and sets up
later event-linked scheduling for care tasks.

---

## Acceptance criteria

Phase 2 is considered complete when:

- planner state is persisted in dedicated planner tables
- the agent can create and update a project brief
- planning context can be assembled from real project and garden data
- blocking unknowns can be surfaced without over-questioning the user
- structured proposals can be saved and revised
- accepting a proposal creates a revision and execution spec
- a schedule preview can be generated without persisting tasks
- planner actions are recorded in the activity log
- planner unit and integration tests pass

These acceptance criteria have been met.

---

## Explicit defer list

Still deferred to Phase 3 or later:

- persistent task rows
- persistent dependency rows
- recurring `TaskSeries` persistence
- `TaskGenerationRun`
- rolling materialization of recurring care tasks
- task-driven care events such as `plant_watered` and `bed_fertilized`
- daily triage over pending tasks
- full event-driven task scheduling from live activity events

Phase 2 establishes the planner and execution contract that Phase 3 will build
on.
