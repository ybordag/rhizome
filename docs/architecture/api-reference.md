# API Reference

The Rhizome internal API is consumed by Cambium (the Go gateway), which proxies it to Verdant (the React frontend) under `/api/v1`. All requests include a `user_id` extracted from Cambium's verified JWT — Rhizome never handles auth directly.

Rhizome exposes two internal surfaces:
- **`/internal/agent`** — LangGraph graph execution (AI operations: chat, triage, drafting)
- **`/internal/data/...`** — direct SQLAlchemy queries (CRUD, no LLM overhead)

Both surfaces are live. All ~115+ endpoints are wired across Rhizome and Cambium.

---

## Swagger UI — interactive API explorer

When `server.py` is running, Rhizome's internal API is fully documented at:

```
http://localhost:8001/docs
```

The public API (what Verdant uses) is documented via **Cambium's Swagger UI** at `http://localhost:8080/docs/index.html`.

---

## Authentication model

Cambium handles all authentication. It:
1. Verifies the JWT `Authorization: Bearer <token>` header
2. Extracts `user_id` from the `sub` claim
3. Injects `user_id` into every internal request to Rhizome as a query param

Rhizome trusts `user_id` from the query param — it never handles JWT directly.

---

## JSON response layer

All data endpoints return structured JSON (not `{"result": "...string..."}`). Response shapes are defined as Pydantic models in `agent/api/views.py`:

- `GardenProfileView`, `BedView`, `ContainerView`
- `PlantSummaryView`, `PlantDetailView`, `CareStateView`, `PlantBatchResultView`
- `TaskSummaryView`, `TaskDetailView`
- `ProjectSummaryView`, `ProjectDetailView`, `ProjectProgressView`
- `ProjectBriefView`, `ProposalSummaryView`, `ProposalDetailView`
- `ThreadView`, `SessionContextView`
- `TaskSeriesView`, `CalendarAnnotationView`
- `ProjectExpenseView`, `ExpenseSummaryView`, `ShoppingItemView`
- `ActivityEventView`, `ActivitySubjectView`

Tools continue to return strings for the LangGraph agent. The JSON layer is a parallel serialization path in the router only.

Mutation endpoints (`PATCH`/`POST` on a single entity) call the underlying tool for its
validation + side effects, then re-query the entity and return its structured view — the
tool's string return value is never surfaced to the client. Because those tools return strings
for both success *and* failure (the LLM reads them either way), the router classifies the
string via `_mutation_error_status()` (`agent/api/routers.py`) into 404 ("no ... found",
"not assigned"), 400 ("invalid", "cannot ...", "must be ...", "but only ...", or an "error"/
"failed" prefix), or success. Introduced in `#140`; see `CLAUDE.md` for the full list of
endpoints this covers.

---

## Garden — Profile

### `GET /api/v1/garden/profile`
**Response:** `GardenProfileView`

### `PATCH /api/v1/garden/profile`
Update profile fields (climate, soil, frost dates, tray capacity, location).
**Response:** `GardenProfileView`. 404 if the user has no garden profile yet.

---

## Garden — Beds

### `GET /api/v1/garden/beds`
**Query params:** `available=true` (excludes beds in active/maintaining projects)
**Response:** `BedView[]`

### `POST /api/v1/garden/beds`
Create a bed.
**Body:** `{ name, location?, size?, sunlight?, soil_type?, notes? }`
**Response:** `BedView`

### `GET /api/v1/garden/beds/{id}`
Bed detail. **Response:** `BedView`

### `PATCH /api/v1/garden/beds/{id}`
Update bed fields. **Response:** `BedView`. 400 on invalid `dimensions_sqft` (must be > 0).

### `DELETE /api/v1/garden/beds/{id}`
Hard delete.

### `GET /api/v1/garden/beds/{id}/care/state`
Current care timestamps. **Response:** `CareStateView`

### `GET /api/v1/garden/beds/{id}/care/history`
Care event history. **Query params:** `limit`

