# Architecture Guide

Use this section to build a working mental model of Rhizome before changing the graph, database models, API routes, or deployment shape.

## Reading Order

1. [System Overview](system-overview.md) — repo boundaries, runtime topology, internal layers, and core invariants.
2. [Agent Loop](agent-loop.md) — how one graph turn moves through intake, weather, triage, LLM calls, tools, and interactions.
3. [Data Model](data-model.md) — durable domain objects, thread metadata, checkpointer state, and migrations.
4. [API Reference](api-reference.md) — internal Rhizome routes and the structured JSON contract proxied by Cambium.
5. [Tools Reference](tools-reference.md) — LLM-callable tool inventory and tool conventions.
6. [Deployment](deployment.md) — stateless instance model, Postgres/checkpointer topology, k3s, and operational notes.
7. [Async Vision Compute](async-vision-compute.md) — planned async vision job ownership across Rhizome and Fairlead.

## Core Invariants

- Cambium owns authentication. Rhizome receives a trusted `user_id` from Cambium and scopes data with it.
- Rhizome owns domain state and domain invariants. Cambium and Verdant do not write Rhizome tables directly.
- Tools return strings for the LLM. API routes return structured Pydantic views for Verdant.
- Domain logic belongs in `agent/domain/`; tools and routers should call domain helpers rather than duplicating rules.
- Conversation content lives in the LangGraph checkpointer. `Thread` stores metadata and small app-facing context documents, not duplicated message bodies.
- Shared environments use Postgres plus Alembic. SQLite is for quick local runs and isolated tests.
- Consequential actions flow through structured interactions or confirmations before mutation.

## Main Runtime Boundaries

```text
Verdant
  -> Cambium /api/v1
    -> Rhizome /internal/agent      graph execution and chat
    -> Rhizome /internal/data/...   structured CRUD/query endpoints
      -> SQLAlchemy domain tables
      -> LangGraph checkpointer
```

Within Rhizome:

```text
agent/core      LangGraph runtime and provider seam
agent/domain    deterministic domain rules and view helpers
agent/tools     LLM-callable wrappers returning strings
agent/api       FastAPI routers returning structured JSON
db              SQLAlchemy models, sessions, migrations target
```

When adding behavior, decide first which boundary owns it:

- A new deterministic rule usually belongs in `agent/domain/`.
- A new chat capability usually needs a tool wrapper plus prompt/graph consideration.
- A new frontend contract usually needs a route, request model, response view, docs, and API tests.
- A schema change needs `db/models.py`, Alembic migration, and focused regression tests.
