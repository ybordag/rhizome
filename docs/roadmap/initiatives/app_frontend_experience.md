# Epic 9 Plan: App-Facing Interaction and Frontend Experience

**Epic status:** In progress — backend contract and Cambium proxy are active;
Verdant frontend work is underway
**Last updated:** 2026-06

---

## Purpose

Turn the existing backend interaction contract into a real product experience in
an app.

This epic is not about rebuilding backend logic. It is about:

- deciding what stays in the Rhizome repo
- deciding what belongs in the separate frontend repo
- defining the backend/frontend contract between them
- exposing the planner, tracker, triage, incidents, treatment plans, and
  approvals through a clean app-facing surface

The frontend will live in a separate repository. Rhizome should remain the
agent/backend repository and become a clean backend product surface for that
app.

---

## Why this epic matters now

Rhizome now has:

- structured interaction envelopes
- persisted interaction records
- app-facing interaction query/resolve APIs
- a structured FastAPI internal API for Cambium
- CLI simulation of the core user flows

That means the backend contract exists beyond rough form. Remaining work is
mostly product/frontend delivery plus media and later visual surfaces:

- media/image upload support
- a real frontend app that can replace the CLI as the main manual testing
  surface

This epic is also a major enabler for:

- **Epic 2: Visual Garden Understanding**, because image upload and review are
  far more natural in an app than in the CLI
- **Epic 3: Project Planning and Negotiation**, because proposal comparison and
  review need a better UI surface
- **Epic 6: Reactive Monitoring and Alerting**, because weather alerts and
  approval-gated task changes need a durable presentation layer

---

## What should exist by the end of this epic

- a usable frontend app shell in a separate repository
- a formal HTTP/JSON backend API in Rhizome
- Cambium-owned authentication and session handling
- stable app-facing structured payloads for:
  - pending interactions
  - recent interactions
  - tasks
  - triage snapshots
  - incidents
  - treatment plans
  - weather snapshots and weather task impacts
  - proposals
- support for media/image attachments in the backend/frontend flow
- removal of remaining terminal-first assumptions from backend responses
- a manual product-testing loop that primarily happens through the app instead
  of the CLI

The first complete user-facing phase should cover:

- login/session
- startup triage
- pending interactions
- task list/detail/actions
- incidents and treatment-plan review
- weather snapshot and weather-change review

Proposal UI is part of the epic, but it can follow shortly after the core
operations phase.

---

## Repo split

### What stays in the Rhizome repo

Rhizome remains the **backend and domain engine**. It owns:

- planner, tracker, triage, weather, incident/treatment, interaction, and
  activity-log logic
- the database schema and persistence layer
- the LangGraph runtime and CLI simulation
- the internal HTTP API/service layer consumed by Cambium
- trusted `user_id` handling after Cambium authentication
- Rhizome-owned media metadata and domain processing once media upload plumbing
  exists
- transformation of internal domain objects into structured API payloads

Rhizome has added:

- a FastAPI + Pydantic internal API layer
- typed serializers / DTOs for app use through Cambium
- API tests and contract tests

Cambium owns:

- public `/api/v1` endpoints
- JWT authentication, refresh tokens, and user/session validation
- authenticated proxying into Rhizome internal routes

Rhizome should not add:

- React UI code
- platform-specific frontend code
- duplicated presentation logic that belongs in the app repo

### What belongs in the separate frontend repo

The frontend repo owns:

- the app shell
- login UX
- dashboard/triage screens
- task list/detail/action screens
- interaction review screens
- treatment-plan and weather-review screens
- proposal review screens
- media/image upload UX

The frontend should:

- consume only the formal HTTP API
- render structured sections/actions instead of rebuilding backend logic
- keep local UI state and app-specific presentation behavior
- remain portable toward web, desktop, and mobile later

The frontend should not:

- import Rhizome Python modules
- call the DB directly
- replicate planner/tracker/triage logic
- depend on CLI-formatted text as the primary backend surface