### `POST /api/v1/garden/beds/{id}/care`
Quick care recording — find-or-create + complete in one call.
**Body:** `{ care_type: watered|fertilized|amended|inspected|treated, notes?, recorded_at? }`  
`pruned` is not valid for beds (plant-only). `recorded_at` (ISO datetime) sets the exact care timestamp; defaults to now.  
If a pending/in_progress task linked to this bed matches the care type, it is completed. Otherwise the care timestamp is applied directly.  
**Response:** `{ task: TaskSummaryView | null, care_state: CareStateView }`

### `GET /api/v1/garden/beds/{id}/activity`
Full bed activity log. **Query params:** `limit`
**Response:** `ActivityEventView[]`. 404 if the bed doesn't exist (or isn't owned by the caller) — previously returned an empty array for any nonexistent id without checking.

---

## Garden — Containers

### `GET /api/v1/garden/containers`
**Query params:** `available=true` (excludes containers in active/maintaining projects)
**Response:** `ContainerView[]`

### `POST /api/v1/garden/containers`
Create a container. **Response:** `ContainerView`. 400 on invalid `container_type` or non-positive `size_gallons`. 404 if the user has no garden profile yet.

### `GET /api/v1/garden/containers/{id}`
Container detail. **Response:** `ContainerView`

### `PATCH /api/v1/garden/containers/{id}`
Update container fields. **Response:** `ContainerView`.

### `DELETE /api/v1/garden/containers/{id}`
Hard delete.

### `GET /api/v1/garden/containers/{id}/care/state`
**Response:** `CareStateView`

### `GET /api/v1/garden/containers/{id}/care/history`
**Query params:** `limit`

### `POST /api/v1/garden/containers/{id}/care`
Quick care recording. Same behaviour as beds.
**Body:** `{ care_type: watered|fertilized|amended|inspected|treated, notes?, recorded_at? }`  
`pruned` invalid for containers.  
**Response:** `{ task: TaskSummaryView | null, care_state: CareStateView }`

### `GET /api/v1/garden/containers/{id}/activity`
**Query params:** `limit`
**Response:** `ActivityEventView[]`. 404 if the container doesn't exist or isn't owned by the caller.

---

## Garden — Plants

### `GET /api/v1/garden/plants`
**Query params:** `status`, `project_id`, `batch_id`, `bed_id`, `container_id`, `location` (filters plants whose bed/container is at that location)
**Response:** `PlantSummaryView[]` (includes `location_name` convenience field)

### `POST /api/v1/garden/plants`
Add a plant. **Response:** `PlantDetailView`. 400 on invalid `status`, non-positive `quantity`, or assigning both `bed_id` and `container_id`. 404 if the user has no garden profile yet.

### `GET /api/v1/garden/plants/{id}`
Plant detail with all care timestamps and lifecycle dates.
**Response:** `PlantDetailView`

### `PATCH /api/v1/garden/plants/{id}`
Update plant fields. **Response:** `PlantDetailView`. 400 on invalid `status`.

### `PATCH /api/v1/garden/plants/{id}/remove`
Soft delete — marks plant as removed. Keeps the record.

### `DELETE /api/v1/garden/plants/{id}`
Hard delete — data entry mistakes only.

### `POST /api/v1/garden/plants/batch`
Batch-sow a group of plants. Creates a `PlantBatch` plus one `Plant` row per unit.
**Response:** `PlantBatchResultView` — `{ batch_id, batch_name, plant_name, variety, quantity_sown, project_id, created_at, plants: PlantSummaryView[] }`.
404 if the user has no garden profile yet, or (with `project_id`) the project doesn't exist.

### `PATCH /api/v1/garden/plants/batch`
Batch status update for all plants matching `name`/`variety`/`project_id`/`current_status`.
**Response:** `PlantSummaryView[]` — just the plants the update actually touched.
404 if nothing matches the filter. 400 if `quantity` exceeds the number of matches.

### `PATCH /api/v1/garden/plants/batch/remove`
Batch soft delete.
**Response:** `PlantSummaryView[]` — just the plants actually marked `removed`.
404 if nothing matches the filter. 400 if `quantity` exceeds the number of matches or an invalid filter value is provided.

