# Epic 6 Plan: Reactive Monitoring and Alerting

**Epic status:** Substantially complete — core monitoring infrastructure delivered; pest ingestion deferred  
**Last updated:** 2026-06-18  
**Implementation plan:** [docs/current_work/calendula_reactive_monitoring.md](../../current_work/calendula_reactive_monitoring.md)

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

| Criterion | Status |
|-----------|--------|
| Rhizome can refresh and evaluate weather context without waiting for a user session | ✅ Done — `weather_job()` in `scripts/monitor.py` |
| Monitoring results influence triage and create approval-gated task/action recommendations | ✅ Done — `triage_job()`, `series_job()`, `apply_weather_impacts()` |
| Major alert-driven changes do not silently rewrite project plans | ✅ Done — critical auto-applied, moderate queued for approval |
| Alerts surface in the agent session | ✅ Done — `session_context_intake` injects pending alerts into system prompt |
| Rhizome can ingest at least one external pest-report source | ⏳ Deferred — iNaturalist integration moved to pest intelligence epic |
| Alerts filtered through vulnerability assessment | ⏳ Deferred — planned for pest intelligence epic alongside RAG |

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

## Open questions — resolved

| Question | Decision |
|----------|----------|
| Alert persistence model? | New `MonitorAlert` model, queryable by API without a user session |
| Shared or separate model for weather vs pest alerts? | Shared `MonitorAlert` with `alert_type` discriminator |
| New task vs urgency escalation? | Critical severity (storm, severe frost, high heat): auto-apply task changes. Moderate: queue for approval. Working window: advisory only, no task changes. |
| Plan amendment vs task adjustment? | Plan amendments remain user-initiated; alerts only touch tasks |
