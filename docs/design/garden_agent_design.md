# Garden Helper Agent — Design Document

**Version:** 0.1 (draft)
**Status:** In design — pre-implementation
**Authors:** Yashi + Claude

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Goals and Non-Goals](#2-goals-and-non-goals)
3. [User Context](#3-user-context)
4. [System Overview](#4-system-overview)
5. [Core Abstractions](#5-core-abstractions)
6. [Workflows](#6-workflows)
7. [Data Model](#7-data-model)
8. [Tools and External Resources](#8-tools-and-external-resources)
9. [Design Decisions](#9-design-decisions)
10. [Open Design Problems](#10-open-design-problems)
11. [Build Order and Immediate Blockers](#11-build-order-and-immediate-blockers)

---

## 1. Problem Statement

Hobby gardening is a deceptively complex management task. Even a small to medium garden involves juggling competing constraints, long-horizon planning, real-time reactive decisions, and deep domain knowledge that most gardeners don't have at hand.

### Limitations gardeners face

1. **Space** — limited and unevenly distributed across sun/shade zones
2. **Soil** — poor native soil (e.g. hard clay) requiring amendment or workarounds like containers
3. **Sunlight** — shade from trees, structures, and neighboring properties
4. **Local climate** — desire to grow plants suited to a different climate (e.g. cottage garden aesthetic in dry Bay Area)
5. **Physical labor** — time and energy are finite; some tasks require more effort than others
6. **Existing vegetation** — trees and established plants that may compete with or enable new plantings
7. **Dogs and children** — safety constraints on plant toxicity and placement
8. **Pests** — ongoing management with a preference for minimal-harm organic approaches
9. **Time** — planning horizon spans seasons; tasks must be sequenced and timed correctly
10. **Cost** — plants, soil, containers, and tools are expensive; bulk buying has logistics challenges

### Complexities (competing goals)

1. Wanting a specific aesthetic (e.g. cottage garden) in an incompatible climate
2. Growing both flowers and vegetables with different care requirements
3. Growing organically while maintaining plant health and yield
4. Balancing beauty and function
5. Protecting plants without harming beneficial insects and wildlife
6. Saving money while minimizing effort
7. Using containers/growbags for better conditions without creating visual clutter
8. Optimizing plant density while meeting nutrient and space needs
9. Growing many varieties within hard limits on soil, sunlight, space, and cost
10. Buying in bulk to save costs without storage or transport infrastructure

### The core challenge

These aren't independent problems — they are deeply interdependent. A decision about which plants to grow affects the seed schedule, which affects tray space allocation, which affects project timelines, which affects budget. Good advice requires reasoning over all of these simultaneously, remembering prior decisions, and updating the plan when things change.

---

## 2. Goals and Non-Goals

### Goals

- Act as an **advisor, coach, and co-worker** — not just a task list
- Understand the **physical layout** of the garden from description, photos, or video
- Maintain a **persistent model** of the garden that accumulates knowledge over time
- Help the user **plan and iterate** on gardening projects with explicit constraint handling
- Generate **time-sensitive task schedules** accounting for seed-start timelines, frost dates, and transplant windows
- Provide **proactive alerts** based on weather forecasts and pest reports
- Recommend **cost-effective solutions** and always offer deferral when the user can't act immediately
- Minimize harm to beneficial insects and wildlife in all recommendations
- Support a **two-step transplant process**: seed tray → red cup water reservoir → final location

### Non-Goals (for initial version)

- Automated purchasing or e-commerce integration
- IoT sensor integration (soil moisture, weather stations)
- Computer vision–based autonomous pest diagnosis without user confirmation
- Multi-user / shared garden management
- Professional or commercial-scale farming

---

## 3. User Context

The initial user is a hobby gardener in the **San Francisco Bay Area (USDA zone 9b)** with the following setup:

**Property:** ~7,000 sqft lot, ~1,000 sqft of active garden area across:
- Front yard: small beds along the front, small strip of lawn
- Courtyard: a few very small beds, one medium bed
- Backyard: mostly slope with beds, plants, and 3 large trees that shade most of the slope

**Infrastructure:**
- 8 seed trays that can go under grow lights
- Additional trays must be placed in a safe sunny spot (protected from dogs)
- Red cup water reservoir system for intermediate transplant stage
- Pots and growbags as primary growing containers (to work around hard clay soil and shade)

**Preferences:**
- Organic methods strongly preferred; neem oil and manual pest removal over chemical pesticides
- Cottage garden aesthetic as a goal despite dry Bay Area climate
- Growing both flowers and vegetables
- Cost-consciousness: growing from seed, propagating from cuttings where possible
- Protecting dogs, children, and beneficial wildlife

---

## 4. System Overview

The Garden Helper Agent is a **LangGraph-based multi-workflow agent** with persistent memory. It is organized around the concept of **gardening projects** — scoped, goal-driven units of work that accumulate state over time.

### Top-level workflows

```
┌─────────────────────────────────────────────────────────────────┐
│                    Persistent Memory (database)                  │
│  garden profile · plant inventory · projects · task queue       │
└──────────┬──────────────────────────────────────────┬───────────┘
           │ read/write                               │ read/write
           ▼                                          ▼
┌──────────────────┐   ┌─────────────────────────────────────────┐
│ Garden Profiling │   │         Project Management              │
│ (onboarding +    │   │  ┌──────────┐ ┌──────────┐ ┌─────────┐ │
│  updates)        │   │  │ Planning │ │Iterating │ │  Task   │ │
└──────────────────┘   │  └──────────┘ └──────────┘ │ Creation│ │
                       │                             └─────────┘ │
                       └─────────────────────────────────────────┘

┌─────────────────────────┐   ┌────────────────────────────────┐
│    Task Management      │   │     Reactive Monitoring        │
│ (surfaces tasks across  │   │ (weather, pests, events —      │
│  all active projects)   │   │  triggers project iterations)  │
└─────────────────────────┘   └────────────────────────────────┘
```

### Key architectural principles

- **Projects are the unit of work.** Plant advisory and seed planning are not standalone workflows — they are phases of a project lifecycle.
- **State is owned by entities, not workflows.** Workflows read and write to persistent entities (the garden profile, projects). Workflows themselves are stateless; entities are stateful.
- **Triage is reasoning, not sorting.** Task priority is computed at query time by the LLM given session context — it is not stored as a static field.
- **Hard constraints are checked before proposals are generated.** Soft preferences are the optimization target.

---

## 5. Core Abstractions

### 5.1 Garden Profile

The global, persistent model of the physical garden. Built once during onboarding, updated when the garden changes.

```python
class GardenProfile(TypedDict):
    climate_zone: str                     # e.g. "9b"
    frost_dates: FrostDates               # last spring frost, first fall frost
    beds: list[Bed]                       # all named beds/areas with dimensions + sunlight
    containers: list[Container]           # pots, growbags with size and location
    tray_capacity: int                    # total seed trays available (8 under lights + outdoor)
    tray_indoor_capacity: int             # trays under grow lights (8)
    native_soil_type: str                 # e.g. "hard clay"
    hard_constraints: HardConstraints     # dogs, children → non-toxic; budget ceiling; etc.
    soft_preferences: SoftPreferences     # aesthetic goals, organic preference, etc.
```

### 5.2 Plant Inventory

The current state of all plants in the garden — both existing and planned.

```python
class Plant(TypedDict):
    id: str
    name: str
    species: str
    location: str                         # bed_id or container_id
    status: Literal["existing", "planned", "removed"]
    value_to_gardener: str                # why this plant is kept
    climate_suitability: str              # assessment of fit to zone 9b
    recommend_keep: bool
    notes: str
```

### 5.3 Gardening Project

The central unit of work. Scoped to specific garden resources, with a goal, constraints, plan, and task list.

```python
class GardeningProject(TypedDict):
    id: str
    name: str
    status: Literal["planning", "active", "paused", "maintaining", "complete"]

    # Scope — what resources does this project own?
    beds: list[str]                       # bed IDs from garden profile
    containers: list[str]                 # container IDs
    tray_slots: int                       # how many of the 8 indoor trays this reserves

    # Goal and constraints
    goal: str                             # user's stated intent in natural language
    budget_ceiling: float                 # per-project budget cap
    target_completion: date | None

    # Planning artifacts
    plant_list: list[PlannedPlant]        # plants approved for this project
    approved_plan: Plan | None            # the negotiated, accepted plan
    negotiation_history: list[Exchange]   # proposals made and responses given

    # Execution artifacts
    tasks: list[Task]                     # generated from the approved plan
    seed_schedule: list[SeedEvent]        # sow → red cup → final location events

    # Change log
    iterations: list[Iteration]           # amendments to the plan with reason + date
```

### 5.4 Project Status Lifecycle

```
planning ──► active ──► maintaining
    ▲            │            │
    │            ▼            ▼
    └────── paused ◄──────────┘
                 │
                 ▼
             complete
```

**Status meanings:**
- `planning` — goal set, plan being negotiated, no tasks yet generated
- `active` — plan approved, seed schedule running, time-sensitive tasks in flight
- `maintaining` — plants established, steady-state care only (seasonal pruning, mulching, dividing)
- `paused` — user has deferred; agent holds state and resurfaces when appropriate
- `complete` — project is truly done (bed being removed, annual season ended)

**Why `maintaining` is distinct from `active`:**
- Task generation shifts from dense time-sensitive events to light recurring cadence
- Iteration triggers change from urgent (pest, frost) to opportunistic (add a variety, propagate)
- Re-entry from `paused` during `maintaining` generates a fresh seasonal task list (spring wake-up), not a catch-up on missed tasks
- Alert urgency from reactive monitoring is lower for established plants than tender seedlings

### 5.5 Task Model

Tasks have two independent dimensions: **type** (what kind of work) and **urgency** (how time-sensitive).

```python
class Task(TypedDict):
    # Identity
    id: str
    project_id: str | None                # None for garden-wide maintenance

    # Classification (two independent dimensions)
    type: Literal["emergency", "milestone", "maintenance", "opportunistic"]
    urgency: Literal["blocker", "time_sensitive", "scheduled", "backlog"]

    # Timing
    deadline: date | None                 # hard deadline — miss this and the task fails
    window_start: date | None             # earliest useful date
    window_end: date | None               # after this, opportunity is gone (perishable tasks)
    scheduled_date: date | None           # calendar date for scheduled tasks

    # Consequence metadata (generated by LLM at task creation, stored as free text)
    what_happens_if_skipped: str
    what_happens_if_delayed: str
    reversible: bool                      # strong signal: irreversible consequences rank higher

    # Execution
    description: str
    estimated_minutes: int
    can_defer_to: date | None             # user-set deferral date
```

**Urgency escalation** (automatic, calendar-driven):
```
backlog → scheduled        (window_end is ~2 weeks away)
scheduled → time_sensitive (window_end is ~3 days away)
time_sensitive → blocker   (window_end is tomorrow, OR external event triggered)
```

Reactive monitoring can **override** urgency directly — a frost warning upgrades all `task_type="emergency"` tasks for vulnerable plants to `blocker` immediately.

### 5.6 Session Context

Collected at the start of each session (inferred from casual conversation, not a formal form):

```python
class SessionContext(TypedDict):
    available_minutes: int | None
    energy_level: Literal["low", "medium", "high"] | None
    focus: str | None                     # e.g. "I really want to work on the tomatoes today"
    constraints: str | None              # e.g. "my back hurts, nothing heavy"
```

---

## 6. Workflows

### 6.1 Garden Profiling

**Trigger:** First-time onboarding, or user-initiated update ("I added a new bed").
**Output:** Updated `GardenProfile` and `PlantInventory` in the database.

**Nodes:**
- `intake_conversation` — multi-turn Q&A to gather bed dimensions, sunlight zones, soil type, existing plants, constraints
- `image_analyzer` — accepts photos/video to identify plants and assess conditions
- `profile_builder` — structures raw information into the `GardenProfile` schema
- `plant_assessor` — evaluates each existing plant for keep/remove recommendation based on value, climate suitability, and planned changes
- `profile_writer` — persists to database

**Key behaviors:**
- Always asks for photos when spatial layout or plant identification is ambiguous
- For any recommended removal, provides timing and cost estimate and always offers a deferral option
- Identifies plants that are unsuitable for zone 9b and flags them

---

### 6.2 Project Management

Contains three sub-workflows that share project state.

#### 6.2.1 Planning

**Trigger:** User starts a new project ("I want to plant a cottage garden in the front bed this spring").
**Output:** `approved_plan` written to project, project status → `active`.

**Nodes:**
- `goal_parser` — extracts intent, scope, implicit constraints from the user's stated goal
- `constraint_checker` — validates against hard constraints (is this bed free? is the timeline feasible given frost dates and seed-start lead times?). If a hard constraint is violated, surfaces a clear explanation rather than generating proposals.
- `resource_checker` — checks tray slot availability across all active projects; surfaces conflicts
- `proposal_generator` — generates 2–3 plans, each satisfying all hard constraints, making different tradeoffs on soft preferences. Each proposal includes plant list, estimated cost, effort level, and tradeoff summary.
- `human_interrupt` — LangGraph interrupt point; user accepts, negotiates, or defers
- `plan_committer` — writes approved plan to project, triggers task creation

**Negotiation loop:**
```
goal_parser → constraint_checker → proposal_generator → human_interrupt
                                          ▲                    │
                                          │    negotiate        │ accept
                                          └────────────────────┘
                                                                │ defer
                                                                ▼
                                                         defer_handler
```

**Proposals always include 3 options:**
- Option A: maximizes the user's stated aesthetic/goal
- Option B: maximizes cost-effectiveness
- Option C: minimizes effort/labor

#### 6.2.2 Iterating

**Trigger:** User-initiated change ("I want to add marigolds as companions") or reactive monitoring ("frost warning — intervention needed").
**Output:** Amended plan written to project, new tasks generated, iteration logged.

**Key difference from planning:** The objective is to minimally disrupt what's already been decided, not to find the best possible plan from scratch. Proposals are amendments to the existing plan, not replacements.

**Nodes:**
- `change_parser` — understands what's changed and why
- `impact_assessor` — determines what parts of the existing plan are affected
- `amendment_generator` — proposes minimal changes that address the trigger
- `human_interrupt` — user approves or negotiates amendment
- `plan_updater` — writes amendment, logs iteration, triggers incremental task update

#### 6.2.3 Task Creation

**Trigger:** Automatically after plan approval or iteration acceptance.
**Output:** `tasks` and `seed_schedule` written to project.

**Nodes:**
- `schedule_generator` — computes seed start dates backwards from last frost date using plant germination data; accounts for the two-step transplant process (sow → red cup → final location)
- `space_allocator` — fits seed schedule into available tray slots (8 indoor + outdoor), respects reservations from other active projects
- `task_generator` — creates all tasks with deadlines, windows, consequence metadata, and `reversible` flag
- `task_writer` — persists to project

**Two-step transplant events generated per plant:**
1. `sow` — start seeds in tray (indoor or outdoor)
2. `transplant_to_red_cup` — move seedlings to red cup water reservoir system
3. `transplant_to_final` — move to pot, growbag, or bed

---

### 6.3 Task Management

**Trigger:** User asks "what should I do today?" or opens the daily view.
**Output:** Prioritized task recommendations with explicit tradeoff reasoning.

**Key design principle:** Priority is **not stored**. It is **computed at query time** by a triage node that reasons over the full task list given session context. The LLM can generate new consequence framings on the fly when existing ones don't fit the situation.

**Nodes:**
- `session_context_intake` — infers `SessionContext` from opening message
- `task_loader` — loads all pending tasks across all active projects
- `urgency_escalator` — applies calendar-based escalation rules (window closing → upgrade urgency)
- `triage_reasoner` — LLM node: reasons over all tasks given session context, produces ranked recommendations with explicit reasoning about tradeoffs between competing objectives (minimize immediate loss vs. maintain gardening velocity)
- `reminder_formatter` — formats the output for the user

**Views the triage reasoner supports:**
- **Blockers** — requires immediate attention regardless of everything else
- **Today's agenda** — what active projects need today to stay on track
- **Daily maintenance** — recurring care tasks (watering, checking, light pruning)
- **Backlog** — things to do when time/energy is available; tasks whose windows are quietly approaching float up

---

### 6.4 Reactive Monitoring

**Trigger:** Scheduled (daily weather check), or event-driven (pest alert in area).
**Output:** Urgency upgrades on existing tasks, or new emergency tasks. May trigger project iterations.

**Nodes:**
- `weather_monitor` — fetches forecast from Open-Meteo; identifies frost events, heat waves, heavy rain
- `pest_alert_checker` — queries iNaturalist for pest species observations within radius of user location
- `vulnerability_assessor` — cross-references alert type against active projects and plant inventory to determine which projects/plants are affected
- `alert_generator` — creates actionable recommendations; upgrades task urgency where appropriate
- `iteration_trigger` — if response requires plan amendment, triggers the iterating sub-workflow on affected projects

**Alert urgency by project status:**
- `active` project with tender seedlings + frost warning → **blocker**
- `maintaining` project with established natives + frost warning → **FYI / informational**

---

## 7. Data Model

### Data ownership map

Every field has an explicit owner (who writes it) and consumers (who reads it). Fields with no writer or no reader are design gaps.

| Field | Written by | Read by |
|---|---|---|
| `garden_profile` | Garden Profiling | All workflows |
| `plant_inventory` | Garden Profiling | Plant advisory, Reactive Monitoring |
| `project.approved_plan` | Planning | Task Creation, Iterating |
| `project.tasks` | Task Creation | Task Management, Reactive Monitoring |
| `project.seed_schedule` | Task Creation | Task Management |
| `project.iterations` | Iterating | Planning (for context), Task Management |
| `project.status` | Planning, Iterating | Reactive Monitoring (alert urgency), Task Management |
| `task.urgency` | Task Creation, Reactive Monitoring | Task Management |
| `task.what_happens_if_skipped` | Task Creation (LLM-generated) | Task Management (triage) |
| `session_context` | Task Management (inferred) | Task Management (triage) |
| `weather_alerts` | Reactive Monitoring | Iterating (trigger), Task Management |

### Persistence model (outline — detail TBD)

- **Long-term memory (database):** `GardenProfile`, `PlantInventory`, all `GardeningProject` records including tasks and seed schedules
- **Short-term memory (in-session state):** `SessionContext`, `negotiation_history` for the current planning session, active conversation messages
- **Derived/cached state:** `seed_schedule` (derivable from plant list + frost dates, stored for performance); must be invalidated if plant list or frost dates change

---

## 8. Tools and External Resources

### External APIs

| Service | Purpose | Notes |
|---|---|---|
| Open-Meteo | Weather forecast + frost dates | Free, no API key required |
| Perenual API | Structured plant data (sun, water, toxicity, growth habit) | Cache results locally after first fetch |
| iNaturalist API | Recent pest/species observations by location | Query by radius around user |
| USDA PLANTS | Climate zone data, native plant info | Stable reference data |

### Built-in capabilities

| Capability | Purpose |
|---|---|
| Gemini vision | Plant ID from photos, pest identification, garden layout assessment |
| Web search | Current plant availability and pricing, Bay Area growing guides, novel pest situations |

### RAG / Vector Database

**Technology:** Postgres with pgvector extension

pgvector adds a vector column type and approximate nearest-neighbor search directly to Postgres. This means structured data (garden profile, projects, tasks) and embeddings live in the same database — one persistence layer to run, back up, and reason about.

**Why not ChromaDB:** ChromaDB is a common tutorial recommendation but introduces a second database alongside Postgres, requiring two persistence layers, two backup strategies, and application-level joins between vector results and relational data. At the corpus size this system needs (a few thousand documents), pgvector's performance is equivalent and the operational simplicity is worth more.

**Setup:**
```sql
CREATE EXTENSION vector;

CREATE TABLE knowledge_base (
    id uuid PRIMARY KEY,
    category text,           -- 'companion_planting', 'pest_management', etc.
    tags text[],             -- e.g. ['zone_9b', 'organic', 'tomatoes']
    content text,
    embedding vector(1536)   -- dimension depends on embedding model
);
```

**Content worth embedding (highest value):**
- Companion planting relationships (which plants help or harm each other)
- Bay Area / zone 9b specific growing guides
- Organic pest management techniques
- Propagation guides by species (when and how to take cuttings)

**When to use RAG vs. other sources:**
- RAG: companion planting, organic treatments, zone-specific advice (curated knowledge, more reliable than web search)
- Plant database (Perenual): structured facts about a specific plant (sun requirements, days to germination, toxicity)
- Web search: current availability, pricing, novel or emerging pest situations, anything that changes over time

---

## 9. Design Decisions

These are decisions we've made and the reasoning behind them, recorded so we don't revisit them accidentally.

### D1: Projects as the central organizing unit

**Decision:** Plant advisory and seed planning are not standalone top-level workflows. They are sub-workflows of a project.

**Reasoning:** Without a project container, plant advisory and seed planning are stateless — they can't accumulate decisions, revisions, or context over time. A project gives them a persistent home, a scope boundary (which resources are allocated), and a natural lifecycle.

---

### D2: `maintaining` as a distinct project status

**Decision:** Add `maintaining` between `active` and `complete` in the project lifecycle.

**Reasoning:** For perennial plantings, the work doesn't end when plants are established — it shifts to a lighter steady-state cadence. `maintaining` correctly models this and changes the agent's behavior: lighter task generation, different iteration triggers, lower-urgency alerts.

---

### D3: Task priority is not stored — it is computed at triage time

**Decision:** Remove `priority` and `consequence` enum fields from `Task`. Instead, store factual consequence metadata as free text (`what_happens_if_skipped`, `what_happens_if_delayed`) and have the triage node reason over them given session context.

**Reasoning:** Priority is a function of context, not an intrinsic property of a task. A static enum can't capture the user's current situation, energy level, and the tradeoff between competing objectives (minimize immediate loss vs. maintain gardening velocity). The LLM should reason over tradeoffs at query time and can generate new consequence framings on the fly for situations the enum doesn't cover.

**What we do store:** `reversible: bool` — this is stable enough to be a stored field because irreversible consequences nearly always outrank reversible ones when urgency is otherwise equal.

---

### D4: Two independent task dimensions (type × urgency)

**Decision:** Tasks have two orthogonal classification axes — `type` (emergency, milestone, maintenance, opportunistic) and `urgency` (blocker, time_sensitive, scheduled, backlog).

**Reasoning:** A single priority scale conflates what kind of work something is with how time-sensitive it is. A maintenance task can be a blocker (water in a heatwave). A milestone task can be backlog (prep the bed when you have time). Keeping them separate allows correct views: the "daily maintenance" view filters on type, the "blockers" view filters on urgency.

---

### D5: Resource allocation is agent-negotiated

**Decision:** When a new project conflicts with an existing one over tray slots or bed space, the agent surfaces the conflict during planning and helps the user resolve it — rather than first-come-first-served or user-prioritized allocation.

**Reasoning:** Resource conflicts are exactly the kind of complex tradeoff this agent exists to help with. Surfacing them explicitly ("you only have 2 free tray slots, but this project needs 4") and negotiating a resolution is the most useful behavior. It also teaches the user to think about their resource constraints across the full season.

---

### D6: Consequences are LLM-generated at task creation time, not at triage time

**Decision:** `what_happens_if_skipped` and `what_happens_if_delayed` are generated by the LLM when a task is created and stored as free text.

**Reasoning:** These are factual descriptions of outcomes, not evaluations. They don't depend on the user's current context, so they can be generated once and stored. The evaluation of whether one consequence outweighs another is what happens at triage time — that is context-dependent and should not be stored.

---

## 10. Open Design Problems

These are unresolved questions that need answers before or during implementation.

### O1: Global state object design [BLOCKER]

We have `GardeningProject` and `GardenProfile` defined, but we haven't fully defined `GardenState` — the top-level LangGraph state object that is passed between nodes.

Questions to resolve:
- How are projects indexed within state? (by ID? as a list?)
- How does the agent know which project is currently active in a session?
- How is the `SessionContext` represented in state?
- Which fields live in the LangGraph state object vs. in the external database?

---

### O2: Persistence and memory architecture [BLOCKER]

We've described what needs to persist but haven't designed the actual persistence layer.

Questions to resolve:
- What database? (SQLite for local simplicity? Postgres? Something else?)
- How does the agent load garden context at session start — does it load everything, or lazy-load on demand?
- LangGraph's checkpointing system (for human-in-the-loop and crash recovery) — how does this interact with our own persistence layer?
- How do we handle stale derived state? (e.g. seed schedule needs regeneration if frost dates change)

---

### O3: Human-in-the-loop interrupt pattern [BLOCKER for planning workflow]

We've referenced LangGraph interrupts several times (the negotiation loop, iteration approval) but haven't designed the implementation.

Questions to resolve:
- How does a LangGraph interrupt work in practice for a chat-based agent?
- How is the pending proposal stored while waiting for user response?
- What happens if the user ignores the proposal and asks about something else?
- How do we resume the interrupted workflow when the user responds?

---

### O4: RAG content sourcing and maintenance

We've identified what to embed but not where the content comes from or how it's kept current.

Questions to resolve:
- What are the actual sources for companion planting and Bay Area growing guides?
- How is the vector DB populated initially? (manual curation, scraping, both?)
- How is it updated when information changes?
- What's the retrieval strategy — dense retrieval only, or hybrid with keyword search?

---

### O5: Session context intake UX

We've defined `SessionContext` but not how the agent elicits it.

Questions to resolve:
- Does the agent always ask at session start, or only when it needs to triage?
- How much can be reliably inferred from casual conversation vs. needing explicit input?
- What's the fallback when no context is provided?

---

### O6: Graph topology for each workflow

We have the conceptual workflows but haven't drawn the actual node/edge maps that translate directly to LangGraph code.

This is needed before writing any implementation. Each workflow needs a complete diagram with all nodes, conditional edges, and interrupt points specified.

---

### O7: Multi-project tray slot conflict resolution UX

When the user tries to create a project that needs more tray slots than are available, the agent needs to surface a conflict and help resolve it. The UX for this negotiation hasn't been designed.

Questions to resolve:
- Does the agent block the project creation, or allow planning to proceed with a warning?
- What resolution options does it offer? (delay start date, reduce varieties, use outdoor trays, pause another project)
- How does this interact with the negotiation loop — is it a separate step before proposals are generated, or integrated into the proposal generation?

---

## 11. Build Order and Immediate Blockers

### Blockers (must resolve before writing code)

1. **O1 — Global state object** and **O2 — Persistence architecture** must be designed together. Every workflow reads from and writes to shared state, and until the state schema is settled, no nodes can be written.

2. **O3 — Human-in-the-loop interrupt pattern** must be understood before implementing the planning workflow, which is the core of the system.

### Recommended build sequence

Each stage produces something genuinely usable before moving to the next.

**Stage 1 — Foundation (resolve blockers first)**
- Design `GardenState` and persistence layer
- Prototype LangGraph interrupt pattern with a minimal example
- Implement Garden Profiling workflow (teaches multi-turn conversation + state persistence)

**Stage 2 — Core planning loop**
- Implement Project Management: Planning sub-workflow (negotiation loop with hard constraint checking)
- Implement Task Creation sub-workflow (seed schedule generation, two-step transplant events)
- At this point the agent can help plan a project end-to-end

**Stage 3 — Daily use**
- Implement Task Management with triage reasoner
- Implement calendar-based urgency escalation
- At this point the agent is genuinely useful day-to-day

**Stage 4 — Iteration and adaptation**
- Implement Project Management: Iterating sub-workflow
- Integrate RAG for companion planting and organic pest management

**Stage 5 — Proactive intelligence**
- Implement Reactive Monitoring (weather + pest alerts)
- Wire up iNaturalist and Open-Meteo integrations
- At this point the agent is proactive, not just reactive

---

*End of document. Next session: resolve O1 (global state) and O2 (persistence architecture).*