---

## Backend / frontend contract

### Contract decisions locked for this epic

- Cambium exposes the public **versioned HTTP/JSON API**
- Rhizome exposes structured internal HTTP routes that Cambium proxies
- the frontend consumes Cambium over HTTP
- auth is token-based and owned by Cambium
- media/image upload will be part of the first contract
- polling covers most data refreshes; SSE is available for chat, monitor, and
  live activity surfaces where needed
- the first frontend delivery target is **web-first React**, with future
  portability toward desktop/mobile

### API shape

Cambium exposes the formal API under `/api/v1` and proxies structured requests
to Rhizome's internal routes.

Auth/session endpoints:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/session`

### Structured payloads

Stable JSON DTOs now exist for the core backend/app surface. Media DTOs remain
part of the visual/media follow-up work.

- `InteractionEnvelopeView`
  - `id`, `type`, `status`, `title`, `summary`, `body`
  - `sections[]`
  - `actions[]`
  - `context`
  - `createdAt`, `expiresAt`
- `InteractionActionView`
  - `id`, `label`, `kind`, `styleHint`, `inputSchema`
- `TriageSnapshotView`
  - `id`, `createdAt`, `timezone`
  - `summary`
  - grouped task objects for urgent, routine, and project work
  - `weatherSummary`
  - `sessionContext`
- `TaskSummaryView`
  - `id`, `projectId`, `title`, `status`, `type`
  - `urgency`, `blocked`
  - `scheduledDate`, `windowStart`, `windowEnd`, `deadline`
  - `estimatedMinutes`
- `TaskDetailView`
  - summary fields plus:
  - `description`, `notes`
  - `dependencies`, `blockers`
  - `linkedSubjects`
  - `seriesId`, `generationRunId`
- `IncidentView`
  - `id`, `type`, `status`, `severity`, `summary`, `notes`, `subjects`
- `TreatmentPlanView`
  - `id`, `incidentId`, `status`
  - `approachSummary`
  - `recommendedSteps[]`
  - `followUpStrategy[]`
- `WeatherSnapshotView`
  - `id`, `createdAt`, `locationLabel`
  - `forecastStartDate`, `forecastEndDate`
  - `conditionsSummary`, `alertsSummary`
  - `derivedImpacts[]`
  - `recommendedActions[]`
- `WeatherTaskImpactView`
  - `taskId`, `taskTitle`, `impactKind`, `impactType`, `impactDate`, `summary`
- `ProposalSummaryView` / `ProposalDetailView`
  - `id`, `status`, `title`, `summary`
  - estimates, assumptions, tradeoffs, risks
- `MediaAssetView`
  - `id`, `mimeType`, `sizeBytes`, `createdAt`
  - `originalFilename`, `attachmentKind`
  - `url`
  - optional linked subject references

### Endpoint surface

Cambium exposes public `/api/v1` routes. Rhizome implements the corresponding
internal agent/data routes. The core app surface exists; media routes remain a
follow-up dependency for visual workflows.

#### Triage

- `POST /api/v1/triage/run`
- `GET /api/v1/triage/latest`

#### Interactions

- `GET /api/v1/interactions/pending`
- `GET /api/v1/interactions`
- `GET /api/v1/interactions/{id}`
- `POST /api/v1/interactions/{id}/resolve`

#### Tasks

- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{id}`
- `POST /api/v1/tasks/{id}/start`
- `POST /api/v1/tasks/{id}/complete`
- `POST /api/v1/tasks/{id}/skip`
- `POST /api/v1/tasks/{id}/defer`
- `GET /api/v1/projects/{projectId}/tasks`

#### Incidents / treatment plans

- `POST /api/v1/incidents`
- `GET /api/v1/incidents`
- `GET /api/v1/incidents/{id}`
- `GET /api/v1/treatment-plans/{id}`

#### Weather

