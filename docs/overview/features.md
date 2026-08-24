# Features

Current capability inventory for Rhizome, organized by domain.

This page is the short map. Durable feature specifications live under
[Feature Specs](../features/README.md), while exact route contracts live in the
[API Reference](../architecture/api-reference.md).

---

## Garden model

The foundation everything else builds on. Rhizome holds a persistent model of the physical garden.

**Garden profile** — climate zone, frost dates, soil type, tray capacity,
location context for weather, hard constraints, soft preferences, and notes.

**Beds and containers** — named growing locations with sunlight, soil, size,
mobility, notes, project assignments, and care history.

**Plants and batches** — individual plants plus groups started or acquired
together. Records include variety, source, lifecycle status, location, timing,
growth state, care fields, and project links.

**Care state** — plants, beds, and containers track recent care timestamps and
notes. Completing linked care tasks can update care state automatically.

See [Garden Model](../features/garden/README.md).

---

## Project planning

Structured lifecycle from goal to approved plan.

**Project brief** — the user's working requirements: desired outcome, target
dates, budget, effort preference, propagation preference, priorities, notes, and
unknowns.

**Planning context** — structured project context assembled from the garden
profile, locations, plant material, resource use, active work, and conflicts.

**Proposals and revisions** — agent-drafted plans with selected locations,
plant material, feasibility notes, estimates, assumptions, risks, and tradeoffs.
Acceptance creates a historical revision and active execution spec.

**Schedule preview** — non-destructive preview of tasks, dependencies, and
recurring series before the user commits to generation.

See [Project Planning](../features/projects/README.md).

---

## Task management

Auto-generated task graphs with full lifecycle management.

**Task generation** — accepted execution specs create section tasks,
milestones, maintenance tasks, recurring series, dependencies, and initial
materialized work.

**Dependencies and anchors** — tasks can wait on direct task dependencies or
biological event anchors such as germination or transplant readiness.

**Lifecycle** — tasks move through pending, in progress, done, skipped,
deferred, blocked, and superseded states. Completion can unblock dependents and
apply linked care side effects.

**Daily work lists** — due, daily, blocked, and project task routes expose
structured task summaries for the app and agent.

**Recurring work and regeneration** — `TaskSeries` records materialize a rolling
task horizon. Regeneration supersedes replaceable generated tasks while
preserving user-modified work.

See [Task Management](../features/tasks/README.md).

---

## Daily triage

Session-time snapshot for "what should I do today?"

**Triage snapshot** — built or loaded during session startup. It combines
weather context, temporal context, session context, monitor alerts, and task
groups into a persisted summary.

**Priority groups** — latest triage returns structured urgent, routine, and
project task groups.

**Weather and monitor integration** — weather-affected tasks and monitor alerts
surface with urgency context.

See [Daily Triage](../features/triage/README.md).

---

## Weather

**Snapshot** — fetches forecast data, derives garden impacts, and stores
summary conditions, alerts, recommendations, and raw payload.

**Task impacts** — identifies tasks materially affected by current weather,
such as transplant work during frost risk or watering work during heat.

**Approval-gated changes** — drafts task adjustments and applies them only after
structured approval, except narrow documented monitor policies.

See [Weather](../features/weather/README.md).

---

## Incidents and treatment

**Incident reports** — user or agent reports a pest, disease, weed, damage, or
other garden incident linked to affected subjects.

**Treatment plans** — agent or user drafts treatment steps and follow-up
strategy. Approval creates linked treatment tasks.

**Resolution** — incidents can be updated, resolved, and reviewed through
activity history.

See [Incidents and Treatment](../features/incidents/README.md).

---

## Human-in-the-loop interactions

The structured interaction system is how Rhizome handles decisions that shouldn't be made unilaterally.

**Interaction types:**
- `confirmation_request` — destructive operation confirmation (delete_project, delete_bed, etc.)
- `proposal_review` — project proposal acceptance (accept_project_proposal)
- `treatment_plan_review` — treatment plan approval (approve_treatment_plan)
- `weather_change_review` — weather-driven task change approval (approve_weather_task_changes)
- `triage_view` — structured priority summary

**Mechanics** — LangGraph interrupts pause the graph and present an
`InteractionEnvelope`. The graph resumes only after the user resolves the
interaction. If cancelled, no domain changes are made.

**Reuse** — pending interactions are persisted as `InteractionRecord` and reused
when the same source object is already awaiting a decision.

**History** — every resolution (confirm, cancel, approve, reject) is recorded as an `interaction_resolved` activity event, so user decisions appear in the project timeline.

See [Human-in-the-Loop Interactions](../features/interactions/README.md).

---

## Action history

Every state change is recorded. The history system makes this queryable.

**Activity events** — domain writes record actor, category, event type, summary,
metadata, project/thread/revision links, and affected subjects.

**Per-entity history** — plant, bed, container, batch, task, incident, and
project views expose filtered timelines.

**Project timeline** — cross-object project history with category, event type,
and cursor filters.

See [Action History](../features/activity/README.md).

---

## Search and navigation

**Garden search** — finds beds, containers, plants, and related entities using
structured filters.

**Location navigation** — returns the plants, containers, and beds associated
with a named garden area.

**Project navigation** — exposes project lists, detail, progress, blockers,
timeline health, budget, and linked garden records.

See [Search and Navigation](../features/search/README.md).