> These two `batch` routes must stay registered in `agent/api/routers.py` *before*
> `PATCH /api/v1/garden/plants/{id}`. Starlette matches path routes in registration order, and
> `{id}` happily matches the literal segment `"batch"` — until `#140`, both batch routes were
> registered after it and were never actually reachable.

### `GET /api/v1/garden/plants/{id}/care/state`
**Response:** `CareStateView`

### `GET /api/v1/garden/plants/{id}/care/history`
**Query params:** `limit`

### `POST /api/v1/garden/plants/{id}/care`
Quick care recording. All six care types valid for plants.
**Body:** `{ care_type: watered|fertilized|inspected|treated|pruned, notes?, recorded_at? }`  
`amended` is not valid for plants (beds/containers only).  
**Response:** `{ task: TaskSummaryView | null, care_state: CareStateView }`

### `GET /api/v1/garden/plants/{id}/activity`
**Query params:** `limit`
**Response:** `ActivityEventView[]`. 404 if the plant doesn't exist or isn't owned by the caller.

---

## Garden — Batches

### `GET /api/v1/garden/batches`
List all plant batches.

### `DELETE /api/v1/garden/batches/{id}`
Delete a batch.

### `GET /api/v1/garden/batches/{id}/activity`
**Response:** `ActivityEventView[]`. 404 if the batch doesn't exist or isn't owned by the caller.

---

## Garden — Search

### `GET /api/v1/garden/search`
ILIKE search across plants, beds, containers by name.
**Query params:** `q` (required), `limit`

### `GET /api/v1/garden/locations/{location}`
All objects at a named location. `location` matches via `ILIKE '%...%'` against `Bed.location`/`Container.location`.
**Response:** `LocationResultsView` — `{ beds: BedView[], containers: ContainerView[], plants: PlantSummaryView[] }`. Fixed from a string-wrapped tool response in #138.

---

## Unified entity search

### `GET /api/v1/search`
Search across multiple entity types in one call (plants, beds, containers, tasks, projects, incidents) — distinct from `GET /api/v1/garden/search`, which is garden-objects-only.
**Query params:** `q` (required, non-empty), `types` (optional comma-separated filter), `limit` (per-type, default 5, max 20)
**Response:** `SearchResultsView` — `results: SearchResultItemView[]` + `by_type` counts.

---

## Tasks

### `GET /api/v1/tasks`
List tasks across projects.
**Query params:** `project_id` (optional), `status`, `type` (milestone|maintenance|emergency|opportunistic), `subject_type`, `subject_id` (filters by `linked_subjects` JSON)
**Response:** `TaskSummaryView[]`

### `POST /api/v1/tasks`
Direct user task creation (bypasses agent planning).
**Body:** `{ project_id, title, type, priority?, scheduled_date?, deadline?, estimated_minutes?, linked_subjects?, notes?, reversible? }`
Sets `is_user_modified=true`, `source_type="user"`.
**Response:** `TaskDetailView`

### `GET /api/v1/tasks/daily`
Top-N tasks by daily priority score (urgency, type, priority, triage alignment, blocking count).
**Query params:** `project_id`, `limit` (default 10)
**Response:** `TaskSummaryView[]` with `urgency`, `blocked`, `due_date`, `score` fields populated

### `GET /api/v1/tasks/due`
Due tasks with urgency tiers.
**Query params:** `project_id`, `days_ahead`
**Response:** `TaskSummaryView[]` with `urgency`, `blocked`, `due_date` fields populated

### `GET /api/v1/tasks/blocked`
All blocked tasks.
**Query params:** `project_id`
**Response:** `TaskSummaryView[]` with `urgency`, `blocked: true`, and `due_date` populated where available.

### `GET /api/v1/tasks/{id}`
Task detail. **Response:** `TaskDetailView`

