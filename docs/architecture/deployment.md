# Deployment Architecture

How Rhizome is deployed, why instances are stateless, and how horizontal scaling works.

---

## Topology

```
                        ┌─────────────────────────┐
                        │  Verdant (React)         │
                        │  DGX Spark A             │
                        └────────────┬────────────┘
                                     │ HTTPS /api/v1
                        ┌────────────▼────────────┐
                        │  Cambium (Go)            │
                        │  DGX Spark A             │
                        │  JWT auth, key mgmt,     │
                        │  request routing         │
                        └────────────┬────────────┘
                                     │ HTTP internal
                    ┌────────────────┼────────────────┐
                    │                │                │
          ┌─────────▼──────┐  ┌──────▼────────┐     ...
          │  Rhizome #1    │  │  Rhizome #2   │
          │  DGX Spark A   │  │  DGX Spark B  │
          │  LangGraph     │  │  LangGraph    │
          │  agent worker  │  │  agent worker │
          └─────────┬──────┘  └──────┬────────┘
                    │                │
                    └────────┬───────┘
                             │ DATABASE_URL
                   ┌─────────▼─────────┐
                   │  Postgres          │
                   │  DGX Spark B       │
                   │  cambium schema    │
                   │  rhizome schema    │
                   └───────────────────┘
```

Cambium and Verdant run on Spark A. Postgres runs on Spark B. Rhizome instances can run on either node.

---

## Why Rhizome instances are stateless

A service is stateless when **no instance holds data that another instance cannot access**. All persistent state in Rhizome lives in Postgres:

### Domain data (`rhizome` schema)

Every write a Rhizome tool performs goes to Postgres via SQLAlchemy. Reads come from the same source. An instance that has never seen a particular user's garden can serve any request for that user — it just opens a session against the shared Postgres instance.

### Conversation state (LangGraph checkpointer)

LangGraph persists the full graph state (message history, node outputs, interrupt state) to a checkpointer after every node execution. With `PostgresSaver`, this checkpoint is written to Postgres, not to a local file or in-process memory.

This means:
- A user's conversation can be resumed by any Rhizome instance, not just the one that started it
- If an instance dies mid-graph, the next request picks up exactly where execution was interrupted
- No sticky sessions or session affinity required at the load balancer

### What "stateless" does *not* mean

Stateless does not mean Rhizome avoids the database. It means Rhizome carries no state that isn't in the database. Each request opens a DB connection, does its work, and closes it. The instance itself holds nothing between requests.

---

## Horizontal scaling

Adding capacity is adding workers:

```
# Before
Cambium → Rhizome #1 → Postgres

# After (more load)
Cambium → load balancer → Rhizome #1 → Postgres
                        → Rhizome #2 ↗
                        → Rhizome #3 ↗
```

Because all instances share Postgres, no coordination is needed between workers. Cambium (or a load balancer in front of Rhizome) distributes requests round-robin. Each instance is interchangeable.

### Current deployment

Two DGX Spark nodes. Practical topology:

| Service | Node |
|---|---|
| Verdant (static) | Spark A |
| Cambium | Spark A |
| Rhizome #1 | Spark A |
| Rhizome #2 | Spark B |
| Postgres | Spark B |

This gives two Rhizome workers across two nodes. Postgres on Spark B means Rhizome #2 has local DB access; Rhizome #1 crosses the network. At this scale, latency is negligible.

### Postgres connection pooling

With multiple Rhizome instances, each runs its own SQLAlchemy connection pool. At 2–4 instances, the default pool size (5 connections per instance) is well within Postgres's default limit (100). If the instance count grows, add PgBouncer as a connection pooler in front of Postgres.

---

## Thread routing

Each conversation has a `thread_id`. Cambium generates this on first message and includes it in every internal request to Rhizome. Any Rhizome instance can serve any `thread_id` — the LangGraph checkpointer loads the full graph state from Postgres at the start of each turn.

```
User sends message
    → Cambium validates JWT, extracts user_id
    → Cambium looks up or generates thread_id
    → Cambium routes to any available Rhizome instance
    → Rhizome loads thread state from Postgres checkpointer
    → Rhizome runs graph turn, writes checkpoint back to Postgres
    → Rhizome returns response
    → Cambium forwards response to client
```

No affinity. No sticky sessions. Any instance handles any thread.

---

## Why Rhizome keeps its database layer

An alternative architecture treats Rhizome as a **pure inference worker** — no DB access of its own. Cambium would own all data reads and writes; Rhizome would receive a pre-loaded context payload and return only AI output.

This was considered and rejected for this project. The reasons:

**Domain logic lives in Python.** The 93 tools in `agent/tools/` contain validation logic (status guards, orphan prevention, constraint checks) that is naturally expressed alongside the SQLAlchemy models. Moving this to Go would require reimplementing it in a different language with no benefit except process separation.

**Tool calls need live data.** The LangGraph agent calls tools iteratively — it might call `list_tasks`, inspect the result, then call `complete_task`. Pre-loading all context Cambium might need to provide is not feasible without Cambium understanding the agent's full decision tree.

**Statelessness is already achieved.** The goal of extracting the DB layer is stateless instances — but Rhizome instances are already stateless in the meaningful sense. All state is in Postgres. The instances carry nothing between requests. Adding process separation would not change this property.

**Temporal compatibility.** If this project grew to the point where Temporal (workflow orchestration) made sense, Rhizome workers could map directly to Temporal Activities, with the LangGraph graph execution as a Temporal Workflow. This architecture is compatible with that evolution without requiring Rhizome to shed its DB access — Temporal workers routinely access databases directly.

---

## Future evolution: Temporal

[Temporal](https://temporal.io) is a workflow orchestration engine. It adds durable execution, retries, visibility, and scheduling to long-running processes. Companies like Uber, Stripe, and Netflix use it for exactly the kind of multi-step async workflows Rhizome runs.

What Temporal would add to this architecture:

- **Durable execution beyond a single request.** Today, if Cambium drops a request before Rhizome responds, the work is lost. With Temporal, the workflow survives process death and is retried automatically.
- **Scheduled workflows.** Triage could run on a cron schedule as a Temporal workflow rather than being triggered by a user message.
- **Visibility.** Temporal's UI shows every workflow execution, its current state, and its history — operationally useful at scale.
- **Backpressure.** Temporal's task queue naturally limits concurrent Rhizome invocations without a separate rate limiter.

The current architecture is Temporal-compatible. The mapping would be:

| Now | With Temporal |
|---|---|
| Cambium HTTP call to Rhizome | Temporal workflow enqueue |
| Rhizome request handler | Temporal Worker + Activity |
| LangGraph graph turn | Temporal Workflow execution |
| LangGraph checkpointer | Temporal's built-in event history |

This migration is not warranted at 2-node scale. It would make sense if the project needed to handle background long-running operations, complex retry logic, or multi-step workflows that span multiple agent calls over time.
