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

## Test counts (current)
- Total (excluding E2E): **706 tests** — unit + integration + graph + API
- E2E tests (require live k3s cluster): `tests/e2e/test_full_stack.py`

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
- `agent/api/routers.py`: ~115 data endpoints across all domains (garden, projects, tasks,
  operations, activity, calendar, shopping) + agent endpoints (streaming + non-streaming + resume)
- `agent/api/views.py`: Pydantic view models for all P0 entities — all data endpoints return
  structured JSON, not `{"result": "string"}`. Views: GardenProfileView, BedView, ContainerView,
  PlantSummaryView/DetailView, CareStateView, TaskSummaryView/DetailView, ProjectSummaryView/DetailView,
  TaskSeriesView, CalendarAnnotationView, ProjectExpenseView, ShoppingItemView
- `server.py`: uvicorn entry point (`PORT` env var, default 8001)
- Multi-tenancy: `_set_user()` sets `current_user_id` ContextVar before every data endpoint;
  agent endpoint passes `user_id` via `config["configurable"]`
- 501 tests passing

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

**Frontend API pass complete (2026-06-19):**
- `ActivityEvent.user_id` column added (migration); `list_recent_activity_entries` now scopes
  to current user — multi-tenancy bug fixed
- `GET /activity/stats`: totals + by_day aggregation, group_by=day|week
- All P0 GET endpoints return structured JSON (views.py). Route ordering fixed (literal routes
  before parameterized).
- New endpoints: `POST/DELETE /tasks`, `POST/DELETE /tasks/series`, `POST/DELETE /tasks/{id}/dependencies`
  (BFS cycle detection), `PATCH /projects/{id}/tasks/bulk`, `GET /projects/{id}/tasks?include_dependencies=true`
- Garden detail: `GET /garden/beds|containers|plants/{id}`, `POST /garden/beds`, location/bed_id/container_id
  filters on plants, `?available=true` on beds/containers
- New models + migrations: `CalendarAnnotation`, `ProjectExpense`, `ShoppingItem`
- Calendar CRUD, expense CRUD + budget summary, shopping CRUD + purchase action
- `Task.revision_id` and `generation_run_id` nullable (user-created tasks); same for `TaskSeries`

**Group B complete (2026-06-19):**
- Quick care recording: POST /garden/{plants|beds|containers}/{id}/care — single endpoint
  collapses find-existing-task + complete (or direct care timestamp update) into one call.
  Validates care_type per subject type. _CARE_TYPE_MAP + _record_care() shared helper.
- Incident CRUD gaps: PATCH/DELETE /incidents/{id}, GET /incidents with 6 new filters
  (severity, incident_type, since, before, subject_type, subject_id), POST /incidents/{id}/treatment/manual
  (returns 409 on duplicate draft), PATCH/DELETE /treatment-plans/{id} (blocked if approved).
  _get_incident_for_user() ownership helper for all write endpoints.
- 529 tests passing; test_groupb_endpoints.py has 28 tests.

**Unified entity search complete (zinnia → main, 2026-06):**
- `#126` closed via PR #131. See `docs/current_work/zinnia_unified_search.md`.

**Thread pinned context complete (verbena, 2026-06):**
- `#127` closed — implemented on `verbena`, not yet merged to main.
- `Thread.pinned_context` JSON column; POST/DELETE `/threads/{id}/context`; `initial_context`
  on thread creation; `session_context_intake` injects a "Pinned context" summary per turn.

**Notification SSE complete (verbena, 2026-06):**
- `#130` closed — implemented on `verbena`, not yet merged to main.
- `agent/domain/notifications.py`: per-user `asyncio.Queue` event bus (process-local), `push_event()`
  best-effort delivery, in-memory `active_jobs` registry, `make_event_sink()`.
- `GET /internal/data/notifications/stream` — SSE, 30s heartbeat, queue created on connect,
  removed on disconnect (generator `finally`).
- `GET /internal/data/notifications` — sync snapshot: pending alerts, pending interactions,
  active jobs. Optional `since` filter.
- Job instrumentation (`event_sink` param, `None` by default — cron/CLI usage unchanged):
  `build_triage_snapshot` (4 steps), `refresh_weather_snapshot`/`apply_weather_impacts` (3 steps),
  `materialize_task_series` wrapper in `series_job` (1 step), `draft_treatment_plan` tool
  (job_started/job_complete/job_failed only, no intermediate steps).
- Alert push wired into both `MonitorAlert` creation points (`agent/domain/weather.py`
  `_write_monitor_alert`, `scripts/monitor.py` `_write_alert`); interaction push wired into
  `record_interaction_summary` via `current_user_id.get()`.
- 50 new tests (663 total). SSE endpoint tested at the async-generator level, not through
  `TestClient` — see `tests/DEFERRED_TESTS.md` ("GET /internal/data/notifications/stream").

