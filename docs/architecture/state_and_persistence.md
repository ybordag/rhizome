# State and Persistence

**Last updated:** 2026-06

Rhizome has two persistence layers: the **application database** (SQLAlchemy / SQLite → Postgres) and the **LangGraph checkpoint store** (SQLite → Postgres).

---

## Application database

All models live in `db/models.py`. SQLAlchemy with SQLite for development; Postgres is the migration target.

### Object lifecycle

```
GardenProfile
  └── GardeningProject  (status: planning → active → maintaining → paused → complete)
        ├── ProjectBrief  (status: draft → ready_for_proposal → superseded)
        │     └── ProjectProposal  (status: proposed → accepted/rejected/superseded)
        │           └── ProjectRevision  (status: active → superseded)
        │                 └── ProjectExecutionSpec  (status: active → superseded)
        │                       └── TaskGenerationRun  (status: complete → superseded)
        │                             └── Task  (status: pending → in_progress → done/skipped/deferred/blocked/superseded)
        │                                   ├── TaskDependency  (blocking_task_id → blocked_task_id)
        │                                   └── TaskSeries  (recurring rule → materialized Task instances)
        │
        ├── ProjectBed / ProjectContainer / ProjectPlant  (junction tables)
        │
        └── IncidentReport  (status: reported → approved → resolved)
              └── TreatmentPlan  (status: draft → approved)
                    └── (generates Tasks via approve_treatment_plan)
```

### Garden entities

```
GardenProfile
  ├── Bed       (with user_id index, care timestamps)
  ├── Container (with user_id index, care timestamps)
  └── Plant     (with user_id index, status index, care timestamps)
        └── PlantBatch  (seed/cutting provenance)
```

### Activity log

```
ActivityEvent  ──── written by every tool that mutates state
  └── ActivitySubject  ──── links the event to affected entities
                            (subject_type + subject_id + role)
```

Every tool calls `record_create_event`, `record_update_event`, `record_delete_event`, or `record_activity_event` from `agent/domain/activity_log.py`. Events have `project_id` for project-scoped queries plus `ActivitySubject` rows for per-entity queries. `resolve_interaction_record` records `interaction_resolved` events so user decisions appear in the timeline.

### Other state tables

- `WeatherSnapshot` — persisted weather forecast + derived impacts
- `WeatherTaskChangeSet` — approval-gated weather-driven task adjustments
- `TriageSnapshot` — persisted daily triage output with recommended task IDs
- `InteractionRecord` — persisted record of every interaction envelope shown to the user

### Key indexes

- All tables with `user_id`: indexed (`Plant`, `Bed`, `Container`, `PlantBatch`)
- `Task`: indexed on `project_id`, `revision_id`, `status`, `scheduled_date`, `deadline`, `priority`
- `ActivityEvent`: indexed on `created_at`, `project_id`, `event_type`, `revision_id`
- `ProjectBed`: unique on `(project_id, bed_id)` — prevents duplicate assignments
- `ProjectContainer`: unique on `(project_id, container_id)`

---

## LangGraph checkpoint store

LangGraph persists conversation state (messages, `GardenState` fields, pending interaction) in a checkpoint store keyed by `thread_id`.

| Current | Target |
|---|---|
| `SqliteSaver` (`rhizome_checkpoints.db`) | `langgraph-checkpoint-postgres` |

The Postgres checkpointer is a drop-in replacement. Migrating both the application DB and the checkpoint store to Postgres is a prerequisite for running multiple Rhizome agent instances (stateless agents require shared external state).

---

## Session state (`GardenState`)

Fields carried across turns in `GardenState` (`agent/core/state.py`):

- `messages` — full conversation history (LangGraph messages)
- `pending_interaction` — current interaction envelope awaiting user response
- `interaction_history` — resolved interactions from this session
- `skip_tool_node` — routing hint set by `interaction_node` after a cancelled operation

`user_id` flows through `graph.config["configurable"]["user_id"]` — never stored in state.

---

## Multi-tenancy status

Currently `user_id == 1` is hardcoded in ~15 files across `agent/core/nodes.py` and `agent/tools/`. The DB schema is ready for multi-tenancy (all user-owned tables have `user_id` columns and indexes). Threading `user_id` from `graph.config["configurable"]["user_id"]` into every tool query is Phase 1 of Rhizome multi-tenancy work, which starts after Cambium is providing authenticated `user_id` values.
