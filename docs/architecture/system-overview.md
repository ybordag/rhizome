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
| **fairlead** | Inference router | Rust | GPU resource accounting, provider failover |

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
    ├── agent/tools/*          — 94 tools across garden, projects, operations
    │
    │  provider seam in agent/core/model.py
    ▼
Model providers
    ├── direct cloud providers — Google Gemini, OpenAI, Anthropic
    └── Fairlead               — OpenAI-compatible local routing / failover track
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

Rhizome has four main internal surfaces:

- `agent/core/` runs the LangGraph workflow, model-provider seam, telemetry, and routing.
- `agent/domain/` owns deterministic domain behavior and shared serialization helpers.
- `agent/tools/` exposes LLM-callable wrappers that return strings.
- `agent/api/` exposes FastAPI routes that return structured JSON for Cambium/Verdant.

### Agent layer (`agent/`)

```
agent/
  core/       — LangGraph runtime (graph, nodes, state, model, telemetry, temporal)
  domain/     — domain logic (triage, planner, tracker, care, weather, incidents,
                interactions, activity_log)
  tools/
    garden/     — profile, plants, beds_containers, search
    projects/   — projects, planning, tracker (94 tools total)
    operations/ — triage, care, incidents, interactions, weather, activity
```

The graph runtime in `core/` calls domain modules in `domain/` and routes tool calls through `tools/`. Domain modules never import from `core`. Tool files are thin wrappers that open a DB session, call domain logic, and return a string to the LLM. API routes call domain/view helpers and return Pydantic views rather than exposing tool strings.

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
models.py    — all SQLAlchemy models
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

The API surface is split into `/internal/agent` for LangGraph execution and `/internal/data/...` for structured CRUD/query endpoints. Major data domains include garden profile/beds/containers/plants/batches, tasks and task series, projects/proposals/progress/expenses/shopping, triage, weather, incidents/treatment plans, interactions, alerts/notifications, threads/session context/pinned context, calendar annotations, activity, and search.

See [API Reference](api-reference.md) for the complete route list and response shapes.

### Request lifecycle

**Chat/agent request:**

```text
Verdant -> Cambium /api/v1/chat...
  -> Cambium verifies JWT, loads provider key, attaches user_id/thread_id
  -> Rhizome /internal/agent...
  -> LangGraph loads checkpoint, runs graph nodes, may call tools
  -> tools mutate/read SQLAlchemy domain tables
  -> graph checkpoint is persisted and response/stream returns through Cambium
```

**Data request:**

```text
Verdant -> Cambium /api/v1/...
  -> Cambium verifies JWT and injects user_id
  -> Rhizome /internal/data/...
  -> FastAPI route calls domain/view helpers or a tool-backed mutation
  -> SQLAlchemy query/mutation is scoped to user_id
  -> structured Pydantic view returns through Cambium
```

## Database

| Layer | Local quickstart | Shared dev / staging / production |
|---|---|---|
| Application DB | SQLite file via SQLAlchemy | Postgres in the `rhizome` schema |
| LangGraph checkpoint | SqliteSaver / AsyncSqliteSaver | PostgresSaver / AsyncPostgresSaver |
| Migrations | `create_all()` safety net only | Alembic |
| Vector search | Not active | pgvector planned |

`DATABASE_URL` selects the backend. If unset, Rhizome uses local SQLite files for quick CLI/dev runs. If it points at Postgres, both SQLAlchemy and the LangGraph checkpointer use the `rhizome` schema so any Rhizome instance can serve any user/thread.

## Model Provider Connection

Rhizome connects to model providers exclusively through `agent/core/model.py`. The factory supports environment defaults and per-request provider overrides from Cambium, so graph nodes never instantiate provider clients directly.

The factory supports two model tiers:
- **Primary model** — planning, reasoning, proposal generation
- **Triage model** — session-start triage summaries (faster, cheaper)

Both tiers are configurable via environment variables. Google Gemini is the default provider path today; OpenAI, Anthropic, and future Fairlead/OpenAI-compatible routing belong behind the same seam.

## Where Status Lives

This page describes the durable architecture. Implementation status and dependency sequencing live in [Roadmap Overview](../roadmap/overview.md). Completed build plans and superseded implementation notes live in [Archive](../archive/README.md).
