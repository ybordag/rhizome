# Rhizome — Architecture Overview

**Last updated:** 2026-06

---

## System topology

Rhizome is one of four repositories in this system:

| Repo | Role | Language | Owns |
|---|---|---|---|
| **rhizome** | Agent and domain engine | Python | LangGraph graph, tools, DB schema, internal HTTP API |
| **cambium** | API gateway and auth | Go | JWT issuance, bcrypt auth, `/api/v1` proxy to Rhizome |
| **verdant** | Frontend | React | UI, app shell, media upload UX |
| **fairlead** | Inference router | TBD | GPU resource accounting, provider failover |

Each repo is independently deployable. Rhizome does not import from any of the others.

## Runtime topology

```
Verdant (React)
    │
    │  HTTP/JSON  /api/v1
    ▼
Cambium (Go, port 8080)
    │  ← verifies JWT, extracts user_id
    │  ← never trusts user_id from request body
    │
    │  POST /internal/...  { user_id: "...", ... }
    ▼
Rhizome (Python — FastAPI + LangGraph, port 8001)
    │
    │  in-process Python calls
    ├── agent/tools/*          — 93 tools across garden, projects, operations
    │
    │  HTTP  OpenAI-compatible  /v1/chat/completions
    ▼
Fairlead (resource router)
    ├── loki  (Spark node)     — primary inference
    ├── thor  (Spark node)     — secondary / failover
    └── cloud APIs             — Gemini Flash, Claude Haiku (last-resort fallback)
```

The browser never calls Rhizome directly — only Cambium. Rhizome is not publicly reachable. Cambium extracts `user_id` from the verified JWT and passes it in every internal request so Rhizome can scope all DB queries correctly.

## What each repo explicitly does not own

**Rhizome does not own:**
- Authentication or session token management (Cambium)
- Inference capacity or model serving (Fairlead)
- Frontend presentation (Verdant)

**Cambium does not own:**
- Domain logic (gardens, plants, tasks, proposals — all Rhizome)
- The Rhizome database schema or migrations
- Inference routing (Fairlead)

**Verdant does not own:**
- Any domain logic
- Direct database access
- LLM calls

**Fairlead does not own:**
- Application domain logic
- Database schema or migrations
- End-user authentication

## Rhizome internal structure

### Agent layer (`agent/`)

```
agent/
  core/       — LangGraph runtime (graph, nodes, state, model, telemetry, temporal)
  domain/     — domain logic (triage, planner, tracker, care, weather, incidents,
                interactions, activity_log)
  tools/
    garden/     — profile, plants, beds_containers, search
    projects/   — projects, planning, tracker (93 tools total)
    operations/ — triage, care, incidents, interactions, weather, activity
```

The graph runtime in `core/` calls domain modules in `domain/` and routes tool calls through `tools/`. Domain modules never import from `core/`. Tool files are thin wrappers that open a DB session, call domain logic, and return a string to the LLM.

### LangGraph workflow

```
session_context_intake
    ↓
weather_context_loader
    ↓
triage_reasoner  ─────→ (no tasks/context) → END
    ↓
llm_call
    ↓
should_continue ──── destructive/review tool call? ──→ interaction_node
    │                                                          │
    └── safe tool call? ──→ tool_node ──→ llm_call            │
    │                                                          │
    └── no tool call? ──→ END                  confirm → tool_node
                                               cancel  → END
```

`interaction_node` handles both destructive confirmations (delete_project, delete_bed, etc.) and structured approval flows (accept_project_proposal, approve_treatment_plan, approve_weather_task_changes). It uses LangGraph's `interrupt` primitive to pause and resume.

### DB layer (`db/`)

```
models.py    — all SQLAlchemy models (SQLite now, Postgres target)
database.py  — session factory (SessionLocal) and current_user_id ContextVar
seed.py      — dev seed data
```

Core domain object lifecycle:
```
GardenProfile
    └── GardeningProject
          ├── ProjectBrief → ProjectProposal → ProjectRevision → ProjectExecutionSpec
          │         └── TaskGenerationRun → Task (+ TaskDependency, TaskSeries)
          ├── ProjectBed / ProjectContainer / ProjectPlant
          └── IncidentReport → TreatmentPlan
```

Activity log:
```
ActivityEvent  ←  every tool write records at least one event
ActivitySubject  ←  links events to subject entities (plant, task, bed, etc.)
```

### API surface (internal → Cambium)

All endpoints are proxied by Cambium under `/api/v1`. The `user_id` is injected by Cambium from the verified JWT — never from the request body.

**Triage:** `POST /run`, `GET /latest`
**Interactions:** `GET /pending`, `GET /`, `GET /{id}`, `POST /{id}/resolve`
**Tasks:** `GET /`, `GET /due`, `GET /{id}`, `POST /{id}/start`, `POST /{id}/complete`, `POST /{id}/skip`, `POST /{id}/defer`, `PUT /{id}`, `GET /daily`
**Projects:** `GET /`, `GET /{id}`, `GET /{id}/brief`, `GET /{id}/schedule/preview`, `GET /{id}/progress`, `GET /{id}/activity`
**Proposals:** `GET /projects/{id}/proposals`, `GET /projects/{id}/proposals/{pid}`
**Incidents:** `GET /`, `GET /{id}`, `POST /`, `GET /{id}/activity`
**Treatment plans:** `GET /{id}`
**Weather:** `GET /latest`, `GET /impacts`, `POST /refresh`
**Activity:** `GET /activity`, `GET /plants/{id}/activity`, `GET /tasks/{id}/activity`, `GET /beds/{id}/activity`, `GET /incidents/{id}/activity`
**Media:** `POST /media`, `GET /media/{id}` — not yet implemented (Epic 2)

## Database

| Layer | Current | Target |
|---|---|---|
| Application DB | SQLite (SQLAlchemy) | Postgres |
| LangGraph checkpoint | SqliteSaver | langgraph-checkpoint-postgres |
| Vector search | Not yet active | pgvector (in requirements.txt) |

The Postgres migration is a prerequisite for:
- Multi-instance deployment (agent instances are stateless only when checkpoint state is in shared external storage)
- Proper FK enforcement (SQLite does not enforce FKs at runtime)
- Multi-tenancy at scale

## Fairlead connection

Rhizome connects to Fairlead exclusively through `agent/core/model.py`. The factory constructs an LLM client pointed at Fairlead's OpenAI-compatible endpoint. If Fairlead is unavailable, the factory falls back to a direct cloud API connection.

The factory supports two model tiers:
- **Primary model** — planning, reasoning, proposal generation
- **Triage model** — session-start triage summaries (faster, cheaper)

Both tiers are configurable via environment variables. The graph never references a model provider directly.

## Epic dependency graph

```
E1 (Garden Profiling) ──► E2 (Visual Understanding)
E1 ──────────────────────► E3 (Planning & Negotiation)
E3 ──► E4 (Task Tracking) ──► E5 (Daily Triage)
E4 ──────────────────────────► E6 (Reactive Monitoring)
E3, E4, E6 ──────────────────► E7 (Iteration & Amendments)
E8 (Knowledge & Retrieval) ──► E2, E3, E6
E9 (App / Frontend) ─────────► E2, E3, E5
E10 (Garden Ops Expansion) ──► E3, E5, E7
E11 (Platform Hardening) ────► E6, E8, E9
```

Current status: E4 and E5 are mostly complete. E1, E3, E6 partial with strong foundations. E9 backend API surface is complete; Cambium gateway is in progress. E2, E7, E8, E10 not started. E11 not started in a focused way.
