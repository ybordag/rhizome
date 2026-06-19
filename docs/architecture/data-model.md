# Data Model

All models live in `db/models.py`. The database is SQLite for development; Postgres is the migration target. SQLAlchemy ORM throughout.

---

## Object lifecycle

```
GardenProfile (1 per user)
  └── GardeningProject  (status: planning → active → maintaining → paused → complete)
        │
        ├── ProjectBrief  (status: draft → ready_for_proposal → superseded)
        │     └── ProjectProposal  (v1, v2, ...) (status: proposed → accepted/rejected/superseded)
        │           └── ProjectRevision  (status: active → superseded)
        │                 └── ProjectExecutionSpec  (status: active → superseded)
        │                       └── TaskGenerationRun  (status: complete → superseded)
        │                             └── Task  (pending → in_progress → done/skipped/deferred/blocked/superseded)
        │                                   ├── TaskDependency  (blocking_task → blocked_task)
        │                                   └── TaskSeries  (recurring rule, → materialized Task instances)
        │
        ├── ProjectBed     (junction: project ↔ bed)
        ├── ProjectContainer (junction: project ↔ container)
        └── ProjectPlant   (junction: project ↔ plant, soft-delete via removed_at)

GardenProfile
  ├── Bed      (location, sunlight, soil, care timestamps)
  ├── Container (type, size_gallons, location, care timestamps)
  └── Plant    (status, source, timing dates, care timestamps)
        └── PlantBatch  (batch provenance: seed lot, supplier, tray)

IncidentReport (status: reported → approved → resolved)
  ├── IncidentSubject  (affected plants, beds, containers)
  └── TreatmentPlan  (status: draft → approved)
        └── (generates Tasks on approval)

InteractionRecord  (status: pending → resolved/dismissed)
WeatherSnapshot    (7-day forecast + derived impacts)
WeatherTaskChangeSet (status: draft → approved)
TriageSnapshot     (session-start triage output)

ActivityEvent      (every state change)
  └── ActivitySubject  (links event to affected entities)
```

---

## Core models

### GardenProfile
One per user. The physical and contextual description of the garden.

| Field | Purpose |
|---|---|
| `climate_zone` | e.g. "9b" — affects plant selection advice |
| `frost_date_last_spring / first_fall` | bounds seed-start and transplant windows |
| `soil_type` | clay, loam, sandy — affects amendment advice |
| `tray_capacity / tray_indoor_capacity` | limits concurrent propagation projects |
| `latitude / longitude` | grounds weather to actual location |
| `hard_constraints` | JSON — e.g. "dog-safe plants only" |
| `soft_preferences` | JSON — e.g. "prefer organic" |

### GardeningProject
The planning unit. Everything — tasks, plants, beds, proposals — is scoped to a project.

Statuses: `planning → active → maintaining → paused → complete`

### ProjectBrief → ProjectProposal → ProjectRevision → ProjectExecutionSpec

This chain is the planning lifecycle:

**ProjectBrief** — user's requirements (desired outcome, budget cap, target completion, effort preference). Auto-promotes to `ready_for_proposal` when required fields are all set.

**ProjectProposal** — agent's response to the brief. Contains the selected plants and locations, propagation strategy, and three computed estimates:
- `cost_estimate` — plant material, materials, amendment, container setup, 10% contingency, total
- `timeline_estimate` — planning start → first action → establishment → completion → maintenance mode
- `effort_estimate` — total hours, avg/peak per week, work buckets (setup/propagation/care)

Also contains feasibility check results (hard violations, soft warnings), assumptions, tradeoffs, risks.

Proposals are versioned. Multiple proposals can exist for a brief; only one is accepted.

**ProjectRevision** — snapshot of the accepted proposal. Immutable once created. Source of truth for "what was agreed on."

**ProjectExecutionSpec** — normalized form of the revision, optimized for task generation. Carries the selected plants (with task profiles), selected locations, timing windows, propagation strategy.

### TaskGenerationRun → Task → TaskDependency → TaskSeries

**TaskGenerationRun** — one per generation pass. Tracks run type (initial / regeneration / event_followup) and serves as parent for all tasks in that run.

**Task** — the unit of work. Key fields:

| Field | Purpose |
|---|---|
| `type` | milestone / maintenance / emergency / opportunistic |
| `status` | pending / in_progress / done / skipped / deferred / blocked / superseded |
| `priority` | critical / high / normal / low |
| `scheduled_date` | target date |
| `earliest_start` | not before this date |
| `window_start / window_end` | acceptable range |
| `deadline` | hard cutoff |
| `deferred_until` | set on deferral |
| `event_anchor_type` | "plant_germinated" etc — task waits for this event |
| `linked_subjects` | JSON list of {subject_type, subject_id, role} for care side effects |
| `is_user_modified` | true = preserved on regeneration |
| `reversible` | false = agent will confirm before skipping |