**Structured JSON backlog — in progress (verbena, 2026-06-21):**
- `#120` ("structured JSON for all data endpoints") was closed prematurely — only its P0 tier
  actually shipped. `#132` documents the root cause (a later commit referencing "#120" for an
  unrelated fix made the P1/P2 checklist look done when it wasn't) and splits the remaining
  scope into `#133`–`#139`, one per frontend page blocked.
- `#138` closed — `GET /garden/locations/{location}` now returns `LocationResultsView`
  (`{beds, containers, plants}`) via direct SQLAlchemy + the existing `BedView`/`ContainerView`/
  `PlantSummaryView` serializers, instead of `{"result": "<prose>"}`.
- `#136` closed — all four `/interactions/*` endpoints now return `InteractionEnvelopeView`
  via a new `interaction_record_to_view_data()` serializer (`agent/domain/interactions.py`).
  Found and fixed a live bug in the process: `POST /interactions/{id}/resolve` was 500ing on
  every call — `ResolveInteractionRequest`'s `action`/`notes` fields never matched the
  `resolve_interaction` tool's `action_id`/`inputs` parameters, so the dict-spread call into
  `.invoke()` raised a pydantic `ValidationError` before the tool body ran. Confirmed broken via
  a live curl call against the dev server, fixed by translating explicitly in the router.
- Dev Postgres was 3 Alembic migrations behind head (`interaction_record.user_id`,
  `incident_report.user_id`, `weather_snapshot`/`triage_snapshot.garden_profile_id`) — applied
  via `alembic upgrade head`. Worth checking `alembic current` after any session that adds a
  migration but only tests against in-memory SQLite, since tests never catch a missing
  migration on the dev/staging Postgres instance.
- Still open: `#133` (triage/weather), `#134` (activity feed), `#135` (incidents/treatment
  plans), `#137` (projects), `#139` (ThreadView, lower priority/no functional gap).

**Next in Rhizome:**
- Garden spatial layout model and map endpoints (`#118`)
- Media/image attachments for garden objects (`#117`)
- Pest intelligence (deferred from calendula Phase 5): iNaturalist + image-based pest ID + RAG

## Known issues
- `ActivityEvent.revision_id` FK is defined in the model; enforced in Postgres (staging/prod), not SQLite (dev/test)
- JSON columns use `Column(JSON, ...)` — JSONB would give better indexing; deferred to Intelligence track
- `public` schema is empty; all tables are in `rhizome` schema ✓
- ~~`InteractionRecord` has no `user_id` column~~ — fixed: `user_id` column added
  (migration `a1b2c3d4e5f6`), `record_interaction_summary` stamps it from `current_user_id`,
  and every read path (`get_pending_interaction_record`, `list_recent_interaction_records`,
  `find_pending_interaction_record`, `GET /notifications`, and the by-id lookups in
  `nodes.py`/`tools/operations/interactions.py`) is now scoped to the current user.
- ~~`user_id` type inconsistency (str vs int)~~ — fixed: `agent/domain/notifications.py`
  normalizes `user_id` to `str` at every entry point, and the misleading `int` type hints in
  `weather_job`/`triage_job`/`series_job`/`apply_weather_impacts`/etc. were corrected to `str`.
- ~~`GardeningProject` resolved by id with no ownership check in domain-layer helpers~~ — fixed:
  `_resolve_project` (`tools/projects/planning.py`), `_select_project` (`domain/planner.py`,
  `domain/tracker.py`) now filter by `user_id == current_user_id.get()`. These gated most
  project-planning agent tools, so the gap had wide blast radius — see audit below.
- ~~`IncidentReport` had no `user_id` column~~ — fixed, same pattern as `InteractionRecord`
  (migration `b2c3d4e5f6a7`). See audit below.
- ~~`get_activity_for_subject` had no `user_id` filter~~ — fixed, scoped to `current_user_id`.
- ~~`WeatherSnapshot`/`TriageSnapshot` have no `user_id` or `project_id` at all~~ — fixed: both
  now carry `garden_profile_id` (migration `c3d4e5f6a7b8`), since location lives on
  `GardenProfile` rather than directly on the user. See the multi-tenancy audit below.

### Post-#130 user_id audit (2026-06-20)

Triggered by the `InteractionRecord` and `user_id` type findings above. Audited every model in
`db/models.py` for missing/inconsistent user scoping. Findings, in order fixed:
1. `GardeningProject` lookups without ownership checks (highest blast radius — root of most of
   the schema; fixed).
2. `IncidentReport` missing `user_id` (fixed, same shape as `InteractionRecord`).
3. `get_activity_for_subject` missing scoping (fixed).
4. `WeatherSnapshot`/`TriageSnapshot` single-tenant design (fixed in the follow-up audit below).

Everything else (`GardenProfile`, `Bed`, `Container`, `Plant`, `PlantBatch`, `Conversation`,
`Thread`, `CalendarAnnotation`, `ProjectExpense`, `ShoppingItem`, `MonitorAlert`, `MonitorRun`)
already had a `user_id` column with correctly scoped queries.

### Multi-tenancy follow-up audit (2026-06-20)

Different users have different garden locations, so weather/triage data must not be shared
across them. Audited for any other functionality that assumes single-tenancy (shared/global
state, not just missing `user_id` columns). Findings:

- **`WeatherSnapshot`/`TriageSnapshot` were genuinely shared across all users** — confirmed
  exploitable through 7 agent tools (`refresh_weather_snapshot`, `get_latest_weather_snapshot`,
  `list_weather_impacted_tasks`, `draft_weather_task_changes`, `approve_weather_task_changes`,
  `get_latest_triage_snapshot`, `list_triage_recommendations`) plus `GET /triage/latest`. Tasks
  themselves were always correctly scoped per-user; the weather/triage *data* overlaid on them
  was not — whichever user refreshed weather last won for everyone. Fixed: both tables now carry
  `garden_profile_id` (migration `c3d4e5f6a7b8`, backfilled to the bootstrapped user's profile).
  `get_latest_weather_snapshot`/`get_latest_triage_snapshot` resolve the current user's
  `GardenProfile` and scope to it; `refresh_weather_snapshot`/`build_triage_snapshot` stamp it on
  create; `approve_weather_task_changes` now joins through
  `WeatherSnapshot.garden_profile_id → GardenProfile.user_id` instead of trusting `change_set_id`
  alone (same shape as the `IncidentReport`/`TreatmentPlan` fix).
- No other unscoped global state found: `agent/core/model.py`'s model-client cache and the
  LangGraph checkpointer are stateless/thread-safe; `current_user_id` is reliably set at every
  entry point (HTTP, SSE, cron, graph nodes); `agent/domain/search.py` scopes all entity types;
  `DEFAULT_PLANT_RULES` and other module-level constants are read-only.
- `scripts/monitor.py`'s cron only ever runs jobs for one `--user-id` per invocation — not a bug,
  but means multi-user weather refresh requires an orchestrator that calls it once per user. Not
  addressed here since no such orchestrator exists yet; revisit alongside actual multi-user cron
  scheduling.

## Invariants — never violate
- **Model access only through `agent/core/model.py`.** Never instantiate a model client directly or at import time anywhere else.
- **No hardcoded user identity.** Never write `user_id == 1` or any literal user identity. User identity flows from `graph.config["configurable"]["user_id"]`.
- **Every DB query on user-owned data must be scoped to the owning user.** Filtering by entity `id` alone is a bug.
- **Every new model/table needs a `user_id` column at creation time.** Don't rely on a nullable
  FK chain (e.g. `project_id`) for scoping — if the FK is ever null (common for objects that
  aren't always project-attached, like confirmations or triage interactions), there's no way to
  scope the row to a user without a schema change later. Add `user_id` directly on the model
  when it's created, even if it duplicates what's derivable via a join. `InteractionRecord`
  shipped without one and silently leaked every user's pending interactions to every other user
  until it was retrofitted (migration `a1b2c3d4e5f6`) — don't repeat that mistake.
- **Untrusted content writes go through `interaction_node`.** Any tool writing data derived from external sources must create an interaction envelope and wait for user confirmation before persisting.
- **Never call `datetime.utcnow()`.** Use `datetime.now(timezone.utc).replace(tzinfo=None)` for DB columns (naive UTC). For non-DB use, plain `datetime.now(timezone.utc)` is fine.
- **Status transition guards.** `complete_task`, `skip_task`, `defer_task` reject `done`/`superseded` targets. `start_task` rejects `done`/`skipped`/`superseded`. Do not bypass these guards.
- **`delete_project` requires no active tasks.** The tool blocks if non-superseded tasks exist. Use `update_project(status='complete')` for finished projects.
- **Tests required for every new feature.** `python -m pytest` must be green before any task is done.

## Postgres notes

`DATABASE_URL` drives the backend — unset/SQLite for local dev and tests, `postgresql://` for staging/prod. The LangGraph checkpointer follows the same env var. Both the SQLAlchemy engine and the psycopg checkpointer connection use `search_path=rhizome` so all tables live in the `rhizome` schema.

**Alembic** manages schema migrations. Workflow:
```bash
# Apply pending migrations (run before starting the server after a schema change)
alembic upgrade head

# After modifying db/models.py, generate a new migration:
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

Tests use in-memory SQLite via `init_db()` — they do not use Alembic. `init_db()` in `db/database.py` is kept as a safety net for fresh installs and tests only.

For HA: run Postgres with streaming replication (Patroni or pg_auto_failover). `pool_pre_ping=True` is set on the engine to handle restarts.

**pgvector** is in `requirements.txt` but not yet enabled. Needed for the RAG / pest intelligence epic: `CREATE EXTENSION IF NOT EXISTS vector;` then `alembic revision --autogenerate`.