### `PATCH /api/v1/tasks/{id}`
Update task fields (title, dates, notes, priority). **Response:** `TaskDetailView`. 400 on negative `estimated_minutes`. 404 if the task doesn't exist or isn't owned by the caller (checked via the task's project).

### `DELETE /api/v1/tasks/{id}`
Hard delete. Returns 400 if task is `in_progress`.

### `POST /api/v1/tasks/{id}/start`
Mark in progress. **Body:** `{ notes? }`

### `POST /api/v1/tasks/{id}/complete`
Complete. **Body:** `{ actual_minutes?, notes? }`

### `POST /api/v1/tasks/{id}/skip`
Skip. **Body:** `{ reason }`

### `POST /api/v1/tasks/{id}/defer`
Defer. **Body:** `{ deferred_until: ISO date, reason? }`

### `GET /api/v1/tasks/{id}/blockers`
Explain blocking dependencies.

### `GET /api/v1/tasks/{id}/activity`
Task history. **Query params:** `limit`
**Response:** `ActivityEventView[]`. 404 if the task doesn't exist or isn't owned by the caller.

### `POST /api/v1/tasks/{id}/dependencies`
Create a finish-to-start dependency edge. Returns 400 on cycle detection.
**Body:** `{ blocking_task_id }`
**Response:** `{ blocking_task_id, blocked_task_id }`

### `DELETE /api/v1/tasks/{id}/dependencies/{blocking_task_id}`
Remove a dependency edge.

### `POST /api/v1/tasks/series`
Create a recurring task series.
**Body:** `{ project_id, title_template, type, cadence, priority?, estimated_minutes?, window_days?, linked_subjects?, start_date?, end_date? }`
**Response:** `TaskSeriesView`

### `PATCH /api/v1/tasks/series/{id}`
Update series cadence, active flag. **Response:** `TaskSeriesView`. 400 on `cadence_days < 1`. 404 if the series doesn't exist or isn't owned by the caller (checked via the series' project).

### `DELETE /api/v1/tasks/series/{id}`
Delete series. `?delete_pending_tasks=true` also removes pending/deferred instances (never removes in_progress, done, or skipped).

### `POST /api/v1/tasks/materialize`
Materialize due recurring task instances (normally run by the monitor cron).

---

## Projects

### `GET /api/v1/projects`
**Response:** `ProjectSummaryView[]` (includes plant/bed/container/batch counts)

### `POST /api/v1/projects`
Create a project.
**Response:** `ProjectDetailView`

### `GET /api/v1/projects/{id}`
**Response:** `ProjectDetailView`

### `PATCH /api/v1/projects/{id}`
Update name, goal, status, budget, notes.
**Response:** `ProjectDetailView`

### `DELETE /api/v1/projects/{id}`
Blocked if non-superseded tasks exist — complete the project first.
**Response:** `ProjectDetailView` for the deleted project snapshot.

### `GET /api/v1/projects/{id}/progress`
Task completion progress, timeline health, budget status.
**Response:** `ProjectProgressView`

### `GET /api/v1/projects/{id}/tasks`
All non-superseded tasks.
**Query params:** `status`, `include_dependencies=true` (returns `{ tasks: TaskSummaryView[], edges: [{blocking_task_id, blocked_task_id}] }` for Gantt rendering)
**Response:** `TaskSummaryView[]` or `{ tasks, edges }` when `include_dependencies=true`

### `PATCH /api/v1/projects/{id}/tasks/bulk`
Atomic date update for Gantt drag operations. Max 50 tasks. Rejects done/superseded.
**Body:** `{ updates: [{ task_id, scheduled_date?, window_start?, window_end?, deadline? }] }`
**Response:** `TaskSummaryView[]`

### `POST /api/v1/projects/{id}/tasks/generate`
AI trigger — generate tasks from the accepted execution spec.

### `GET /api/v1/projects/{id}/series`
All active task series for a project.
**Response:** `TaskSeriesView[]`

### `GET /api/v1/projects/{id}/beds`
Beds assigned to this project. Each item includes `available: bool` (false only if the bed is also in another active/maintaining project).
**Response:** `BedView[]`

### `GET /api/v1/projects/{id}/containers`
Containers assigned to this project. Each item includes `available: bool`.
**Response:** `ContainerView[]`

### `POST /api/v1/projects/{id}/beds/{bedId}`
Assign a bed to the project.

### `DELETE /api/v1/projects/{id}/beds/{bedId}`
Unassign a bed.

### `POST /api/v1/projects/{id}/beds/batch`
Bulk assign beds.

### `POST /api/v1/projects/{id}/containers/{containerId}`
Assign a container.

### `DELETE /api/v1/projects/{id}/containers/{containerId}`
Unassign a container.

### `POST /api/v1/projects/{id}/containers/batch`
Bulk assign containers.

### `POST /api/v1/projects/{id}/plants/{plantId}`
Add a plant to the project.

### `DELETE /api/v1/projects/{id}/plants/{plantId}`
Remove a plant from the project.

### `GET /api/v1/projects/{id}/brief`
Active project brief. **Response:** `ProjectBriefView`

### `PATCH /api/v1/projects/{id}/brief`
Update brief.
**Response:** `ProjectBriefView`

### `GET /api/v1/projects/{id}/proposals`
**Response:** `ProposalSummaryView[]`

### `GET /api/v1/projects/{id}/proposals/{proposalId}`
**Response:** `ProposalDetailView`

### `POST /api/v1/projects/{id}/proposals/{proposalId}/accept`
Accept a proposal and promote to revision.
**Response:** `ProposalDetailView` with `status: "accepted"`.

### `GET /api/v1/projects/{id}/activity`
Cross-object timeline. **Query params:** `category`, `event_type`, `since`, `before_timestamp`, `limit`
**Response:** `ActivityEventView[]`. 404 if the project doesn't exist or isn't owned by the caller.

### `GET /api/v1/projects/{id}/expenses`
All expense records. **Response:** `ProjectExpenseView[]`

### `POST /api/v1/projects/{id}/expenses`
Add an expense item.
**Body:** `{ name, category, estimated_cost?, actual_cost?, quantity?, unit?, supplier?, purchased_at?, status?, notes? }`
**Response:** `ProjectExpenseView`

### `PATCH /api/v1/projects/{id}/expenses/{expenseId}`
Update an expense (mark purchased, update actual cost, etc.).

### `DELETE /api/v1/projects/{id}/expenses/{expenseId}`
Delete an expense record.

### `GET /api/v1/projects/{id}/expenses/summary`
Budget summary: proposal estimate vs. actual spend.
**Response:** `{ proposal_estimate, total_estimated, total_actual, remaining_estimate, by_category: { [category]: { estimated, actual } } }`

### `GET /api/v1/projects/{id}/shopping`
Shopping list scoped to this project. Convenience alias for `GET /api/v1/shopping?project_id=X`.

---

## Triage

### `POST /api/v1/triage/run`
AI trigger — run a fresh triage pass and persist the snapshot.

### `GET /api/v1/triage/latest`
Most recent triage snapshot, or `null` if none exists yet.
**Response:** `TriageSnapshotView` — `{ id, created_at, reasoning_summary, user_focus_summary, weather_snapshot_id, urgent_tasks: TaskSummaryView[], routine_tasks: TaskSummaryView[], project_tasks: TaskSummaryView[] }`. Resolves task IDs into full task objects rather than returning bare IDs (#133, fixed from a string-wrapped response).

### `POST /api/v1/triage/monitor`
Trigger the monitor cron triage job.

---

## Interactions

All four endpoints return `InteractionEnvelopeView` (or an array/null of it) — fixed from string-wrapped tool responses in #136. Shape: `{ id, interaction_type, status, title, summary, body, sections, actions: InteractionActionView[], context, created_at, resolved_at, resolution_action, resolution_summary }`.

### `GET /api/v1/interactions/pending`
The current pending interaction, or `null` if none.

### `GET /api/v1/interactions/recent`
List recent interactions as an array. **Query params:** `limit`, `interaction_type`, `project_id`

### `GET /api/v1/interactions/{id}`
Interaction detail. 404 if not found or owned by another user.

### `POST /api/v1/interactions/{id}/resolve`
Resolve a pending interaction. **Body:** `{ action: string, notes?: string }` — note this is `action`/`notes`, not `action_id`/`inputs` (those are the underlying tool's parameter names; the router translates between the two, `notes` → `inputs.note`). Returns the updated envelope with `status` transitioned to `resolved`/`dismissed`.

---

## Incidents

### `GET /api/v1/incidents`
**Query params:** `project_id`, `status`, `severity`, `incident_type`, `since` (ISO datetime), `before` (ISO datetime), `subject_type` + `subject_id` (filter by affected entity)  
**Response:** `IncidentView[]` — structured JSON array, scoped to the authenticated user's projects.

### `POST /api/v1/incidents`
Report a new incident. `project_id` is not a body field — it's inferred from `subjects` (each
subject's project, if any) and otherwise left null.
**Body:** `{ incident_type, summary, severity?, subjects?: [...], notes? }`
**Response:** `IncidentView`. Returns 400 for an invalid `incident_type`.

### `GET /api/v1/incidents/{id}`
Incident detail including subjects and the most recent treatment plan (any status).
**Response:** `IncidentDetailView` — `IncidentView` fields plus `subjects: IncidentSubjectView[]`,
`treatment_plan: TreatmentPlanView | null`.

### `PATCH /api/v1/incidents/{id}`
Partial update. **Body:** `{ summary?, severity?, notes?, incident_type? }`
**Response:** `IncidentView`

### `DELETE /api/v1/incidents/{id}`
Hard delete. Returns 400 if an approved treatment plan exists.

### `PATCH /api/v1/incidents/{id}/resolve`
Mark an incident resolved. **Body:** `{ notes?: string }` (optional, appended to the incident's
existing notes). **Response:** `IncidentView` with `status: "resolved"`.

### `GET /api/v1/incidents/{id}/activity`
Incident history. **Query params:** `limit`
**Response:** `ActivityEventView[]` — fixed from string-wrapped tool responses in #135 (this endpoint
was left out of #140's activity-endpoint sweep).

---

## Treatment Plans

### `GET /api/v1/incidents/{id}/treatment`
The most recent treatment plan for an incident (any status), 404 if none exists.
**Response:** `TreatmentPlanView`

Note: there is no `POST /api/v1/incidents/{id}/treatment` AI-trigger route. The agent drafts
treatment plans via the `draft_treatment_plan` chat tool
(`agent/tools/operations/incidents.py`), not a dedicated REST endpoint — only the user-authored
path below is exposed over HTTP.

### `POST /api/v1/incidents/{id}/treatment/manual`
Create a user-authored treatment plan (no LLM call).
**Body:** `{ approach_summary, recommended_steps: [{title, task_type, estimated_minutes, days_from_approval}][], follow_up_strategy? }`
`follow_up_strategy` is a plain string in the request but stored (and returned) as
`[{"title": follow_up_strategy}]` — matching the dict-list shape AI-drafted plans always use
(#135; previously stored as a bare string, which crashed the `get_treatment_plan` tool's prose
renderer).
Returns 409 if a draft plan already exists.
**Response:** `TreatmentPlanView`

### `PATCH /api/v1/treatment-plans/{id}`
Edit a draft treatment plan. Returns 400 if the plan is already approved.
**Body:** `{ approach_summary?, recommended_steps?, follow_up_strategy? }`
**Response:** `TreatmentPlanView`

### `DELETE /api/v1/treatment-plans/{id}`
Delete a draft plan. Returns 400 if approved.

### `PATCH /api/v1/treatment-plans/{id}/approve`
Approve a treatment plan and auto-generate tasks. Returns 404 if not found, 400 if not in `draft`
status or the incident lacks an active project revision.
**Response:** `TreatmentPlanView`

---

## Weather

### `GET /api/v1/weather/latest`
Most recent weather snapshot, or `null` if none exists yet.
**Response:** `WeatherSnapshotView` — `{ id, created_at, location_label, timezone, forecast_start_date, forecast_end_date, conditions_summary, alerts_summary, derived_impacts: WeatherDayImpactView[], recommended_actions: WeatherRecommendedActionView[] }`. Fixed from a string-wrapped response in #133.

### `POST /api/v1/weather/refresh`
Fetch a fresh Open-Meteo forecast. **Response:** `WeatherSnapshotView` (same shape as above).
Returns 400 (not 200-with-error-text) if the garden profile has no location set yet.

### `GET /api/v1/weather/tasks/impacted`
Tasks materially affected by current weather. **Query params:** `project_id`
**Response:** `WeatherImpactedTaskView[]` — `{ task_id, task_title, project_id, impact_type, impact_kind, impact_date, summary }`. Fixed from a string-wrapped response in #133.

### `POST /api/v1/weather/tasks/draft`
AI trigger — draft weather-driven task adjustments.

### `PATCH /api/v1/weather/changesets/{id}/approve`
Apply a previously drafted weather-aware task change set.
**Response:** `WeatherTaskChangeSetView` — `{ id, status, summary, weather_snapshot_id, created_at, approved_at, affected_tasks: TaskSummaryView[] }`. Fixed from a string-wrapped response in #133. 404 if not found/not owned by the caller; 400 if already approved (previously both cases silently returned 200 with an error message embedded in the response text).

### `POST /api/v1/weather/monitor`
Trigger the monitor cron weather job.

---

## Activity

`ActivityEventView`: `{ id, created_at, actor_type, actor_label, event_type, category, summary, notes, project_id, subjects: ActivitySubjectView[] }`.
`ActivitySubjectView`: `{ subject_type, subject_id, role }`.

### `GET /api/v1/activity`
Global activity feed. **Response:** `ActivityEventView[]` — fixed from `{"result": "<prose>"}` in
`#134`. Every per-entity activity endpoint above (beds/containers/plants/batches/tasks/projects)
already returned this shape as of `#140`.
**Query params:** `project_id`, `subject_type`, `event_type`, `category`, `since` (ISO, inclusive),
`before_timestamp` (ISO cursor, exclusive), `limit` (default 20). Invalid `since`/`before_timestamp`
returns 400. Results are newest-first. To paginate: pass the `created_at` of the last (oldest) event
in a page as the next page's `before_timestamp` — exclusivity at that exact boundary is what
prevents the same event appearing on both pages.

### `GET /api/v1/activity/stats`
Aggregated activity counts for velocity tracking and progress charts.
**Query params:** `since` (required), `before`, `event_types` (comma-separated), `project_id`, `group_by=day|week`
**Response:** `{ totals: { [event_type]: count }, by_day: [{ date, ...counts }] }`

---

## Calendar Annotations

Day-level notes attached to specific dates (observations, plans, reminders that aren't tasks).

### `GET /api/v1/calendar/annotations`
**Query params:** `since` (required, ISO date), `before` (required, ISO date) — inclusive range
**Response:** `CalendarAnnotationView[]`

### `POST /api/v1/calendar/annotations`
**Body:** `{ date (ISO), content, category? (note|observation|plan|reminder), color? }`
**Response:** `CalendarAnnotationView`

### `PATCH /api/v1/calendar/annotations/{id}`
**Body:** `{ content?, category?, color? }`

### `DELETE /api/v1/calendar/annotations/{id}`

---

## Shopping List

Standalone or project-scoped shopping items. Separate from tasks — purchasing materials is tracked here, not in the task system.

### `GET /api/v1/shopping`
**Query params:** `status` (needed|ordered|purchased), `project_id`, `category`, `priority`
**Response:** `ShoppingItemView[]`

### `POST /api/v1/shopping`
**Body:** `{ name, category, project_id?, quantity?, unit?, estimated_cost?, supplier?, notes?, priority? }`
**Response:** `ShoppingItemView`

### `PATCH /api/v1/shopping/{id}`
Update any fields.

### `DELETE /api/v1/shopping/{id}`

### `POST /api/v1/shopping/{id}/purchase`
Mark item purchased. Automatically creates a linked `ProjectExpense` if `project_id` and `estimated_cost` are set.
**Response:** `ShoppingItemView` (with `expense_id` set if expense was created)

---

## Threads (conversation management)

Thread IDs are botanical three-word names generated by Cambium (`silver-fern-cascade`). Rhizome stores metadata; message content lives in the LangGraph checkpointer.

### `POST /api/v1/threads`
Register a thread. Idempotent.
**Body:** `{ thread_id, title?, project_id? }`
**Response:** `{ thread_id, created: bool }`

### `GET /api/v1/threads`
List user's conversations sorted by most recently active.
**Query params:** `limit` (default 20)
**Response:** `ThreadView[]`

### `GET /api/v1/threads/{id}`
Thread metadata.
**Response:** `ThreadView`

`ThreadView` preserves the existing wire shape:
`{ thread_id, title, project_id, last_message_preview, last_active_at, message_count, pinned_context, session_context, created_at }`

### `GET /api/v1/threads/{id}/session-context`
Structured startup/session context for a thread. Used by Verdant's SessionStrip.
**Response:** `SessionContextView`:
`{ available_minutes, energy_level, focus_project_id, focus_label, preferred_location_type, open_to_outdoor_work, wants_quick_wins, source, updated_at }`

Unset threads return all nullable values as `null`, `source: "unset"`, and `updated_at: null`.

### `PATCH /api/v1/threads/{id}/session-context`
User override for structured startup/session context.
**Body:** one or more fields from `{ available_minutes, energy_level, focus_project_id, preferred_location_type, open_to_outdoor_work, wants_quick_wins }`; empty bodies return `400`, and unknown fields return validation errors.
Explicit `null` clears a field. `energy_level` is `low | medium | high`; `preferred_location_type` is `bed | container`.
**Response:** `SessionContextView` with `source: "user"`.

### `GET /api/v1/threads/{id}/messages`
Full message history from the LangGraph checkpoint.
**Response:** `{ thread_id, messages: [{ role, content, type }] }`

### `DELETE /api/v1/threads/{id}`
Delete thread metadata.

---

## Alerts and Monitor

### `GET /api/v1/alerts`
Pending non-expired alerts.

### `POST /api/v1/alerts/{id}/dismiss`
Dismiss an alert.

### `GET /api/v1/monitor/runs`
Monitor job history.

### `GET /api/v1/monitor/runs/{id}`
Monitor run detail.

### `POST /api/v1/tasks/series/run`
Trigger the series materialization cron job.

---

## Notifications

Two complementary surfaces backing the frontend's notification drawer — see `agent/domain/notifications.py` for the underlying per-user event bus.

### `GET /api/v1/notifications/stream`
Long-lived SSE connection. Frontend opens once on app mount and keeps it open for the session. Emits `{"type": "heartbeat"}` every 30s when idle, and live events as they happen: `job_started`, `job_step`, `job_complete`, `job_failed`, `alert` (a freshly-written `MonitorAlert`). Delivery is **best-effort and process-local** — if the user has no active connection in the process handling a given background job (e.g. disconnected, or the job runs in a different process via `scripts/monitor.py`), the live push is silently dropped. `MonitorAlert`/`InteractionRecord` rows are the durable fallback; `active_jobs` (in-memory only) is not.

### `GET /api/v1/notifications`
Sync snapshot — called on app mount and on stream reconnection to catch up on anything missed while disconnected.
**Query params:** `since` (ISO datetime, optional — limits alerts/interactions to those created after this timestamp)
**Response:** `{"alerts": [...], "pending_interactions": [...], "active_jobs": [...]}`. `alerts` = pending, non-expired `MonitorAlert` rows. `active_jobs` is a point-in-time snapshot only (not `since`-filtered) — a job that fully starts and completes during a disconnect window leaves no trace here; check `alerts` for anything that job wrote on completion (see `series_job`/`draft_treatment_plan` in `scripts/monitor.py` / `agent/tools/operations/incidents.py`).

---

## Media (not yet implemented)

### `POST /api/v1/media`
Upload a media asset. Requires Epic 2 backend work.

### `GET /api/v1/media/{id}`
Retrieve a media asset.

---

## Pagination

List endpoints that support pagination use cursor-based pagination via `before_timestamp` (ISO 8601 datetime). Pass the `created_at` of the last item on the previous page to fetch the next page. No offset-based pagination.

---

## Error responses

Data endpoints return HTTP status codes directly:
- `200` — success
- `400` — invalid input or business rule violation (e.g. deleting an in_progress task)
- `404` — entity not found or belongs to a different user
- `409` — conflict (e.g. duplicate dependency)

Agent surface errors are embedded in the response body string and handled by Cambium's `_result_or_404` pattern.
