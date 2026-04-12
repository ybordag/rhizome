# Rhizome Activity Log and Task System Plan

**Status:** Proposed  
**Last updated:** 2026-04-11

---

## Purpose

This document captures the revised plan for Rhizome's next major feature area.

Instead of treating task scheduling as a narrow "seed timing" feature, the new
direction is to build a broader project execution system made up of:

- an activity log
- a project planner
- a task tracker

These systems are related, but they should not be treated as one monolithic
feature. The planner defines what the user is trying to do, the task tracker
manages execution over time, and the activity log provides the historical
record that makes the whole system explainable and auditable.

---

## Proposed sequencing

We are proposing the following implementation order:

1. **Implement Activity Log (at least basic)**
2. **Implement Project Planner**
3. **Implement Task Tracker**
4. **Finish implementing Activity Log (if necessary)**

This sequencing is intentional.

- A basic activity log should exist before the planner and tracker become more
  dynamic, so Rhizome can explain what changed and why.
- The project planner should come before the task tracker, because tasks should
  be generated from an approved project plan rather than appearing as isolated
  work items.
- The task tracker should then manage execution, progress, dependencies,
  deadlines, and revisions over time.
- A second activity-log pass can deepen history coverage once the planner and
  tracker reveal what events are actually important in practice.

---

## System overview

### 1. Activity Log

The activity log should be an append-only historical record of meaningful
changes across the garden system.

At minimum, it should capture:

- object created
- object updated
- object deleted or removed
- project plan proposed
- project plan approved
- tasks generated
- task completed / skipped / deferred
- schedule adjusted
- agent-triggered changes
- user-triggered changes

The activity log should be able to answer questions like:

- when did this project change direction?
- why did this task deadline move?
- what changed after a weather event?
- did the user edit this directly, or did Rhizome do it?
- which revision generated this task set?

### 2. Project Planner

The planner should be the layer that turns a project goal into an executable
proposal.

For a project, Rhizome should be able to propose:

- a plan within budget
- a plan within time-to-completion constraints
- a plan grounded in garden constraints and preferences
- a plan with tradeoffs and assumptions clearly stated

The planner should reason about things like:

- planting start date vs desired completion horizon
- whether a seed-start plan is still realistic if the user is starting late
- what can reasonably be completed by a target date
- what the user can afford within the stated budget
- whether the plan fits available beds, containers, trays, and other resources

The output of the planner should be an explicit project plan or project
revision, not just chat text.

### 3. Task Tracker

The task tracker should be the execution layer for an approved project plan.

It should support:

- project-scoped task trees
- parent / child tasks
- cross-task dependencies
- earliest start, deadline, and scheduling windows
- estimated effort
- task status and progress tracking
- blockers
- replanning and task supersession when assumptions change

The tracker should also support adjustment over time in response to:

- weather events
- plant failures
- changed user budget or goals
- changed timing constraints
- new ideas introduced by the user

Major plan changes should be proposal-first and approval-gated, rather than
silently rewriting the task graph in place.

---

## Why this differs from the old Step 4 framing

The earlier roadmap treated this area mainly as rough schedule generation.
That is too narrow for the actual product direction.

What we want now is not just:

- "generate a seed schedule"

but rather:

- propose a project plan
- generate a task graph from that plan
- track progress over time
- revise the plan when reality changes
- preserve a history of what happened

The old schedule-generation concept can still exist, but it should live inside
the planner/task system rather than define the whole feature.

---

## What "basic activity log" means in phase 1

The first pass of the activity log does not need to be complete.

Phase 1 should be enough to support planner/tracker development and debugging.
At minimum it should record:

- timestamp
- actor type (`user`, `agent`, `system`)
- event type
- object type
- object id
- related project id if applicable
- human-readable summary
- structured payload or diff metadata

This first pass is primarily an internal product and engineering foundation.

---

## What the planner should own

The planner should own:

- project proposal generation
- cost and timing tradeoffs
- assumptions
- feasibility framing
- revision creation when the user changes direction

It should not be reduced to a one-shot date calculator.

The planner should be able to answer questions like:

- what can I realistically start now and still complete by July?
- if I only have $60, what version of this project is still viable?
- if I start peppers late, what tradeoff am I accepting?
- what is the cheapest viable version of this plan?

---

## What the tracker should own

The tracker should own:

- concrete task generation from an accepted plan
- dependency structure
- temporal fields
- progress updates
- task completion / skip / defer flows
- downstream schedule adjustment

It should be able to answer:

- what is due next?
- what is blocked?
- what slips if this task is late?
- what changed after a missed deadline?
- what tasks belong to the current revision vs an older one?

---

## Relationship between the systems

The intended flow is:

1. user creates or updates a project brief
2. Rhizome proposes a plan
3. user approves the plan
4. Rhizome records that approval as a revision
5. Rhizome generates tasks from the approved revision
6. task execution happens over time
7. meaningful changes are written to the activity log throughout
8. if conditions change, Rhizome proposes an amendment or new revision

The activity log spans the whole flow.

---

## Current working decision

Going forward, we should plan this feature area under the following structure:

- **Phase 1:** basic activity log
- **Phase 2:** project planner
- **Phase 3:** task tracker
- **Phase 4:** finish or expand activity log based on real planner/tracker needs

This is the plan we should use for future issue creation, schema planning, and
implementation sequencing unless we explicitly revise it again.
