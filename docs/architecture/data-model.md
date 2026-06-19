# Data Model

All models live in `db/models.py`. The database is **Postgres** in staging and production (SQLite for in-memory test runs only). SQLAlchemy ORM throughout.

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

GardeningProject
  ├── ProjectExpense   (budget tracking: estimated vs actual cost, by category)
  └── ShoppingItem     (purchasing list; linked to ProjectExpense on purchase)

CalendarAnnotation  (day-level notes, per user — independent of projects)

IncidentReport (status: reported → approved → resolved)
  ├── IncidentSubject  (affected plants, beds, containers)
  └── TreatmentPlan  (status: draft → approved)
        └── (generates Tasks on approval)

InteractionRecord  (status: pending → resolved/dismissed)
WeatherSnapshot    (7-day forecast + derived impacts)
WeatherTaskChangeSet (status: draft → approved)
TriageSnapshot     (session-start triage output)

ActivityEvent      (every state change, scoped to user_id)
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

**TaskDependency** — finish-to-start link between tasks. `blocking_task → blocked_task`. `compute_task_blocked_state` checks direct blockers only (one level deep). Dependencies are manageable via the API; cycle detection (BFS) prevents A→B→A chains.

**TaskSeries** — recurring rule. Defines cadence, start/end conditions, and linked subjects. `materialize_task_series` generates Task instances on a rolling 14-day horizon. `revision_id` and `generation_run_id` are nullable — user-created series (source_type="user") don't require a planning revision.

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
- `user_id` — mandatory since the multi-tenancy fix; `list_recent_activity_entries` filters on this
- `actor_type / actor_label` — who did it (agent tool call, user confirmation)
- `event_type` — e.g. `task_completed`, `plant_watered`, `proposal_accepted`
- `category` — domain: `task`, `project`, `plant`, `incident`, `interaction`, `care`, `weather`
- `summary` — human-readable description
- `project_id` — for project-scoped queries (nullable — not all events belong to a project)
- `revision_id` — FK to project_revision (nullable)
- `event_metadata` — JSON with `before`/`after` snapshots for update events

### ActivitySubject
Links an event to the entities it affected. `subject_type` + `subject_id` + `role` (primary/affected/generated_from/source). Multiple subjects per event.

---

## User-facing models added in the frontend API pass

### CalendarAnnotation
Day-level notes per user. Not tied to a project. Key fields: `date` (Date), `content`, `category` (note|observation|plan|reminder), `color`. Indexed on `(user_id, date)` for efficient range queries.

### ProjectExpense
Budget tracking for a project. Tracks `estimated_cost` vs `actual_cost` per item, grouped by `category` (material|equipment|plant|labor|other). `purchased_at` is a Date column. Used by the `/expenses/summary` endpoint to produce proposal vs. actual budget comparisons.

### ShoppingItem
Purchasing list — standalone or project-scoped. `status`: needed|ordered|purchased. `priority`: high|normal|low. On `POST /shopping/{id}/purchase`, status is set to purchased and a linked `ProjectExpense` is auto-created when `project_id` and `estimated_cost` are both set (linked via `expense_id` FK).

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
| ActivityEvent | created_at, project_id, event_type, revision_id, user_id |
| ActivitySubject | event_id, (subject_type, subject_id) |
| CalendarAnnotation | (user_id, date) |
| ProjectExpense | user_id, project_id |
| ShoppingItem | user_id, project_id, status |
| InteractionRecord | created_at, status, project_id, interaction_type |
| IncidentReport | project_id, status |
| TreatmentPlan | incident_id, status |

---

## Thread model

`Thread` bridges user-facing conversation management with LangGraph's internal checkpoint store.

```
Thread
  id                   string PK    — IS the LangGraph thread_id (botanical name e.g. silver-fern-cascade)
  user_id              string       — UUID string from cambium.users; scopes the thread to a user
  title                string?      — auto-set from first human message (first 60 chars); user-editable
  project_id           string? FK   — optional link to a GardeningProject
  last_message_preview string?      — first 150 chars of last AI response (updated each turn)
  last_active_at       datetime?    — updated by session_context_intake on every turn
  message_count        int          — human message count; updated each turn
  created_at           datetime
```

**Key design decision:** `Thread` stores only metadata. Actual message content lives in the LangGraph PostgresSaver checkpointer tables. `GET /internal/data/threads/{id}/messages` calls `agent.get_state()` to retrieve the full history — no duplication.

**Thread ID generation:** Cambium generates botanical three-word names (31 descriptors × 41 plants × 36 phenomena ≈ 45,700 combinations). Rhizome stores and uses them as opaque strings.

**Interrupted stream recovery:** The LangGraph checkpoint is saved after each node completes — including after `llm_call` finishes, before SSE streaming to the client. If the stream is cut, the full AI response is still in the checkpoint and retrievable via the messages endpoint.

---

## Session state (LangGraph)

Conversation state lives in the LangGraph PostgresSaver checkpoint store, keyed by `thread_id`. The `GardenState` TypedDict carries: `messages`, `monitor_alerts`, `temporal_context`, `session_context`, `skip_tool_node`, `user_id`.

`user_id` flows through `graph.config["configurable"]["user_id"]` and is set into the `current_user_id` ContextVar by `session_context_intake` at the start of every turn. All tool queries use `current_user_id.get()` — never a hardcoded value.

---

## Schema and migrations

All domain tables live in the **`rhizome` schema** in Postgres. The SQLAlchemy engine and LangGraph checkpointer both set `search_path=rhizome` so queries and `create_all()` target the correct schema.

**Alembic** manages schema migrations in staging and production:

```bash
# Apply pending migrations before starting the server
alembic upgrade head

# After changing db/models.py — generate and apply a new migration
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

`alembic/versions/` contains the migration history. `alembic.ini` and `alembic/env.py` configure the connection (reads `DATABASE_URL` from environment) and target schema.

Tests use `init_db()` with in-memory SQLite — they never run Alembic. `init_db()` remains as a safety net for fresh installs only.
