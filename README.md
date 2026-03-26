# rhizome

The agentic backend for a hobby gardening assistant. Rhizome manages garden profiles, project planning, seed scheduling, and task prioritization through a LangGraph-based multi-workflow agent with persistent memory — acting as an advisor, co-worker, and coach for the hobby gardener.

> **Status:** Early design phase — architecture and data model are being defined. No runnable code yet.

---

## What it does

Gardening is a deceptively complex management task. Even a small garden involves juggling competing constraints across space, soil, sunlight, climate, budget, and time — often seasons in advance. Rhizome is designed to hold all of that context and help a gardener reason through it.

Concretely, it will:

- Build and maintain a persistent model of your garden — beds, containers, sunlight zones, existing plants, and constraints
- Help plan and negotiate gardening projects (what to grow, where, when, and how much it will cost) with explicit handling of hard constraints like toxicity, budget, and available space
- Generate seed schedules and transplant timelines, accounting for frost dates, tray capacity, and multi-step transplant processes
- Surface prioritized task recommendations based on what's urgent, what's due today, and what can wait for a free hour
- Monitor weather forecasts and local pest reports and proactively alert when intervention is needed

---

## Architecture

Rhizome is built on [LangGraph](https://github.com/langchain-ai/langgraph) and organized around five top-level workflows:

| Workflow | Description |
|---|---|
| **Garden Profiling** | Onboarding and ongoing updates to the garden layout and plant inventory |
| **Project Management** | Planning, iterating, and task creation for scoped gardening projects |
| **Task Management** | Daily triage and prioritization across all active projects |
| **Reactive Monitoring** | Weather and pest alerts that trigger proactive recommendations |

Projects are the central organizing unit — plant selection and seed scheduling are sub-workflows of a project lifecycle (`planning → active → maintaining → paused → complete`), not standalone features.

For full architecture documentation see [`docs/design.md`](docs/design.md).

---

## Tech stack

- **Agent framework:** LangGraph (Python)
- **LLM:** Gemini (via `langchain-google-genai`)
- **Database:** Postgres with pgvector (structured data + embeddings in one place)
- **External APIs:** Open-Meteo (weather), Perenual (plant data), iNaturalist (pest reports), USDA PLANTS (climate zones)

---

## Project status

This repository is in active design. The current focus is:

- [ ] Global state object and persistence architecture
- [ ] Human-in-the-loop interrupt pattern (needed for the planning negotiation loop)
- [ ] Garden Profiling workflow (first workflow to implement)

See [`docs/design.md`](docs/design.md) for the full design document including open problems and build order.

---

## License

Apache 2.0
