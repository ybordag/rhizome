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
- `PlantSummaryView`, `PlantDetailView`, `CareStateView`
- `TaskSummaryView`, `TaskDetailView`
- `ProjectSummaryView`, `ProjectDetailView`
- `TaskSeriesView`, `CalendarAnnotationView`
- `ProjectExpenseView`, `ExpenseSummaryView`, `ShoppingItemView`

Tools continue to return strings for the LangGraph agent. The JSON layer is a parallel serialization path in the router only.

---

## Garden — Profile

### `GET /api/v1/garden/profile`
**Response:** `GardenProfileView`

### `PATCH /api/v1/garden/profile`
Update profile fields (climate, soil, frost dates, tray capacity, location).

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
Update bed fields.

### `DELETE /api/v1/garden/beds/{id}`
Hard delete.

### `GET /api/v1/garden/beds/{id}/care/state`
Current care timestamps. **Response:** `CareStateView`

### `GET /api/v1/garden/beds/{id}/care/history`
Care event history. **Query params:** `limit`

### `GET /api/v1/garden/beds/{id}/activity`
Full bed activity log. **Query params:** `limit`

---

## Garden — Containers

### `GET /api/v1/garden/containers`
**Query params:** `available=true` (excludes containers in active/maintaining projects)
**Response:** `ContainerView[]`

### `POST /api/v1/garden/containers`
Create a container.

### `GET /api/v1/garden/containers/{id}`
Container detail. **Response:** `ContainerView`

### `PATCH /api/v1/garden/containers/{id}`
Update container fields.

### `DELETE /api/v1/garden/containers/{id}`
Hard delete.

### `GET /api/v1/garden/containers/{id}/care/state`
**Response:** `CareStateView`

### `GET /api/v1/garden/containers/{id}/care/history`
**Query params:** `limit`

### `GET /api/v1/garden/containers/{id}/activity`
**Query params:** `limit`

---

## Garden — Plants

### `GET /api/v1/garden/plants`
**Query params:** `status`, `project_id`, `batch_id`, `bed_id`, `container_id`, `location` (filters plants whose bed/container is at that location)
**Response:** `PlantSummaryView[]` (includes `location_name` convenience field)

### `POST /api/v1/garden/plants`
Add a plant.

### `GET /api/v1/garden/plants/{id}`
Plant detail with all care timestamps and lifecycle dates.
**Response:** `PlantDetailView`

### `PATCH /api/v1/garden/plants/{id}`
Update plant fields.

### `PATCH /api/v1/garden/plants/{id}/remove`
Soft delete — marks plant as removed. Keeps the record.

### `DELETE /api/v1/garden/plants/{id}`
Hard delete — data entry mistakes only.

### `POST /api/v1/garden/plants/batch`
Batch-sow a group of plants.

### `PATCH /api/v1/garden/plants/batch`
Batch status update.

### `PATCH /api/v1/garden/plants/batch/remove`
Batch soft delete.

### `GET /api/v1/garden/plants/{id}/care/state`
**Response:** `CareStateView`

### `GET /api/v1/garden/plants/{id}/care/history`
**Query params:** `limit`

### `GET /api/v1/garden/plants/{id}/activity`
**Query params:** `limit`

---

## Garden — Batches

### `GET /api/v1/garden/batches`
List all plant batches.

### `DELETE /api/v1/garden/batches/{id}`
Delete a batch.

### `GET /api/v1/garden/batches/{id}/activity`

---

## Garden — Search

### `GET /api/v1/garden/search`
ILIKE search across plants, beds, containers by name.
**Query params:** `q` (required), `limit`

### `GET /api/v1/garden/locations/{location}`
All objects at a named location.

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

### `GET /api/v1/tasks/{id}`
Task detail. **Response:** `TaskDetailView`

### `PATCH /api/v1/tasks/{id}`
Update task fields (title, dates, notes, priority).

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
Update series cadence, active flag.

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

### `GET /api/v1/projects/{id}`
**Response:** `ProjectDetailView`

### `PATCH /api/v1/projects/{id}`
Update name, goal, status, budget, notes.

### `DELETE /api/v1/projects/{id}`
Blocked if non-superseded tasks exist — complete the project first.

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

### `GET /api/v1/projects/{id}/proposals`
**Response:** `ProposalSummaryView[]`

### `GET /api/v1/projects/{id}/proposals/{proposalId}`
**Response:** `ProposalDetailView`

### `POST /api/v1/projects/{id}/proposals/{proposalId}/accept`
Accept a proposal and promote to revision.

### `GET /api/v1/projects/{id}/activity`
Cross-object timeline. **Query params:** `category`, `event_type`, `since`, `before_timestamp`, `limit`

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
Most recent triage snapshot.

### `GET /api/v1/triage/recommendations`
Recommended task IDs from the latest triage snapshot.

### `POST /api/v1/triage/monitor`
Trigger the monitor cron triage job.

---

## Interactions

### `GET /api/v1/interactions/pending`
Get the current pending interaction.

### `GET /api/v1/interactions/recent`
List recent interactions. **Query params:** `limit`, `interaction_type`, `project_id`

### `GET /api/v1/interactions/{id}`
Interaction detail.

### `POST /api/v1/interactions/{id}/resolve`
Resolve a pending interaction. **Body:** `{ action_id, inputs? }`

---

## Incidents

### `GET /api/v1/incidents`
**Query params:** `project_id`, `status`, `limit`
**Response:** `IncidentView[]`

### `POST /api/v1/incidents`
Report a new incident.
**Body:** `{ incident_type, summary, project_id?, severity?, subjects?: [...], detected_at? }`

### `GET /api/v1/incidents/{id}`
Incident detail including subjects and treatment plan status.
**Response:** `IncidentDetailView`

### `GET /api/v1/incidents/{id}/activity`
Incident history. **Query params:** `limit`

---

## Treatment Plans

### `GET /api/v1/incidents/{id}/treatment`
Treatment plan for an incident.
**Response:** `TreatmentPlanView`

### `POST /api/v1/incidents/{id}/treatment`
AI trigger — draft a treatment plan.

### `PATCH /api/v1/treatment-plans/{id}/approve`
Approve a treatment plan and auto-generate tasks.

---

## Weather

### `GET /api/v1/weather/latest`
Most recent weather snapshot. **Response:** `WeatherSnapshotView`

### `POST /api/v1/weather/refresh`
Fetch a fresh Open-Meteo forecast.

### `GET /api/v1/weather/tasks/impacted`
Tasks materially affected by current weather. **Query params:** `project_id`

### `POST /api/v1/weather/tasks/draft`
AI trigger — draft weather-driven task adjustments.

### `PATCH /api/v1/weather/changesets/{id}/approve`
Approve a weather task changeset.

### `POST /api/v1/weather/monitor`
Trigger the monitor cron weather job.

---

## Activity

### `GET /api/v1/activity`
Global activity feed.
**Query params:** `project_id`, `subject_type`, `event_type`, `category`, `since` (ISO), `before_timestamp` (ISO cursor), `limit`

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

### `GET /api/v1/threads/{id}`
Thread metadata.

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
