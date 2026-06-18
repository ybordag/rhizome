# rhizome

The agent and domain engine for a hobby gardening assistant. Rhizome manages garden profiles, project planning, task scheduling, and daily triage through a LangGraph-based agent with persistent memory — acting as an advisor, co-worker, and coach for the hobby gardener.

**Status:** Active development. Core agent loop is functional. Multi-user deployment, frontend API, and image analysis are in progress.

---

## What it does

Gardening is a deceptively complex management task. Even a small garden involves juggling competing constraints across space, soil, sunlight, climate, budget, and time — often seasons in advance. Rhizome holds all of that context and helps a gardener reason through it.

**Currently working:**
- Persistent garden model — beds, containers, plants, care history, activity log
- Project planning with negotiation loop — brief → proposal → revision → approved plan → tasks
- Task generation and lifecycle — deadlines, windows, consequence metadata, recurrence, dependencies
- Daily triage with weather context — urgency-aware task surfacing, session context intake
- Incident and treatment plan workflows
- Weather integration (Open-Meteo) with approval-gated task impact recommendations
- Structured human-in-the-loop interactions — proposals, treatment plans, destructive confirmations
- CLI for manual testing

**In progress / planned:**
- FastAPI layer for frontend consumption
- Multi-user auth and tenancy (Postgres migration required)
- Image analysis — plant identification, pest diagnosis via vision model (MCP sidecar)
- External knowledge retrieval — Perenual plant data, iNaturalist, RAG
- Scheduled weather monitoring and proactive alerting

---

## Architecture

Rhizome is the backend engine in a three-repo system:

| Repo | Role |
|---|---|
| **rhizome** | Agent and domain engine (this repo) |
| **verdant** | React frontend |
| **fairlead** | Resource router — inference routing, agent worker pool, session failover |

Rhizome connects to Fairlead through a standard OpenAI-compatible endpoint configured in `agent/model.py`. The repos are independently deployable.

See [`docs/architecture/overview.md`](docs/architecture/overview.md) for the full architecture.

---

## Tech stack

- **Agent framework:** LangGraph (Python)
- **LLM:** Gemini via `langchain-google-genai`; multi-provider abstraction in progress
- **Database:** SQLite (current) → Postgres with pgvector (target)
- **Weather:** Open-Meteo (no API key required)
- **Planned:** Perenual (plant data), iNaturalist (pest observations)

---

## Getting started

```bash
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env        # add your GOOGLE_API_KEY
python main.py              # start the CLI
python -m pytest            # run the test suite
```

---

## License

Apache 2.0
