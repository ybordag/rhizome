# Rhizome — Claude Code Memory

## Branch
`geranium` merged into `main`. Active feature branches: `calendula` (reactive monitoring, Phases 1–4 done, pending merge). `iris` deleted — image modality work not yet started.

## Build and test
```
pip install -r requirements.txt -r requirements-dev.txt

/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest               # full suite (421 tests)
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

  tools/            — 95 tools, all registered in tools/__init__.py
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
                      InteractionRecord, WeatherSnapshot, TriageSnapshot,
                      MonitorRun, MonitorAlert
  database.py       — SQLAlchemy engine (SQLite in dev/test, Postgres in staging/prod via
                      DATABASE_URL); current_user_id ContextVar; init_db(), get_session()
  seed.py           — dev seed data

scripts/
  monitor.py        — standalone cron runner: weather_job, triage_job, series_job
                      (--job weather|triage|series|all, --user-id)

tests/
  agent/
    core/           — test_graph, test_nodes (incl. monitor alert injection), test_node_edge_cases,
                      test_telemetry, test_model (15 unit), test_model_live (live smoke tests)
    domain/         — test_domain_logic (compute_task_blocked_state, planner estimates,
                      infer_care_action, _resolve_subjects), test_weather_monitor
  tools/
    garden/         — test_plants, test_beds_containers, test_profile, test_search
    projects/       — test_projects, test_planning, test_task_tracker_tools,
                      test_priority_and_progress, test_bulk_assign, test_query_efficiency
    operations/     — test_triage_care_incident_operations, test_activity, test_interaction_tools,
                      test_status_and_orphans, test_activity_history
  db/               — test_activity_log, test_interactions, test_planner, test_tracker,
                      test_temporal_weather_triage_helpers, test_monitor_models,
                      test_monitor_jobs
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
- ~326 tests, 0 failures; `tests/DEFERRED_TESTS.md` documents 11 consciously deferred areas

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

**FastAPI internal layer complete (narcissus → main, 2026-06):**
- `agent/api/app.py`: FastAPI app with two routers + `/health`
- `agent/api/routers.py`: ~80 data endpoints across all domains (garden, projects, tasks,
  operations, activity) + agent endpoints (streaming + non-streaming + resume)
- `server.py`: uvicorn entry point (`PORT` env var, default 8001)
- Multi-tenancy: `_set_user()` sets `current_user_id` ContextVar before every data endpoint;
  agent endpoint passes `user_id` via `config["configurable"]`
- 408 tests passing; streaming tests in DEFERRED_TESTS.md

**Active work — Cambium (Go API gateway):**
- Phases 1–3 complete (auth, key management, Rhizome proxy, SSE streaming)
- Phases 1–4 complete (periderm merged); Phase 5 (fibril branch): thread management
- See `../cambium/CLAUDE.md` for full build plan and invariants

**Reactive monitoring complete (calendula, 2026-06):**
- `MonitorAlert` + `MonitorRun` models; `scripts/monitor.py` cron runner (weather, triage, series jobs)
- `apply_weather_impacts()`: critical weather auto-applied, moderate queued, working window advisories written
- `unsafe_outdoor_window` / `safe_outdoor_window` impact types in `derive_weather_impacts()`
- `GardenState.monitor_alerts`; session-start alert injection into system prompt
- `triage_job()` writes triage alert when urgent tasks exist; `series_job()` materialises recurring tasks
- 43 new tests (13 model, 14 weather monitor, 7 node, 9 job)
- Phase 5 (iNaturalist pest ingestion) deferred — see planning note below
- See `docs/current_work/calendula_reactive_monitoring.md` for full implementation record

**Upcoming — visual garden understanding (image modality):**
- Image input to Rhizome agent (multimodal `HumanMessage` handling)
- Plant/disease/pest identification from photos
- See `docs/roadmap/initiatives/visual_garden_understanding.md`

**Postgres migration complete:**
- `db/database.py` switches on `DATABASE_URL`: SQLite for dev/test, Postgres for staging/prod
- `agent/core/graph.py` checkpointer switches between `SqliteSaver` and `PostgresSaver`
- `.env` already points at `postgresql+psycopg2://postgres:dev@localhost:5432/postgres`
- `psycopg2-binary` + `langgraph-checkpoint-postgres` in `requirements.txt`
- Schema uses `Base.metadata.create_all(engine)` — no Alembic yet; fine for fresh installs
- `pgvector` extension not yet enabled — needed for RAG (future epic)

**Thread management complete (narcissus, 2026-06):**
- `Thread` model: id = LangGraph thread_id (botanical name), user_id, title (auto from first
  message), project_id?, last_message_preview, last_active_at, message_count, created_at
- `session_context_intake` upserts thread metadata on every turn via `_upsert_thread()`
- Five data endpoints: POST (register, idempotent), GET list (sorted by last_active_at),
  GET {id}, GET {id}/messages (from LangGraph checkpoint), DELETE
- 13 tests; 421 total tests passing

**Next in Rhizome:**
- Multi-tenancy: audit all tool queries for `user_id` scoping (currently defaults to 1 in CLI)
- Pest intelligence (deferred from calendula Phase 5): iNaturalist + image-based pest ID + RAG
  — after visual garden understanding initiative

## Known issues
- `user_id == 1` hardcoded in ~15 files across `agent/core/nodes.py` and `agent/tools/` — will be fixed in the multi-tenancy workstream
- `ActivityEvent.revision_id` FK is defined in the model but only enforced in Postgres (not SQLite dev); Postgres is now in use for staging/prod so enforcement is active there
- No Alembic migration tooling yet — schema changes require manual `ALTER TABLE` on live Postgres or a full re-create; acceptable for now, needed before the first production schema change

## Invariants — never violate
- **Model access only through `agent/core/model.py`.** Never instantiate a model client directly or at import time anywhere else.
- **No hardcoded user identity.** Never write `user_id == 1` or any literal user identity. User identity flows from `graph.config["configurable"]["user_id"]`.
- **Every DB query on user-owned data must be scoped to the owning user.** Filtering by entity `id` alone is a bug.
- **Untrusted content writes go through `interaction_node`.** Any tool writing data derived from external sources must create an interaction envelope and wait for user confirmation before persisting.
- **Never call `datetime.utcnow()`.** Use `datetime.now(timezone.utc).replace(tzinfo=None)` for DB columns (naive UTC). For non-DB use, plain `datetime.now(timezone.utc)` is fine.
- **Status transition guards.** `complete_task`, `skip_task`, `defer_task` reject `done`/`superseded` targets. `start_task` rejects `done`/`skipped`/`superseded`. Do not bypass these guards.
- **`delete_project` requires no active tasks.** The tool blocks if non-superseded tasks exist. Use `update_project(status='complete')` for finished projects.
- **Tests required for every new feature.** `python -m pytest` must be green before any task is done.

## Postgres notes
Migration is complete. `DATABASE_URL` drives the backend — unset/SQLite for local dev and tests, `postgresql://` for staging/prod. The LangGraph checkpointer follows the same env var.

When adding schema changes: run `Base.metadata.create_all(engine)` for fresh installs. For live Postgres with existing data, write a manual migration script until Alembic is in place.

For HA: run Postgres with streaming replication (Patroni or pg_auto_failover). `pool_pre_ping=True` is already set on the Postgres engine to handle restarts gracefully.

**pgvector** is in `requirements.txt` but not yet enabled or used. It will be needed for the RAG / pest intelligence epic.
