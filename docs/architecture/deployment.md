# Deployment Architecture

How Rhizome is deployed, why instances are stateless, how horizontal scaling works, and the tooling stack from local dev to production.

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

### Schema and migrations

All Rhizome domain tables live in the **`rhizome` schema**. The SQLAlchemy engine and LangGraph checkpointer both set `search_path=rhizome`. The `cambium` schema (users, refresh_tokens) is owned by Cambium and never queried by Rhizome.

**Alembic** manages schema migrations. Before deploying a Rhizome update that includes model changes:

```bash
# On the deployment host (or in a migration job/init container):
alembic upgrade head
```

This is safe to run before the new Rhizome processes start — migrations are idempotent and run against the live Postgres without downtime for simple column additions. For destructive changes (DROP COLUMN), coordinate with a blue/green deploy.

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

**Domain logic lives in Python.** The 94 tools in `agent/tools/` contain validation logic (status guards, orphan prevention, constraint checks) that is naturally expressed alongside the SQLAlchemy models. Moving this to Go would require reimplementing it in a different language with no benefit except process separation.

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

---

## Tooling stack

### The four tools and what each one does

| Tool | Layer | Does |
|---|---|---|
| **Docker** | Container build + local runtime | Builds images from Dockerfiles; runs containers locally |
| **Docker Compose** | Local orchestration | Defines and starts all services together on one machine |
| **k3s** | Production orchestration | Manages containers across Thor + Loki; schedules, restarts, scales |
| **Helm** | K8s package manager | Installs third-party software (Postgres, Redis) onto k3s with one command |

These are complementary layers, not alternatives. Docker builds the images. Docker Compose runs them locally. k3s runs them in production. Helm installs pre-packaged third-party services onto k3s.

### `kubectl` — the k3s remote control

`kubectl` is a CLI client that sends commands to the k3s API server. It does no containerization — it's analogous to `psql` for Postgres. Having `kubectl` installed without a cluster to point it at does nothing.

k3s uses **containerd** as its container runtime (not Docker). Docker is not required on the production nodes — only on the dev machine for building images.

### Local dev workflow (Mac)

```
docker build -t ghcr.io/ybordag/rhizome:latest .   # build image
docker compose up                                   # run full stack locally
docker compose down                                 # tear down
```

`docker-compose.yml` defines all services — Postgres, Rhizome ×2, Cambium — and their environment variables. Service names (`postgres`, `rhizome`) become hostnames inside Docker's internal network.

### Production workflow (Thor + Loki)

```
Your Mac  →  docker build + push to GHCR  →  GitHub Container Registry
                                                        │
Thor + Loki  ←  k3s pulls image from GHCR  ←──────────┘
```

The registry is the handoff point. You never copy images directly between machines.

**Cluster topology:**

| Node | Role | Runs |
|---|---|---|
| **Thor** | Control plane + worker | k3s API server, scheduler, etcd; Cambium, Verdant, Rhizome #1 |
| **Loki** | Worker | Postgres, Rhizome #2 |

Postgres on Loki means Rhizome #2 has local DB access. Thor does control-plane overhead so heavier workloads are preferentially scheduled on Loki.

### Helm for third-party services

Raw K8s manifests for a single service like Postgres require ~5 YAML files (Deployment, Service, PersistentVolumeClaim, Secret, ConfigMap). Helm bundles these into a single installable package with a `values.yaml` for configuration.

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install rhizome-db bitnami/postgresql \
  --set auth.postgresPassword=secret \
  --set primary.persistence.size=20Gi
```

**Rule of thumb:** use Helm charts for third-party software (Postgres, nginx, Prometheus); write raw K8s manifests for your own services (Rhizome, Cambium, Verdant).

### Docker Compose vs Helm chart — same idea, different target

Both describe "which services exist and how they connect." The difference is the runtime they target:

```
docker-compose.yml   →  Docker (local dev, one machine)
Helm chart / K8s     →  k3s (production, cluster)
```

`kompose` can convert a Compose file to K8s manifests as a starting point, though the output usually needs cleanup. In practice you maintain both: Compose for fast local iteration, K8s manifests for production.