- `GET /api/v1/weather/latest`
- `GET /api/v1/weather/impacts`
- `POST /api/v1/weather/refresh`

#### Proposals

- `GET /api/v1/projects/{projectId}/proposals`
- `GET /api/v1/projects/{projectId}/proposals/{proposalId}`

#### Media

- `POST /api/v1/media`
- `GET /api/v1/media/{id}`

### Contract rules

- frontend should consume **structured payloads**, not CLI-formatted text
- approval-gated flows should be represented as **interactions**, not
  frontend-local confirmation logic
- human-readable summary fields are helpful, but not the primary API surface
- polling is acceptable in the first phase for:
  - pending interactions
  - latest triage
  - task changes

---

## Implementation phases

### Phase 1: Rhizome backend contract

Status: substantially complete for core operations. Remaining media-specific
work belongs with the media/vision follow-up.

- ✅ FastAPI internal API framework
- ✅ typed DTO/serializer layer for current domain objects
- ✅ API tests for triage, interactions, tasks, incidents, weather, activity,
  projects, search, and structured session context
- ✅ Cambium token-based auth and public proxy layer
- Remaining: media asset model and local upload handling

### Phase 2: Frontend core operations app

Status: in progress in Verdant.

- login screen
- startup triage flow
- dashboard with latest triage and pending interaction
- task list/detail/start/complete/defer flows
- incident list/detail and treatment-plan review
- weather snapshot and weather-change review

### Phase 3: Proposal and history surfaces

Backend:

- proposal/detail/review API shapes exist for backend use and should be refined
  against Verdant screens as needed
- recent interaction and activity-history payloads are exposed

Frontend:

- proposal list/detail/review UI
- interaction history screen
- richer task/project navigation

### Phase 4: Media-ready app boundary

Backend:

- stabilize attachment APIs and linking model
- make uploads usable for later visual-analysis workflows

Frontend:

- add upload UX and attachment display for supported entities

This phase is the direct handoff point into **Epic 2**.

---

## Completion criteria

This epic should be considered complete when:

- the main Rhizome interaction flows can be exercised through the app rather
  than primarily through the CLI
- the backend exposes clean, stable JSON payloads for interactions, tasks,
  triage, weather, incidents, treatment plans, and proposals
- single-account token-based login works end-to-end
- media/image attachments are supported in the backend/frontend flow
- the frontend can drive the core operational workflows without depending on
  terminal behavior

---

## Test expectations

### Rhizome repo

- internal API contract tests for every core resource listed above
- Cambium proxy/auth tests for login/session/logout and unauthorized access
- serializer/view tests to ensure DTOs are stable and structured-first
- media upload tests for valid/invalid files and metadata persistence once media
  routes land
- interaction resolution tests through the HTTP layer
- regression tests ensuring the backend remains usable without the CLI

### Frontend repo

- screen/component tests for:
  - dashboard triage
  - pending interaction review
  - task detail/actions
  - treatment-plan review
  - weather-change review
- integration tests against the API for:
  - login
  - triage run
  - resolve interaction
  - start/complete task
  - upload media
- one end-to-end “core ops” scenario:
  - login
  - run triage
  - resolve a pending interaction
  - open task details
  - complete a task
  - verify dashboard/task state updates

---

## Important dependencies

### Depends on

- existing Phase 5 interaction contract and APIs
- existing planner/tracker/triage/incident/weather foundations already built in
  Rhizome

### Strongly enables

- **Epic 2: Visual Garden Understanding**
- **Epic 3: Project Planning and Negotiation**
- **Epic 6: Reactive Monitoring and Alerting**

### Not blocked by

- no major uncompleted epic blocks this one

---

## Open questions to resolve during remaining implementation

- where uploaded media should live on disk and how stable access URLs should be
- what app history surface should expose from interaction records vs activity
  log
- how far proposal UI should go in the first shipped frontend phase versus the
  second
