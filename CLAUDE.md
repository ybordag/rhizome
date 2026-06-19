# Rhizome — Claude Code Memory

## Branch
Active development is on `geranium`. `main` is behind — do not treat it as current or merge until intentionally reconciled.

## Build and test
```
pip install -r requirements.txt -r requirements-dev.txt

/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest               # full suite (325 tests)
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m unit        # fast unit tests
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m integration # database-backed tests
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m graph       # graph and orchestration tests
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m live        # live API smoke tests (requires provider keys)
```
Requires at least one provider key in `.env` to run the CLI (`GOOGLE_API_KEY` is the default).
Tests mock the model and run without any key. Live tests (`-m live`) auto-skip if the relevant key is absent.
Use the `RHIZOME_ENV` conda environment — never install into the base environment.

## Project layout
```
agent/
  core/
    graph.py        — LangGraph workflow: session_context_intake → weather_context_loader
                      → triage_reasoner → llm_call → {interaction_node | tool_node | END}
    nodes.py        — all graph node implementations and routing functions
    state.py        — GardenState TypedDict
    model.py        — multi-provider model factory (google_genai | openai | anthropic);
                      get_model(config) / get_triage_model(config) accept optional per-request
                      provider/provider_key from config["configurable"] (Cambium injection path),
                      falling back to RHIZOME_MODEL_PROVIDER + provider key env vars for local dev
    telemetry.py    — OTel + observer framework wired into all node transitions
    temporal.py     — timezone handling, temporal context, session context inference

  domain/
    activity_log.py — ActivityEvent write helpers (record_create/update/delete/activity_event)
                      and read helpers (get_activity_for_subject, list_recent_activity_entries
                      with filtering + cursor pagination)
    care.py         — care action inference (infer_care_action) and side-effect propagation
                      from task completion to plant/bed/container care timestamps
    incidents.py    — incident report and treatment plan lifecycle
    interactions.py — interaction envelope builders, resolve_interaction_record
                      (now writes interaction_resolved activity events)
    planner.py      — proposal estimation (cost, timeline, effort), feasibility checking,
                      planning context assembly
    tracker.py      — task generation from execution specs, lifecycle state machine,
                      dependency/blocking logic, daily priority scoring,
                      cascade_defer_to_dependents, get_daily_priority_tasks
    triage.py       — triage snapshot builder; secondary LLM call at session start
    weather.py      — Open-Meteo integration and weather impact derivation

  tools/            — 93 tools, all registered in tools/__init__.py
    garden/
      beds_containers.py  — bed and container CRUD
      plants.py           — plant and batch CRUD, status lifecycle
      profile.py          — garden profile read/update
      search.py           — search_garden, list_by_location (N+1-free bulk lookups)
    projects/
      planning.py         — brief, proposal, revision, execution spec, schedule preview
      projects.py         — project CRUD, bulk location assignment (assign_beds/containers_to_project),
                            get_project_progress
      tracker.py          — task generation, lifecycle actions, daily priority tool
    operations/
      activity.py         — per-entity history tools (get_task_activity, get_incident_activity,
                            get_plant_activity, etc.), list_project_activity (cross-object timeline
                            with filtering + pagination), list_recent_activity
      care.py             — get_current_care_state, get_recent_care_history
      incidents.py        — list_incidents, get_incident, report_incident, treatment plan lifecycle
      interactions.py     — pending/recent interaction query and resolution tools
      triage.py           — run_daily_triage, get_latest_triage_snapshot
      weather.py          — weather snapshot refresh, impacts, task change approval

db/
  models.py         — SQLAlchemy models. Core lifecycle:
                      GardenProfile → GardeningProject → ProjectBrief →
                      ProjectProposal → ProjectRevision → ProjectExecutionSpec →
                      TaskGenerationRun → Task (with Task.priority, TaskDependency, TaskSeries)
                      Plus: ActivityEvent/ActivitySubject, IncidentReport/TreatmentPlan,
                      InteractionRecord, WeatherSnapshot, TriageSnapshot
  database.py       — SQLite session factory and current_user_id ContextVar
  seed.py           — dev seed data

tests/
  agent/
    core/           — test_graph, test_nodes, test_node_edge_cases, test_telemetry,
                      test_model (15 unit tests), test_model_live (live endpoint smoke tests)
    domain/         — test_domain_logic (compute_task_blocked_state, planner estimates,
                      infer_care_action, _resolve_subjects)
  tools/
    garden/         — test_plants, test_beds_containers, test_profile, test_search
    projects/       — test_projects, test_planning, test_task_tracker_tools,
                      test_priority_and_progress, test_bulk_assign, test_query_efficiency
    operations/     — test_triage_care_incident_operations, test_activity, test_interaction_tools,
                      test_status_and_orphans, test_activity_history
  db/               — test_activity_log, test_interactions, test_planner, test_tracker,
                      test_temporal_weather_triage_helpers
  support/          — factories.py, fakes.py, patching.py
  DEFERRED_TESTS.md — consciously deferred test areas with rationale and re-enable criteria

main.py             — CLI entrypoint
```

## Current state

**Phases 1–5 complete** (activity log, project planner, task tracker, operational triage + weather, structured interactions). The full **plan → task → triage → action → history** loop works in the CLI.

