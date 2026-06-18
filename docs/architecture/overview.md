# Rhizome — Architecture Overview

## System topology

Rhizome is one of three repositories in this project:

| Repo | Role | Owns |
|---|---|---|
| **rhizome** | Agent and domain engine | LangGraph graph, tools, DB schema, FastAPI layer |
| **verdant** | Frontend | UI, app shell, media upload UX |
| **fairlead** | Resource router | Inference routing, agent worker pool, session failover, VRAM accounting |

Each repo is independently deployable. Rhizome does not import from Fairlead — the connection between them is a standard OpenAI-compatible HTTP endpoint configured in `agent/model.py`. Fairlead has no knowledge of gardening or any application domain.

## Runtime topology

```
verdant (React)
    │
    │ HTTP/JSON  /api/v1
    ▼
rhizome (FastAPI + LangGraph)
    │
    │ in-process Python function calls
    ├── agent/tools/*     database reads/writes, external APIs, business logic
    │
    │ MCP protocol (future — vision sidecar, embedding sidecar)
    ├── [MCP sidecar processes]
    │
    │ HTTP  OpenAI-compatible  /v1/chat/completions
    ▼
fairlead (resource router)
    ├── loki  (Spark node)     primary inference
    ├── thor  (Spark node)     secondary / failover
    └── cloud APIs             Gemini Flash, Claude Haiku (last-resort fallback)
```

## What each repo explicitly does not own

**rhizome does not own:**
- Inference capacity or model serving
- GPU resource accounting
- Agent process scheduling at the infrastructure level

**verdant does not own:**
- Any domain logic
- Direct database access
- LLM calls

**fairlead does not own:**
- Application domain logic of any kind
- Database schema or migrations
- Session checkpoint storage (the application externalizes this to Postgres)
- MCP sidecar lifecycle (tracks their VRAM; does not start or stop them)
- End-user authentication

## API layer

The FastAPI layer lives inside the rhizome repo, not in a separate service. It is the HTTP surface that verdant consumes. Separating it into a fourth repo would add coordination overhead with no meaningful benefit at this scale — extract it if a second client or second developer joins later.

API routes live under `/api/v1`. See `docs/roadmap/epic_09_app_frontend_experience.md` for the full endpoint inventory and payload shapes.

## Database

Rhizome currently uses SQLite for both the application database and the LangGraph checkpoint. This is the migration target:

| Layer | Current | Target |
|---|---|---|
| Application DB | SQLite (SQLAlchemy) | Postgres |
| LangGraph checkpoint | SqliteSaver | langgraph-checkpoint-postgres |
| Vector search | Not yet active | pgvector (already in requirements.txt) |

The Postgres migration is a prerequisite for multi-instance deployment. Agent instances are stateless only when session state lives in shared external storage — with SQLite, each process has its own isolated state.

**High availability:** run Postgres with streaming replication (one primary, one replica across loki and thor). Patroni or pg_auto_failover handles automatic primary election when a node dies. This is infrastructure configuration, not application code.

**Why not sharding:** the per-user data volume for this application does not approach the thresholds where sharding helps. Sharding adds cross-shard query complexity with no benefit at this scale. Revisit if multi-tenant usage grows substantially.

## MCP sidecars

Some future tools will run as MCP sidecar processes rather than in-process Python functions. The signal that a tool belongs in a sidecar:

- It loads a heavy model at startup (vision model, embedding model) — should be loaded once and shared across all agent instances, not per-process
- It runs on specific hardware (GPU-bound)
- Its results are cacheable across sessions

The first expected sidecar is a vision analysis server for Epic 2 (Visual Garden Understanding). It exposes plant identification, pest candidate recognition, and layout assessment over MCP, and internally routes between local vision model and cloud multimodal APIs based on task complexity and VRAM availability.

When a sidecar performs its own inference, Fairlead must account for its VRAM consumption alongside the primary LLM serving process to avoid OOM scheduling conflicts.

## Fairlead connection

Rhizome connects to Fairlead exclusively through the model factory in `agent/model.py`. The factory constructs an LLM client pointed at Fairlead's OpenAI-compatible endpoint. If Fairlead is unavailable, the factory falls back to a direct cloud API connection.

The factory supports two model tiers:
- **Primary model** — planning, reasoning, proposal generation
- **Triage model** — session-start triage summaries (faster, cheaper)

Both tiers are configurable via environment variables. The graph never references a model provider directly.

## Dependency graph (epics)

```
E1 (Garden Profiling) ──► E2 (Visual Understanding)
E1 ──────────────────────► E3 (Planning & Negotiation)
E3 ──► E4 (Task Tracking) ──► E5 (Daily Triage)
E4 ──────────────────────────► E6 (Reactive Monitoring)
E3, E4, E6 ──────────────────► E7 (Iteration & Amendments)
E8 (Knowledge & Retrieval) ──► E2, E3, E6
E9 (App / Frontend) ─────────► E2, E3, E5
E11 (Platform Hardening) ────► E6, E8, E9
```

Current status: E4 and E5 are mostly complete. E1, E3, E6 are partial with strong foundations. E2, E7, E8, E10 not started. E9 backend contract exists; app not started. E11 not started in a focused way.
