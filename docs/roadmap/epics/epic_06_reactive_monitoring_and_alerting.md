# Epic 6 Plan: Reactive Monitoring and Alerting

**Epic status:** Ready to start  
**Last updated:** April 29th, 2026

---

## Purpose

Move Rhizome from session-only operational awareness to proactive monitoring of
weather, pests, and other external conditions that should influence the
garden’s active projects and task lists.

---

## Why this epic matters now

Rhizome already has the first half of this system:

- weather snapshots
- weather-aware task impacts
- approval-gated weather task changes
- daily triage
- incident and treatment-plan workflows

What is missing is the proactive and external monitoring layer:

- scheduled refresh
- alert generation
- external pest-report ingestion
- vulnerability analysis
- escalation into triage and tasks

---

## What should exist by the end of this epic

- scheduled weather refreshes
- scheduled or event-triggered alert evaluation
- pest alert ingestion from sources like iNaturalist
- vulnerability assessment across:
  - projects
  - plants
  - beds/containers
  - active tasks
- alert generation with actionable recommendations
- urgency upgrades and draft task changes where appropriate
- approval-gated plan/task changes when alerts require intervention
- monitoring outputs surfaced into triage and app interaction flows

---

## Proposed implementation slices

### Slice 1: Weather automation

Upgrade the current weather path from session-driven to scheduled:

- periodic weather snapshot refresh
- freshness tracking
- weather-trigger evaluation independent of an active chat session

### Slice 2: Monitoring records and alert model

Define the persistence/runtime model for monitoring:

- alert or monitoring run records
- alert summaries
- affected objects/projects/tasks
- resolution state if needed

### Slice 3: Vulnerability assessment

Implement logic that cross-references:

- weather conditions
- active projects
- plant inventory
- current task graph
- care state

This should determine which things are actually at risk.

### Slice 4: Pest alert ingestion

Integrate external pest-report sources such as iNaturalist:

- recent local observations
- matching those observations to relevant plant/project context
- turning those into monitoring alerts rather than immediate treatment actions

### Slice 5: Alert-driven task and triage updates

Connect monitoring outputs to:

- triage recommendations
- urgency changes
- draft weather or incident task updates
- project amendment proposals when a simple task change is not enough

---

## Completion criteria

This epic should be considered complete when:

- Rhizome can refresh and evaluate weather context without waiting for a user
  session
- Rhizome can ingest at least one external pest-report source
- alerts are filtered through vulnerability assessment instead of being treated
  as globally relevant
- monitoring results can influence triage and create approval-gated task/action
  recommendations
- major alert-driven changes do not silently rewrite project plans

---

## Important dependencies

### Depends on

- Epic 4: Task Creation and Execution Tracking
- Epic 5: Daily Triage and Operational Guidance

### Strongly benefits from

- Epic 8: Knowledge and External Retrieval
- Epic 11: Platform Hardening and Scale

### Strongly enables

- Epic 7: Iteration and Amendments

### Partially blocked by

- stronger background automation / scheduled operations support is still thin
- local external alert integrations are not yet in place

---

## Open questions to resolve inside this epic

- what alert persistence model should we use?
- should weather and pest alerts share one monitoring abstraction or stay
  separate at first?
- when should an alert create a new task versus only escalating urgency on an
  existing task?
- when should an alert trigger a plan amendment rather than a task adjustment?
