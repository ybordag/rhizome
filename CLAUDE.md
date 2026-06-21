# Rhizome — Claude Code Memory

## Branch
`geranium` merged into `main`. Active feature branches: `calendula` (reactive monitoring, Phases 1–4 done, pending merge), `verbena` (current branch — structured-JSON backlog #133–#141, 15 commits ahead of `origin/verbena`, not yet merged to main). `iris` deleted — image modality work not yet started.

## Build and test
```
pip install -r requirements.txt -r requirements-dev.txt

/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest               # full suite (817 tests, excl. E2E)
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m unit        # fast unit tests
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m integration # database-backed tests
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m graph       # graph and orchestration tests
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m live        # live API smoke tests (requires provider keys)
```
Requires at least one provider key in `.env` to run the CLI (`GOOGLE_API_KEY` is the default).
Tests mock the model and run without any key. Live tests (`-m live`) auto-skip if the relevant key is absent.
Use the `RHIZOME_ENV` conda environment — never install into the base environment.

## Test counts (current)
- Total (excluding E2E): **817 tests** — unit + integration + graph + API
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
- `#133` closed — `GET /triage/latest`, `GET /weather/latest`, `POST /weather/refresh`,
  `GET /weather/tasks/impacted`, `PATCH /weather/changesets/{id}/approve` now return
  `TriageSnapshotView`/`WeatherSnapshotView`/`WeatherImpactedTaskView`/`WeatherTaskChangeSetView`.
  `TriageSnapshotView` resolves urgent/routine/project task IDs into full `TaskSummaryView`
  objects rather than bare IDs. Also fixed two related error-handling gaps found while wiring
  it: `refresh_weather_snapshot`'s "no profile/location" `ValueError` was previously a 200 with
  an error string baked into prose — now a 400; `approve_weather_task_changes` previously
  returned 200-with-embedded-error-text for both "not found" and "already approved" — now
  404 and 400 respectively. Post-merge coverage audit found zero router-level cross-user tests
  for `weather/latest`, `weather/tasks/impacted`, and the changeset approve endpoint despite the
  domain layer already being correctly scoped — added 3 tests in `test_user_isolation_api.py`.
- `#140` closed — the remaining mutation/activity endpoints left over after #133/#136/#138:
  `PATCH /garden/profile`, `PATCH /garden/beds/{id}`, `POST`/`PATCH /garden/containers`,
  `POST`/`PATCH /garden/plants`, `POST`/`PATCH /garden/plants/batch`, `PATCH /tasks/{id}`,
  `PATCH /tasks/series/{id}`, and `GET .../activity` for tasks/plants/beds/containers/batches/
  projects. These tools return human-readable strings for both success and failure (the LLM
  reads them), so the router can't just try/except — added `_mutation_error_status()`
  (`agent/api/routers.py`) to classify a tool's string result into 404/400/success by pattern.
  New views: `ActivityEventView`, `ActivitySubjectView`, `PlantBatchResultView`. New domain
  serializer: `activity_event_to_view_data()` (`agent/domain/activity_log.py`).
  Found and fixed a live routing bug in the process: `PATCH /garden/plants/batch` and
  `PATCH /garden/plants/batch/remove` were registered *after* `PATCH /garden/plants/{plant_id}`,
  so Starlette's order-of-registration matching let `{plant_id}` swallow the literal `"batch"`
  segment — both endpoints had likely never been reachable. Fixed by moving the literal routes
  before the parametrized ones (same fix already applied elsewhere per the 2026-06-19 entry
  below; this pair had been missed). Also intentionally changed `GET .../activity` to 404 for a
  nonexistent subject id instead of silently returning an empty array — it previously never
  checked the subject existed at all.
  50 tests in `tests/agent/api/test_issue_140_structured_mutations.py` covering structured shape,
  400/404 paths (including the "no garden profile" branch, distinct from "entity not found"),
  and cross-user isolation for all 16 endpoints.
- Still open: `#137` (projects), `#139` (ThreadView, lower priority/no functional gap).

**SSE streaming fix complete (#141, 2026-06-21):**
- `POST /internal/agent/stream` and `POST /internal/agent/resume/stream` were completely broken
  in production, for every provider — `200 OK`, `text/event-stream`, zero bytes of body, every
  time. Root cause: `agent.astream_events()`/`agent.get_state()` (called from inside the running
  async generator) need the LangGraph checkpointer's *async* interface (`aget_tuple`/etc.); the
  module-level `agent` (`agent/core/graph.py`) was built on the sync-only `SqliteSaver`/
  `PostgresSaver`, which raise `NotImplementedError` unconditionally on those methods. The
  non-streaming `/internal/agent`/`/internal/agent/resume` endpoints were unaffected — they only
  call the sync `.invoke()`/`.get_state()` path.
- Fix: `agent/core/graph.py` now exposes `build_agent(checkpointer)` (the shared topology
  builder) and `async def build_async_checkpointer()` (returns an `AsyncSqliteSaver`/
  `AsyncPostgresSaver` + an `aclose` callable). The module-level sync `agent` — used by the CLI
  (`main.py`) and the two non-streaming endpoints — is unchanged. `agent/api/app.py`'s `lifespan`
  builds a *second* agent on the async checkpointer (`app.state.streaming_agent`) when the
  FastAPI app starts, since constructing `aiosqlite`/async `psycopg` connections requires a
  running event loop. Both agents share the same underlying checkpoint tables, so conversation
  state is consistent regardless of which endpoint touched a given `thread_id`.
- `agent/api/routers.py`'s `stream_agent`/`resume_agent_stream` now take the agent via
  `Depends(get_streaming_agent)` instead of referencing the module-level `agent` directly — this
  was the dependency-injection seam `tests/DEFERRED_TESTS.md` had flagged as missing, and is what
  makes the new tests possible. Also swapped `state = agent.get_state(config)` →
  `state = await streaming_agent.aget_state(config)` inside the generators — calling the *sync*
  accessor from the same loop driving the async generator hits a different async-saver guard
  rail (`InvalidStateError`), so this had to change too, not just the checkpointer class.
- Tests: `tests/agent/api/test_streaming_endpoints.py` (5 tests) — drives the real HTTP path via
  `httpx.AsyncClient` + `ASGITransport` (not `TestClient`, which doesn't manage a stable event
  loop across calls the way this needed) against a real `AsyncSqliteSaver`-backed graph, overriding
  `get_streaming_agent` via `app.dependency_overrides`. Covers the plain-turn path, the
  destructive-tool-call-interrupt-then-resume path, token-event forwarding specifically (see
  below), and the Postgres checkpointer branch. Confirmed all of these fail with
  `NotImplementedError` against the *old* sync checkpointer, and again against the *old* router
  code (bare `agent` reference, no `Depends`), before verifying they pass against the fix — not
  just written to pass.
- **Found during the post-merge test review (critical self-review, not just "tests are green"):**
  - `tests/conftest.py` clears `DATABASE_URL` to force SQLite for the whole suite, but that's
    ineffective for anything that imports `agent.core.graph` — `agent.core.model` calls
    `load_dotenv()` unconditionally at import time, and `graph.py` imports `agent.core.nodes`
    (which imports `agent.core.model`) *before* its own `_database_url = os.environ.get(...)` line
    runs. So importing `graph.py` silently repopulates `DATABASE_URL` from `.env` — pointing at the
    real shared dev Postgres — before `_use_postgres` is decided. `fresh_test_graph` was never
    affected (it injects its own SQLite checkpointer and never touches `graph.py`'s module-level
    one), but the first version of the new streaming tests called `build_async_checkpointer()`
    directly and were silently writing real checkpoint rows to the shared dev Postgres instance on
    every test run (confirmed: `stream-thread-1`/`stream-thread-resume` rows in
    `rhizome.checkpoints`, deleted by hand afterward). Fixed by having every SQLite-intent test
    monkeypatch `graph_module._use_postgres = False` explicitly rather than trusting the env var —
    confirmed via `type(checkpointer).__name__ == "AsyncSqliteSaver"` and a real tmp_path file
    appearing on disk. At the time, the underlying `load_dotenv()`-ordering footgun in `graph.py`
    itself was left unfixed (worked around per-test only) — since fixed, see below.
  - The first version only asserted `'"type": "done"' in body` — that proves the pipe didn't crash,
    but `FakeBoundModel.invoke()` is a bare Python call, not a traced `Runnable`, so
    `astream_events()` never emitted `on_chat_model_stream` for it; a regression in the token-
    forwarding branch in `agent/api/routers.py` would have slipped through untested. Added
    `test_stream_agent_emits_token_and_done_events`, using `GenericFakeChatModel`
    (`langchain_core.language_models.fake_chat_models`) — a real streaming-capable `Runnable` — and
    asserting the actual token content round-trips through the SSE response.
  - The Postgres branch of `build_async_checkpointer()` had zero automated coverage — only the
    one-off live curl. Added `test_async_checkpointer_postgres_branch`, which runs against the
    local dev Postgres, skips cleanly if it's unreachable, and deletes its own checkpoint rows
    (`thread_id` is a fresh `uuid4()` each run) so it can't repeat the pollution mistake above.
  - The resume test's assertions were weak (`"done"` appearing anywhere in the body proves
    nothing about *which* AI message ended up persisted). Strengthened to check
    `final_state.values["messages"][-1].content` and `not final_state.next` via `aget_state()` —
    which caught a wrong assumption in the test itself (a second queued fake response that's never
    actually consumed, since `interaction_node` short-circuits on a negative resume without calling
    the model again).
  - SSE body assertions were raw substring checks (`'"type": "done"' in text`). Replaced with a
    real `_parse_sse_events()` helper that splits `data: ` frames and `json.loads`s each one, so
    assertions check the actual last event rather than hoping a substring doesn't appear elsewhere.
- **Found during the follow-up complete audit (confirming, not assuming, that coverage is
  exhaustive):** grepped the whole codebase for every call site of `astream_events`/`aget_state`/
  `.astream(`/`.ainvoke(` outside tests — confirmed the *only* production consumers of the async
  checkpointer interface are the two streaming endpoints in `agent/api/routers.py`, and confirmed
  `tests/agent/api/test_streaming_endpoints.py` is the only test file touching any #141-relevant
  symbol (`graph_module`, `build_async_checkpointer`, `get_streaming_agent`, etc.) — there's no
  second, forgotten test surface for this bug. That audit surfaced two more gaps, both now fixed:
  - No test ever exercised the *real* `agent/api/app.py` lifespan — every test in this file (and
    every other file in `tests/agent/api/`) uses bare `TestClient(app)`, which silently never runs
    FastAPI's lifespan unless entered as `with TestClient(app) as client:`. A typo in
    `app.state.streaming_agent = build_agent(...)`, or `build_async_checkpointer()` raising and
    getting swallowed, would only ever have surfaced live. Added
    `test_app_lifespan_builds_usable_streaming_agent`, which uses the context-manager form and
    calls `/internal/agent/stream` through the unmocked `get_streaming_agent` dependency — no
    override. Confirmed it fails with the right message when the lifespan's assignment is
    deliberately broken, and passes against the real code.
  - `app.state.streaming_agent` is not cleared by FastAPI's lifespan shutdown — confirmed by
    experiment that after `with TestClient(app) as client:` exits, `hasattr(app.state,
    "streaming_agent")` is still `True`, pointing at a graph wired to a now-closed connection. Mostly
    harmless today since no other test touches the streaming endpoints without an override, but
    it's stale state on a shared module-level `app` singleton. The new test wraps its body in
    `try/finally` and explicitly `del app.state.streaming_agent` in the `finally` block.
- Verified live against the actual dev stack (Postgres, per `.env`): `POST /internal/agent/stream`
  now streams real tokens ending in `data: {"type": "done"}`.
- **`load_dotenv()` import-order footgun fixed at the source (2026-06-21):** `agent/core/graph.py`
  now calls `load_dotenv()` itself, explicitly, before reading `DATABASE_URL` — it no longer
  depends on `agent.core.nodes` → `agent.core.model`'s own `load_dotenv()` call having already run
  first by import-order accident. Reordering alone wasn't sufficient, though: `load_dotenv()` only
  skips keys already *present* in `os.environ` (even empty ones), and `tests/conftest.py` was
  *popping* `DATABASE_URL` rather than setting it — a popped key is indistinguishable from "never
  set" to `load_dotenv()`, so any module calling it later (regardless of import order) silently
  refills it from `.env`, which points at the real shared dev Postgres. Fixed `conftest.py` to set
  `DATABASE_URL = "sqlite:///rhizome.db"` (matching `db/database.py`'s own default) instead of
  popping it. This also broke `test_async_checkpointer_postgres_branch`'s sneaky reliance on the
  very footgun it existed to test — that test derived the real dev Postgres URL from
  `graph_module._database_url`, which only held the real value because of the bug. Fixed it to read
  `.env` directly via `dotenv_values(".env")` instead, and to monkeypatch `graph_module._database_url`
  alongside `_use_postgres` so `build_async_checkpointer()` actually connects to Postgres for that
  one test. Full suite re-run clean afterward (782 passed, 1 pre-existing unrelated live-API
  failure, 21 e2e deselected) with zero Postgres checkpoint-table pollution.
- **Final audit (2026-06-21) caught one more casualty of the `conftest.py` fix:**
  `tests/e2e/test_full_stack.py` calls `load_dotenv()` itself at module scope and reads
  `DATABASE_URL` right after, expecting to recover the real Postgres DSN — that worked before only
  because `conftest.py` *popped* the key, leaving it absent for `load_dotenv()` to fill back in.
  Once `conftest.py` started setting it to the SQLite default instead (a *present* value),
  `load_dotenv()`'s override-skip logic left it stuck on the SQLite URL, and the `db` fixture would
  have tried (and failed) to `psycopg2.connect()` to a `sqlite:///` DSN instead of skipping cleanly
  when Postgres isn't configured. Confirmed via direct repro (`os.environ["DATABASE_URL"] =
  "sqlite:///rhizome.db"; load_dotenv(); print(os.environ["DATABASE_URL"])` → stays SQLite). Fixed
  by reading `dotenv_values(".env")` directly instead of relying on `os.environ` post-`load_dotenv()`
  — same pattern already used in `test_async_checkpointer_postgres_branch`. Confirmed the fix
  recovers the real DSN even with the SQLite default present in `os.environ`, and that
  `pytest --collect-only -m e2e` still collects all 21 e2e tests cleanly. This is the second test
  this `.env`-precedence quirk has bitten — worth treating "reads `DATABASE_URL` to mean *real
  Postgres*" as a smell anywhere outside `db/database.py`/`agent/core/graph.py` themselves; reach
  for `dotenv_values(".env")` directly instead of `os.environ.get(...)` after `load_dotenv()`.

**Incidents/treatment plans structured JSON complete (#135, 2026-06-21):**
- New views (`agent/api/views.py`): `IncidentView`, `IncidentDetailView` (adds `subjects:
  IncidentSubjectView[]` and `treatment_plan: TreatmentPlanView | null`), `TreatmentPlanView`. New
  serializers (`agent/domain/incidents.py`): `incident_to_view_data()`,
  `treatment_plan_to_view_data()`, `incident_detail_to_view_data()`.
- All incident/treatment-plan endpoints in `agent/api/routers.py` now return these views instead of
  ad hoc dicts or `{"result": "<prose>"}`: `GET`/`POST /incidents`, `GET`/`PATCH /incidents/{id}`,
  `PATCH /incidents/{id}/resolve`, `GET /incidents/{id}/treatment`, `POST
  /incidents/{id}/treatment/manual`, `PATCH /treatment-plans/{id}`, `PATCH
  /treatment-plans/{id}/approve`, `GET /incidents/{id}/activity` (this last one wasn't part of
  #140's activity-endpoint sweep, since #140 covered tasks/plants/beds/containers/batches/projects
  only — `ActivityEventView` reused from there).
- Most of these endpoints now bypass their LangChain tool entirely and call the `agent/domain/
  incidents.py` functions (`create_incident_report`, `resolve_incident`, `approve_treatment_plan`)
  directly, classifying their `ValueError`s into 404/400 by message content — same pattern as
  `update_incident`/`update_treatment_plan` already used. The tools themselves
  (`agent/tools/operations/incidents.py`) are untouched; they're still what the LLM calls in chat.
- Found and fixed two live bugs in the process:
  - `GET /incidents/{id}/treatment` called the `get_treatment_plan` tool with
    `{"incident_id": incident_id}`, but that tool's parameter is `treatment_plan_id` — every call
    raised a pydantic `ValidationError` before the tool body ran, 100% of the time, with zero test
    coverage (same shape of bug as #136's `resolve_interaction` mismatch). Confirmed by reverting
    the fix and watching the new test suite fail with that exact error. Fixed by querying the
    incident's most recent treatment plan directly instead of going through the tool.
  - `POST /incidents/{id}/treatment/manual` stored `follow_up_strategy` as `[body.follow_up_strategy]`
    — a list containing a bare string — while AI-drafted plans (`_treatment_steps`) always store a
    list of `{"title": ...}` dicts. The `get_treatment_plan` tool's prose renderer does
    `follow_up['title']`, which would `TypeError` on a plain string the first time anyone called it
    on a manually-created plan. `TreatmentPlanView.follow_up_strategy: list[dict]` makes the
    mismatch a 422 instead of a silent landmine. Fixed by wrapping the string in `{"title": ...}` to
    match the canonical shape.
  - `PATCH /incidents/{id}/resolve` never exposed `notes` at all, even though the underlying tool
    and domain function both support it — added `ResolveIncidentRequest` (`agent/api/models.py`)
    so callers can actually use the capability that was always there underneath.
- `docs/architecture/api-reference.md` also had two unrelated inaccuracies in this section, fixed
  while in there: `POST /api/v1/incidents/{id}/treatment` was documented as an "AI trigger" route
  that doesn't exist — drafting happens via the `draft_treatment_plan` chat tool only, no REST
  endpoint for it; and `PATCH /api/v1/incidents/{id}/resolve` had no entry at all.
- 23 tests in `tests/agent/api/test_issue_135_incident_structured_views.py`, covering both new
  views' shapes, both live-bug regressions (confirmed they fail against the pre-fix code, not just
  pass against the fix), error paths (404/400/409), and cross-user isolation. Full suite: 805
  passed, 1 pre-existing skip (`ANTHROPIC_API_KEY` not set), 21 e2e deselected.

**Activity feed structured JSON complete (#134, 2026-06-21):**
- `GET /internal/data/activity` (the global feed) was the one activity endpoint #140 left
  unstructured — #140's sweep covered the per-entity activity endpoints
  (beds/containers/plants/batches/tasks/projects) only. Now returns `ActivityEventView[]` instead
  of `{"result": "<prose>"}`, by calling `list_recent_activity_entries()`
  (`agent/domain/activity_log.py`) and `activity_events_to_view_data()` directly instead of going
  through the `list_recent_activity` chat tool — same bypass-the-tool pattern as #135/#140. The
  tool itself is untouched.
- Also added proper 400 handling for malformed `since`/`before_timestamp` — previously these went
  through the tool's own try/except, which converted a bad date string into a 200 with
  `{"result": "Failed to list recent activity: Invalid since '...'..."}` baked into prose, the
  same masked-error pattern fixed elsewhere in this backlog.
- `GET /activity/stats` was already structured (a plain dict, not wrapped in `{"result": ...}`)
  and untouched — `#134`'s docs note only ever applied to the global feed endpoint, not stats.
- 11 tests in `tests/agent/api/test_issue_134_activity_feed_structured.py`: empty-feed shape,
  subjects round-tripping, all four filters (category/event_type/project_id/subject_type), limit,
  both invalid-date 400 paths (confirmed they fail against the pre-fix code), cross-user isolation,
  and one test driving through the real `report_incident` chat tool to prove the serializer
  round-trips activity actually written by tool-layer code, not just direct ORM/domain calls.

**#140/#141/#135 committed (2026-06-21):** all three had been sitting uncommitted, interleaved
across the same shared files (`routers.py`, `views.py`, `CLAUDE.md`, `api-reference.md`). Split
into three commits, one per issue, by reconstructing each intermediate snapshot (selective hunk
reversal/reapplication, not just `git add -p`) and running the full suite at each checkpoint —
`9ae26d5` (#140), `739394b` (#141), `7c7cbeb` (#135). Caught one real mistake mid-split (the first
#140 attempt truncated this file, dropping the Known issues/Invariants/Postgres notes sections
below — fixed via amend before moving on, confirmed via `git show HEAD:CLAUDE.md` afterward).
Post-split audit confirmed: `git diff <pre-session>..HEAD --stat` matches the original combined
diff exactly, no duplicate class/function/section definitions anywhere, all imports clean, the
real FastAPI lifespan boots and serves `/health`, all 12 incident endpoints and both streaming
endpoints present and correct, full suite still 805 passed/1 skipped, zero Postgres pollution.

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
