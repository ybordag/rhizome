# Vision and Design

## The problem

Hobby gardening is a planning and reasoning problem disguised as a hobby.

Even a small garden involves dozens of interdependent constraints: limited bed space distributed unevenly across sun zones; soil that may need amendment or workarounds; frost windows that bound when seeds can go out; plants that need weeks of indoor propagation before transplanting; a budget that must stretch across materials, plants, and containers; pests that require organic-first responses; and a user who has finite time and energy and can't always act when the ideal moment arrives.

These constraints don't live in separate silos. A decision about which plants to grow determines the seed-start timeline. That timeline determines how many tray slots are needed. Tray capacity affects how many concurrent projects are feasible. Project count affects task density. Task density affects what can realistically happen in a given week. None of this is capturable in a to-do list or a static spreadsheet.

The **core challenge** is that good gardening advice requires reasoning over all of these simultaneously, remembering decisions made across sessions, updating the plan when reality diverges from it, and doing so in a way the user can actually act on.

---

## Design philosophy

**Rhizome is an advisor and co-worker, not a task list.**

The distinction matters. A task list records what you decided. An advisor helps you decide — surfacing constraints you forgot, flagging when a plan isn't feasible, explaining what happens if you skip something, and adapting to what actually happened. Rhizome aims to be the latter.

Four principles underpin the design:

**1. Persistent, specific knowledge.** The agent knows *your* garden — your beds, containers, climate zone, frost dates, existing plants, care history, project state. Every session starts with full context. Advice is grounded in what's actually true for you, not generic recommendations.

**2. Planning as a first-class activity.** Before tasks exist, projects need to be planned. Rhizome supports a full negotiation loop: user describes a goal → agent checks constraints and surfaces tradeoffs → proposal with cost/timeline/effort estimates → user approves or revises → tasks generated. The plan is versioned. If circumstances change, the plan can be revised.

**3. Transparency over automation.** Consequential actions — approving a plan, applying weather-driven task changes, deleting something — require explicit user confirmation. The agent proposes; the user decides. This isn't a safety guardrail bolted on; it's the core interaction model.

**4. Long-horizon awareness.** A seed started today will be transplanted in 10 weeks. A deadline missed today might not surface as a problem for 3 weeks. Rhizome tracks these horizons explicitly — deadlines, windows, event anchors, recurring series — so the daily view ("what should I do today?") is always grounded in the full timeline.

---

## What Rhizome is built for

A single user (or a small household) managing a hobby garden. Think:

- Growing vegetables and flowers in a Zone 9b Bay Area garden
- Managing beds, raised containers, and growbags simultaneously
- Planning spring planting in January, executing through summer, into fall harvest
- Organic-first, budget-conscious, limited weekend time

The current implementation is **single-tenant** (one user, `user_id == 1`). Multi-tenancy is on the roadmap and the schema is ready for it, but the tools don't yet thread user identity into every query.

The **full product vision** includes a React frontend (Verdant), but the current UX is a CLI. The CLI is a simulation surface, not the final product — every feature is designed for eventual app consumption.

---

## The interaction surface

Rhizome interactions fall into four categories:

**Conversational turns** — the user sends a message, the LLM responds, possibly calling tools along the way. Most interactions are this: "how are my tomatoes doing?", "what should I do today?", "did I fertilize the peppers recently?"

**Structured approvals** — when the agent proposes something consequential (a project plan, a treatment approach, weather-driven task changes), the interaction pauses. The user is shown a structured card with the proposal details and action buttons. The graph resumes only after the user responds. This uses LangGraph's `interrupt` primitive.

**Destructive confirmations** — before any delete operation, the agent halts and presents a confirmation card. The user must explicitly confirm. If they cancel, no changes are made.

**Care and task updates** — completing a task triggers side effects: care timestamps update on linked plants, containers, and beds; dependent tasks unblock; activity events record the change. The user doesn't manage this plumbing manually.

---

## The multi-repo system

Rhizome is the **domain engine** — it holds all the gardening knowledge, manages the DB, and runs the agent. It is not responsible for user-facing auth, API versioning stability, or frontend concerns.

Those responsibilities belong to other repos:

**Cambium** (Go) sits between the frontend and Rhizome. It owns JWT issuance, bcrypt password hashing, refresh token rotation, and stable versioned `/api/v1` endpoints. This separation means Rhizome can evolve its internal API without breaking the frontend — Cambium absorbs changes. It also means Rhizome never handles plaintext passwords or session tokens.

**Verdant** (React) is the frontend app. It consumes only the Cambium API and has no knowledge of LangGraph, SQLAlchemy, or Rhizome internals.

**Fairlead** is the inference router. It presents an OpenAI-compatible endpoint and handles GPU resource accounting, LLM failover (loki → thor → cloud), and concurrency management. Rhizome connects to it through a standard HTTP client in `agent/core/model.py`. If Fairlead is unavailable, the model factory falls back to direct cloud APIs.

This design keeps each repo independently deployable and independently understandable.

---

## What Rhizome does not do (yet)

- **Multi-user / shared gardens** — user_id is hardcoded to 1 in ~15 files pending the multi-tenancy pass
- **Image analysis** — plant identification, visual pest diagnosis (Epic 2, needs media upload API first)
- **Automated purchasing** — no e-commerce integration
- **IoT sensors** — no soil moisture or weather station integration
- **Proactive background monitoring** — weather refresh is user-triggered; scheduled monitoring is Epic 6
- **External knowledge retrieval** — plant databases (Perenual), pest observations (iNaturalist) are Epic 8
