# Rhizome

Rhizome is an AI-powered gardening assistant built on LangGraph. It acts as an **advisor, co-worker, and coach** for the hobby gardener — holding persistent knowledge of your specific garden, helping plan projects from seed to harvest, generating time-sensitive task schedules, surfacing daily priorities based on weather and deadlines, and tracking what happens over time.

**Status:** Active development on `verbena` branch. Core agent loop is fully functional with 94 tools and 850+ non-live tests. API gateway ([Cambium](../cambium)) is active; frontend ([Verdant](../verdant-pages)) is not yet started.

---

## The problem it solves

Gardening is deceptively complex. Even a small garden involves constraints across space, soil, sunlight, climate, budget, pests, and timing — often sequenced months in advance. A single planning decision cascades: which plants you grow affects seed start timelines, which affects tray space, which affects project schedules, which affects cost.

Most tools treat gardening as a to-do list. Rhizome treats it as a planning and reasoning problem. It maintains a persistent model of your specific garden — beds, containers, plants, care history, projects, proposals, tasks — and reasons over all of it simultaneously.

---

## Key capabilities

**Garden model**
- Persistent beds, containers, and plants with full care history
- Activity log on every object — every watering, fertilization, transplant, inspection
- Garden profile with climate zone, frost dates, tray capacity, location

**Project planning**
- Guided planning: brief → proposal with cost/timeline/effort estimates → approved plan
- Feasibility checking: budget caps, timeline constraints, location conflicts
- Schedule preview before committing to a plan

**Task management**
- Auto-generated task graphs from approved plans (milestones, series, dependencies)
- Event-anchored scheduling (tasks that wait for plant_germinated, plant_transplanted)
- Recurring task series with rolling 14-day materialization
- Daily priority scoring across urgency, task type, user priority, and triage alignment
- Task lifecycle: start / complete / skip / defer (with cascade to dependents)

**Daily triage**
- Session-start triage snapshot with weather context
- Urgency tiering: blocker / time_sensitive / scheduled / backlog
- `GET /api/v1/tasks/daily` — deterministic ranked work list

**Weather**
- Open-Meteo integration (no API key required)
- Derived impacts: frost, heat, heavy rain, storm, good planting windows
- Approval-gated task adjustments when weather changes the schedule

**Incidents and treatment**
- User-reported pest, blight, and weed incidents
- Agent-drafted treatment plans with approval gate
- Treatment tasks auto-generated on approval

**Human-in-the-loop interactions**
- Structured approval flows: proposals, treatment plans, weather changes, destructive ops
- LangGraph interrupt/resume — pauses mid-graph for user input, resumes exactly where it left off
- Every interaction resolution recorded in the activity log

**Action history**
- Complete activity timeline for any object: plant, task, bed, project, incident
- Cross-object project timeline with category/event-type filtering and cursor pagination
- User decisions (approvals, cancellations) appear in the timeline

---

## System context

Rhizome is one part of a four-repo system:

```
Verdant (React)
    │  /api/v1
    ▼
Cambium (Go)  ←— JWT auth, bcrypt, refresh tokens
    │  /internal/...  { user_id }
    ▼
Rhizome (Python + LangGraph)  ←— this repo
    │
    ▼
Fairlead (inference router)  ←— GPU routing, provider failover
```

| Repo | Role |
|---|---|
| **rhizome** | Agent engine, domain logic, DB, internal HTTP API |
| **[cambium](../cambium)** | Go API gateway — JWT auth, `/api/v1` proxy |
| **verdant** | React frontend |
| **fairlead** | Inference router — GPU resource accounting, LLM failover |

---

## Tech stack

| Layer | Technology |
|---|---|
| Agent framework | LangGraph (Python) |
| LLM | Google Gemini via `langchain-google-genai` |
| Database | SQLite → Postgres (migration path in place) |
| Weather | Open-Meteo (free, no key required) |
| Observability | OpenTelemetry (OTel) |
| Tests | pytest, 850+ non-live tests |

---

## Getting started

```bash
# Clone and install (use the RHIZOME_ENV conda environment)
conda activate RHIZOME_ENV
pip install -r requirements.txt -r requirements-dev.txt

# Configure
cp .env.example .env
# Add your GOOGLE_API_KEY to .env

# Run the CLI
python main.py

# Run the test suite
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest
```

See [docs/getting-started/setup.md](docs/getting-started/setup.md) for full setup instructions.

---

## Documentation

| Document | What it covers |
|---|---|
| [Vision and Design](docs/overview/vision-and-design.md) | Why Rhizome exists, design philosophy, interaction surface |
| [Features](docs/overview/features.md) | Complete capability inventory |
| [Setup Guide](docs/getting-started/setup.md) | Installation, configuration, first run |
| [Using the CLI](docs/getting-started/using-the-cli.md) | How to have a session with the agent |
| [System Architecture](docs/architecture/system-overview.md) | Repos, runtime topology, deployment model |
| [Agent Loop](docs/architecture/agent-loop.md) | End-to-end walkthrough of one session |
| [Data Model](docs/architecture/data-model.md) | All models, lifecycle, relationships |
| [API Reference](docs/architecture/api-reference.md) | Complete `/api/v1` endpoint reference |
| [Tools Reference](docs/architecture/tools-reference.md) | All 94 tools organized by domain |
| [Code Organization](docs/development/code-organization.md) | Directory guide, module responsibilities |
| [Testing Guide](docs/development/testing.md) | Test structure, patterns, how to add tests |
| [Roadmap](docs/roadmap/overview.md) | Epic inventory, current status, what's next |
| [CLAUDE.md](CLAUDE.md) | Claude Code session memory |

---

## License

Apache 2.0
