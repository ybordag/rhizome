# Rhizome — Claude Code Memory

## Branch
Active development is on `geranium`. `main` is behind by one major phase — do not treat it as current or merge until intentionally reconciled.

## Build and test
```
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest                      # full suite
python -m pytest -m unit              # fast unit tests only
python -m pytest -m integration       # database-backed tests
python -m pytest -m graph             # graph and orchestration tests
```
Requires `GOOGLE_API_KEY` in `.env` to run the CLI. Tests mock the model and run without a key. `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are in `.env.example` as placeholders — neither is wired yet; they will be in Phase 2 (model provider abstraction).

## Project layout
```
agent/
  graph.py          — LangGraph workflow: session_context_intake →
                      weather_context_loader → triage_reasoner → llm_call →
                      {interaction_node | tool_node | END}
  model.py          — the single model seam (see invariants)
  nodes.py          — graph node implementations. confirmation_node is dead
                      code (alias for interaction_node, not in graph) — do not
                      add it to the graph; remove it
  tools/            — 72 tools organized by domain; all registered in
                      tools/__init__.py
  telemetry.py      — OTel + observer framework; wired into llm_call,
                      tool_node, triage_reasoner, and interaction_node
  triage.py         — triage snapshot builder; makes a secondary LLM call at
                      every session start
  planner.py        — project planning and cost estimation
  tracker.py        — task generation and lifecycle
  care.py           — care event propagation from task completion to plants
  weather.py        — Open-Meteo integration and impact derivation
  incidents.py      — incident and treatment plan logic
  interactions.py   — interaction envelope and record management
  activity_log.py   — change event recording

db/
  models.py         — SQLAlchemy models. Core lifecycle:
                      GardenProfile → GardeningProject → ProjectBrief →
                      ProjectProposal → ProjectRevision →
                      ProjectExecutionSpec → TaskGenerationRun → Task
  database.py       — SQLite session/engine. Migration to Postgres is a
                      prerequisite for multi-instance deployment.
  seed.py           — dev seed data

main.py             — CLI entrypoint
```

## Current state
Phases 1–5 complete: activity log, project planner, task tracker, operational triage + weather context, structured interaction layer and CLI simulation. 72 tools, full project planning lifecycle, human-in-the-loop interrupt/resume, weather-aware triage.

**Phase 0 — complete.** Model factory, datetime cleanup, telemetry wiring, history bug, README.

**Known issues (not yet fixed):**
- `user_id == 1` hardcoded in ~15 files across `agent/nodes.py` and `agent/tools/` — Phase 1 work
- `ActivityEvent.revision_id` has no ForeignKey or index (all other revision refs do)
- `confirmation_node` in `nodes.py` is dead code (alias for `interaction_node`, not in the graph) — safe to delete

**Current focus — Phase 1: multi-tenancy**
- Thread `user_id` from `graph.config["configurable"]["user_id"]` into thread_id and every tool query
- Remove all `user_id == 1` literals (~15 files)
- Owner-scope all single-entity lookups (currently some filter by `id` alone)
- Add auth layer (Supabase recommended: Postgres + auth + object storage in one)

**Phase 2 (after Phase 1):**
- Extend model factory to support Gemini / Claude / OpenAI / local OpenAI-compatible endpoint
- One env-var switch selects the provider; graph never knows the difference
- Enables routing through Fairlead's local inference endpoint

## Invariants — never violate
- **Model access only through `agent/model.py`.** Never instantiate a model client directly or at import time anywhere else in the codebase.
- **No hardcoded user identity.** Never write `user_id == 1` or any literal user identity. User identity flows from `graph.config["configurable"]["user_id"]`.
- **Every DB query on user-owned data must be scoped to the owning user.** Filtering by entity `id` alone is a bug.
- **Untrusted content writes go through `interaction_node`.** Any tool writing data derived from external sources (image analysis, Drive import, web retrieval) must create an interaction envelope and wait for user confirmation before persisting.
- **Never call `datetime.utcnow()`.** Use `datetime.now(timezone.utc).replace(tzinfo=None)` for any datetime stored in or compared with DB columns (which are naive UTC until the Postgres `DateTime(timezone=True)` migration). For non-DB use, plain `datetime.now(timezone.utc)` is fine.
- **Tests required for every new feature.** `python -m pytest` must be green before any task is done.

## Postgres migration notes
`requirements.txt` already includes `psycopg2-binary` and `pgvector`. When migrating:
- Swap `langgraph-checkpoint-sqlite` → `langgraph-checkpoint-postgres` in requirements
- Update `db/database.py` engine and session factory
- LangGraph's Postgres checkpointer is a drop-in for SqliteSaver
- Run Postgres with streaming replication for HA (Patroni or pg_auto_failover)
- This migration is a prerequisite for running multiple agent instances