**TaskDependency** — finish-to-start link between tasks. `blocking_task → blocked_task`. `compute_task_blocked_state` checks direct blockers only (one level deep).

**TaskSeries** — recurring rule. Defines cadence, start/end conditions, and linked subjects. `materialize_task_series` generates Task instances on a rolling 14-day horizon.

---

## Garden entity models

### Bed
Physical garden bed. `user_id` indexed. Tracks care state: `last_watered_at`, `last_fertilized_at`, `last_amended_at`, `last_inspected_at`, `care_state_notes`.

### Container
Pot, growbag, raised container. `user_id` indexed. Same care state fields as Bed, plus `is_mobile`.

### Plant
Individual plant. `user_id` indexed, `status` indexed. Key fields: `source` (seed/cutting/transplant/existing), `status`, `sow_date`, `red_cup_date`, `transplant_date`, care timestamps, `fertilizing_schedule`, `special_instructions`.

### PlantBatch
Provenance record for a group of plants sown together. Tracks supplier, seed lot reference, grow light, tray assignment.

---

## Incident models

### IncidentReport
User or agent-reported problem: pest, blight, weed. Linked to affected subjects via `IncidentSubject`. Statuses: `reported → approved → resolved`.

### TreatmentPlan
Agent-drafted treatment approach. `recommended_steps` is a JSON list of `{title, task_type, estimated_minutes, days_from_approval}`. On approval, tasks are auto-generated for each step.

---

## Interaction and event models

### InteractionRecord
Persisted record of every structured interaction presented to the user. Tracks interaction type, status (pending/resolved/dismissed), resolution action, and resolution summary.

### WeatherSnapshot
7-day Open-Meteo forecast + derived impacts (`derived_impacts` JSON) + recommended actions. Refreshed on demand; all tasks that reference weather load the latest snapshot.

### WeatherTaskChangeSet
Proposed batch of weather-driven task adjustments. Approval-gated via the interaction system.

### TriageSnapshot
Session-start output: recommended task IDs, urgent/routine/project groupings, weather snapshot reference, reasoning summary.

---

## Activity log

### ActivityEvent
Every state change in the system records at least one event. Fields:
- `actor_type / actor_label` — who did it (agent tool call, user confirmation)
- `event_type` — e.g. `task_completed`, `plant_watered`, `proposal_accepted`
- `category` — domain: `task`, `project`, `plant`, `incident`, `interaction`, `care`, `weather`
- `summary` — human-readable description
- `project_id` — for project-scoped queries
- `revision_id` — FK to project_revision (enforced in Postgres)
- `event_metadata` — JSON with `before`/`after` snapshots for update events

### ActivitySubject
Links an event to the entities it affected. `subject_type` + `subject_id` + `role` (primary/affected/generated_from/source). Multiple subjects per event.

---

## Key indexes

| Table | Index |
|---|---|
| Plant | user_id, status |
| Bed | user_id |
| Container | user_id |
| PlantBatch | user_id, project_id |
| Task | project_id, revision_id, status, scheduled_date, deadline, priority, series_id |
| TaskDependency | blocking_task_id, blocked_task_id |
| TaskSeries | project_id, revision_id, next_generation_date |
| ProjectBed | project_id; UNIQUE(project_id, bed_id) |
| ProjectContainer | project_id; UNIQUE(project_id, container_id) |
| ProjectPlant | project_id, plant_id |
| ActivityEvent | created_at, project_id, event_type, revision_id |
| ActivitySubject | event_id, (subject_type, subject_id) |
| InteractionRecord | created_at, status, project_id, interaction_type |
| IncidentReport | project_id, status |
| TreatmentPlan | incident_id, status |

---

## Session state (LangGraph)

Conversation state lives in the LangGraph checkpoint store (`rhizome_checkpoints.db`), keyed by `thread_id`. The `GardenState` TypedDict carries: messages, pending_interaction, interaction_history, skip_tool_node.

`user_id` is NOT in GardenState — it's in `graph.config["configurable"]["user_id"]`, read by tools via the `current_user_id` ContextVar.

---

## Postgres migration path

`requirements.txt` already includes `psycopg2-binary` and `pgvector`. Migration steps:
1. Swap `langgraph-checkpoint-sqlite` → `langgraph-checkpoint-postgres`
2. Update `db/database.py` engine and session factory to use the Postgres URL
3. Run Alembic migrations (or apply schema via `Base.metadata.create_all`)
4. Configure HA replication (Patroni or pg_auto_failover)

This migration is required before: multi-instance deployment, FK enforcement (SQLite ignores FKs at runtime), and pgvector for embeddings.
