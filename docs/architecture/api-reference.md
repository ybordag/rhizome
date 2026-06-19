# API Reference

The Rhizome internal API is consumed by Cambium (the Go gateway), which proxies it to Verdant (the React frontend) under `/api/v1`. All requests include a `user_id` extracted from Cambium's verified JWT — Rhizome never handles auth directly.

Rhizome exposes two internal surfaces:
- **`/internal/agent`** — LangGraph graph execution (AI operations: chat, triage, drafting)
- **`/internal/data/...`** — direct SQLAlchemy queries (CRUD, no LLM overhead)

Both surfaces are live. Cambium Phases 1–4 are complete; all ~95 endpoints are wired.

---

## Authentication model

Cambium handles all authentication. It:
1. Verifies the JWT `Authorization: Bearer <token>` header
2. Extracts `user_id` from the `sub` claim
3. Injects `user_id` into every internal request to Rhizome

Rhizome trusts `user_id` from the request body (internal only) — it never appears in the public API surface. The public API is `Authorization: Bearer <token>` only.

---

## Triage

### `POST /api/v1/triage/run`
Run a fresh triage pass and persist the snapshot.

**Backing tool:** `run_daily_triage`  
**Response:** `TriageSnapshotView`

### `GET /api/v1/triage/latest`
Retrieve the most recent triage snapshot.

**Backing tool:** `get_latest_triage_snapshot`  
**Response:** `TriageSnapshotView`

---

## Interactions

### `GET /api/v1/interactions/pending`
Get the current pending interaction (if any).

**Backing tool:** `get_pending_interaction`  
**Response:** `InteractionEnvelopeView | null`

### `GET /api/v1/interactions`
List recent interactions.

**Query params:** `limit`, `interaction_type`, `project_id`  
**Backing tool:** `list_recent_interactions`  
**Response:** `InteractionEnvelopeView[]`

### `GET /api/v1/interactions/{id}`
Get a specific interaction record.

**Backing tool:** `get_interaction_record`  
**Response:** `InteractionEnvelopeView`

### `POST /api/v1/interactions/{id}/resolve`
Resolve a pending interaction.

**Body:** `{ action_id: string, inputs?: object }`  
**Backing tool:** `resolve_interaction`  
**Response:** `{ status: string, resolution_summary: string }`

---

## Tasks

### `GET /api/v1/tasks`
List tasks for a project.

**Query params:** `project_id` (required), `status`, `include_superseded`  
**Backing tool:** `list_project_tasks`  
**Response:** `TaskSummaryView[]`

### `GET /api/v1/tasks/due`
List due tasks with urgency tiers.

**Query params:** `project_id`, `days_ahead`  
**Backing tool:** `list_due_tasks`  
**Response:** `{ task: TaskSummaryView, urgency: string, blocked: bool, due_date: string }[]`

### `GET /api/v1/tasks/daily`
Top-N tasks by daily priority score.

**Query params:** `project_id`, `limit` (default 10)  
**Backing tool:** `get_daily_priority_tasks`  
**Response:** `{ task: TaskSummaryView, score: number, urgency: string, blocked: bool, triage_recommended: bool, unblocks_count: number }[]`

### `GET /api/v1/tasks/{id}`
Task detail.

**Backing tool:** `get_task`  
**Response:** `TaskDetailView`

### `POST /api/v1/tasks/{id}/start`
Mark task in progress.

**Body:** `{ notes?: string }`  
**Backing tool:** `start_task`

### `POST /api/v1/tasks/{id}/complete`
Complete a task.

**Body:** `{ actual_minutes?: number, notes?: string }`  
**Backing tool:** `complete_task`

### `POST /api/v1/tasks/{id}/skip`
Skip a task with a reason.

**Body:** `{ reason: string }`  
**Backing tool:** `skip_task`

### `POST /api/v1/tasks/{id}/defer`
Defer a task.

**Body:** `{ deferred_until: string (ISO date), reason?: string }`  
**Backing tool:** `defer_task`

### `PUT /api/v1/tasks/{id}`
Update task fields (title, dates, notes, priority).

**Body:** partial `TaskUpdateRequest`  
**Backing tool:** `update_task`

### `GET /api/v1/tasks/{id}/blockers`
Explain what's blocking a task.

**Backing tool:** `explain_task_blockers`

### `GET /api/v1/tasks/{id}/activity`
Task history.

**Query params:** `limit`  
**Backing tool:** `get_task_activity`

---

## Projects

### `GET /api/v1/projects`
List all projects.

**Query params:** `status`  
**Backing tool:** `list_projects`  
**Response:** `ProjectSummaryView[]`

### `GET /api/v1/projects/{id}`
Project detail with assigned beds, containers, plants, batches.

**Backing tool:** `get_project`  
**Response:** `ProjectDetailView`

### `GET /api/v1/projects/{id}/progress`
Task completion progress, timeline health, budget status.

**Backing tool:** `get_project_progress`  
**Response:** `ProjectProgressView`

### `GET /api/v1/projects/{id}/brief`
Active project brief.