**API readiness work complete (geranium, 2026-06):**
- 93 tools (up from 72), all organized into `garden/`, `projects/`, `operations/` subdirs
- `Task.priority` field (`critical/high/normal/low`), auto-assigned at generation, user-overridable
- `get_daily_priority_tasks` — deterministic scoring across urgency, type, priority, triage alignment, blocking count
- `cascade_defer_to_dependents` — deferred task cascades earliest_start to direct dependents
- Gap-fill tools: `list_incidents`, `get_incident`, `get_project_proposal`, `get_project_progress`
- Bulk location assignment: `assign_beds_to_project`, `assign_containers_to_project`
- Status transition guards on `complete_task`, `skip_task`, `defer_task`
- `delete_project` blocked when active tasks exist (prevents orphan task rows)
- N+1 query fixes in `list_projects`, `get_project`, `search_garden`, `list_by_location`
- DB schema: user_id indexes on Plant/Bed/Container/PlantBatch, unique constraints on ProjectBed/ProjectContainer, ActivityEvent.revision_id FK
- Action history: `get_task_activity`, `get_incident_activity`, `list_project_activity`, enhanced `list_recent_activity` with DB-level filtering and cursor pagination; `interaction_resolved` events now recorded by `resolve_interaction_record`
- 325 tests, 0 failures; `tests/DEFERRED_TESTS.md` documents 11 consciously deferred areas

**Model provider abstraction complete (geranium, 2026-06):**
- `agent/core/model.py` rewritten as a multi-provider factory: `google_genai`, `openai`, `anthropic`
- `get_model(config)` / `get_triage_model(config)` accept per-request `provider` + `provider_key`
  from `config["configurable"]` (the Cambium injection path); env-var fallback for local dev
- Default models: `gemini-2.5-flash` (Google), `gpt-4o` (OpenAI), `claude-sonnet-4-6` (Anthropic)
- `model_with_tools` in `nodes.py` is now lazy (`None` at module level); `llm_call` accepts `config`
  and calls `get_model(config).bind_tools(tools)` — per-request provider flows end-to-end
- 15 unit tests cover routing, env fallback, error paths, caching; 3 live smoke tests (`-m live`)
  confirm all three provider endpoints respond (auto-skip when key is absent)
- `gemini-2.0-flash` was retired by Google; updated default and `.env` to `gemini-2.5-flash`
- Added `langchain-openai` and `langchain-anthropic` to `requirements.txt`

**Active work — Cambium (Go API gateway):**
- Cambium sits between Verdant (React frontend) and Rhizome
- Handles JWT auth, bcrypt password hashing, refresh token rotation
- Proxies all `/api/v1/*` to Rhizome's internal HTTP interface
- See `../cambium/CLAUDE.md` for Cambium's build plan and invariants

**Active work — `calendula` branch (reactive monitoring):**
- Scheduled cron runner (`scripts/monitor.py`) for weather refresh, triage, series materialization
- `MonitorAlert` + `MonitorRun` models — alert persistence queryable without a session
- Auto-apply critical weather changes (storm, severe frost, high heat); queue moderate for approval
- Safe/unsafe outdoor working window advisory alerts
- Session-start delivery via `session_context_intake` + `llm_call` system prompt injection
- Phase 5: iNaturalist pest monitoring (later)
- See `docs/current_work/calendula_reactive_monitoring.md` for full plan

**Active work — `iris` branch (image modality):**
- Image input to Rhizome agent (multimodal `HumanMessage` handling)
- Branch created, plan not yet started

**Next in Rhizome:**
- Postgres migration (prerequisite for multi-instance deployment and FK enforcement)
- Multi-tenancy: thread `user_id` from JWT (via Cambium) into every tool query
- FastAPI layer for internal HTTP interface (Cambium → Rhizome)

## Known issues
- `user_id == 1` hardcoded in ~15 files across `agent/core/nodes.py` and `agent/tools/` — Phase 1 work (multi-tenancy)
- `ActivityEvent.revision_id` FK is defined in the model but SQLite does not enforce it at runtime; enforcement lands with Postgres migration
- SQLite `ProjectBed`/`ProjectContainer` unique constraints are enforced by the DB for new inserts but cannot be added retroactively to an existing SQLite DB without a migration script

## Invariants — never violate
- **Model access only through `agent/core/model.py`.** Never instantiate a model client directly or at import time anywhere else.
- **No hardcoded user identity.** Never write `user_id == 1` or any literal user identity. User identity flows from `graph.config["configurable"]["user_id"]`.
- **Every DB query on user-owned data must be scoped to the owning user.** Filtering by entity `id` alone is a bug.
- **Untrusted content writes go through `interaction_node`.** Any tool writing data derived from external sources must create an interaction envelope and wait for user confirmation before persisting.
- **Never call `datetime.utcnow()`.** Use `datetime.now(timezone.utc).replace(tzinfo=None)` for DB columns (naive UTC). For non-DB use, plain `datetime.now(timezone.utc)` is fine.
- **Status transition guards.** `complete_task`, `skip_task`, `defer_task` reject `done`/`superseded` targets. `start_task` rejects `done`/`skipped`/`superseded`. Do not bypass these guards.
- **`delete_project` requires no active tasks.** The tool blocks if non-superseded tasks exist. Use `update_project(status='complete')` for finished projects.
- **Tests required for every new feature.** `python -m pytest` must be green before any task is done.

## Postgres migration notes
`requirements.txt` includes `psycopg2-binary` and `pgvector`. When migrating:
- Swap `langgraph-checkpoint-sqlite` → `langgraph-checkpoint-postgres` in requirements
- Update `db/database.py` engine and session factory
- LangGraph's Postgres checkpointer is a drop-in for SqliteSaver
- Run Postgres with streaming replication for HA (Patroni or pg_auto_failover)
- This migration is a prerequisite for multi-instance deployment and proper FK enforcement