**Backing tool:** `get_project_brief`  
**Response:** `ProjectBriefView`

### `GET /api/v1/projects/{id}/schedule/preview`
Non-destructive preview of the task graph for a proposal or revision.

**Query params:** `proposal_id | revision_id`  
**Backing tool:** `preview_project_schedule`

### `GET /api/v1/projects/{id}/tasks`
All tasks for a project.

**Query params:** `status`, `include_superseded`  
**Backing tool:** `list_project_tasks`

### `GET /api/v1/projects/{id}/activity`
Cross-object project timeline.

**Query params:** `category`, `event_type`, `since` (ISO), `before_timestamp` (ISO), `limit`  
**Backing tool:** `list_project_activity`

---

## Proposals

### `GET /api/v1/projects/{id}/proposals`
List all proposals for a project.

**Backing tool:** `list_project_proposals`  
**Response:** `ProposalSummaryView[]`

### `GET /api/v1/projects/{id}/proposals/{proposalId}`
Proposal detail.

**Backing tool:** `get_project_proposal`  
**Response:** `ProposalDetailView`

---

## Incidents

### `POST /api/v1/incidents`
Report a new incident.

**Body:** `{ incident_type, summary, project_id?, severity?, subjects?: [...], detected_at? }`  
**Backing tool:** `report_incident`

### `GET /api/v1/incidents`
List incidents.

**Query params:** `project_id`, `status`, `limit`  
**Backing tool:** `list_incidents`  
**Response:** `IncidentView[]`

### `GET /api/v1/incidents/{id}`
Incident detail including subjects and treatment plan status.

**Backing tool:** `get_incident`  
**Response:** `IncidentDetailView`

### `GET /api/v1/incidents/{id}/activity`
Incident history.

**Backing tool:** `get_incident_activity`

---

## Treatment Plans

### `GET /api/v1/treatment-plans/{id}`
Treatment plan detail with recommended steps and follow-up strategy.

**Backing tool:** `get_treatment_plan`  
**Response:** `TreatmentPlanView`

---

## Weather

### `GET /api/v1/weather/latest`
Most recent weather snapshot.

**Backing tool:** `get_latest_weather_snapshot`  
**Response:** `WeatherSnapshotView`

### `GET /api/v1/weather/impacts`
Tasks materially affected by current weather.

**Query params:** `project_id`  
**Backing tool:** `list_weather_impacted_tasks`

### `POST /api/v1/weather/refresh`
Fetch a fresh forecast from Open-Meteo.

**Backing tool:** `refresh_weather_snapshot`

---

## Activity

### `GET /api/v1/activity`
General activity log.

**Query params:** `project_id`, `subject_type`, `event_type`, `category`, `since`, `before_timestamp`, `limit`  
**Backing tool:** `list_recent_activity`

### `GET /api/v1/plants/{id}/activity`
Plant history. **Backing tool:** `get_plant_activity`

### `GET /api/v1/beds/{id}/activity`
Bed history. **Backing tool:** `get_bed_activity`

### `GET /api/v1/containers/{id}/activity`
Container history. **Backing tool:** `get_container_activity`

---

## Threads (conversation management)

Thread IDs are botanical three-word names generated by Cambium (`silver-fern-cascade`). Rhizome stores metadata; message content lives in the LangGraph checkpointer.

### `POST /api/v1/threads`
Register a new thread ID before the first chat message. Idempotent — safe to call if thread already exists.

**Body:** `{ "thread_id": "silver-fern-cascade", "title"?: "...", "project_id"?: "..." }`  
**Response:** `{ "thread_id": "...", "created": true|false }`

### `GET /api/v1/threads`
List the user's conversations, sorted by most recently active.

**Query params:** `limit` (default 20)  
**Response:** array of `{ thread_id, title, last_message_preview, last_active_at, message_count, created_at }`

### `GET /api/v1/threads/{id}`
Get metadata for a single thread. Returns 404 if thread belongs to a different user.

### `GET /api/v1/threads/{id}/messages`
Full message history from the LangGraph checkpoint. No duplication — reads directly from the PostgresSaver state.

**Response:** `{ "thread_id": "...", "messages": [{ "role": "user"|"assistant", "content": "...", "type": "..." }] }`

### `DELETE /api/v1/threads/{id}`
Delete thread metadata. The LangGraph checkpoint is retained (checkpoint cleanup is a future improvement).

---

## Media (not yet implemented)

### `POST /api/v1/media`
Upload a media asset (image, video). Requires Epic 2 backend work.

### `GET /api/v1/media/{id}`
Retrieve a media asset.

---

## Pagination

All list endpoints that support pagination use cursor-based pagination via `before_timestamp` (ISO 8601 datetime string). Pass the `created_at` of the last item on the previous page to get the next page. There is no offset-based pagination.

---

## Error responses

All errors return a human-readable string. HTTP status codes are managed by Cambium, not Rhizome tools. Rhizome tools always return a string — errors are embedded in the string (e.g. "No project found with id abc-123.").
