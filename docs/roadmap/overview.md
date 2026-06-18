# Roadmap

**Last updated:** 2026-06

---

## What's been built

Phases 1–5 are complete. The full planning-to-execution loop works end-to-end in the CLI.

| Phase | What it delivered |
|---|---|
| Phase 1 | Activity log foundation |
| Phase 2 | Project planner (brief → proposal → revision → execution spec) |
| Phase 3 | Task tracker (generation, dependencies, recurrence, lifecycle) |
| Phase 4 | Operational triage, weather integration, reactive care |
| Phase 5 | Structured interaction system (approvals, confirmations, LangGraph interrupt/resume) |
| API readiness (2026-06) | 93 tools, task priority scoring, daily work list, action history, N+1 fixes, 310 tests |

---

## What's active now

**Cambium** — Go API gateway (separate repo). Phases:
1. Project skeleton — Go module, HTTP server, Postgres connection, users + refresh_tokens tables
2. Auth endpoints — `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, JWT middleware
3. Rhizome proxy — HTTP client to Rhizome internal API, JWT → user_id injection
4. Full API surface — all `/api/v1` endpoints proxied from the backing tools

**Rhizome FastAPI internal interface** — small FastAPI layer that Cambium calls. Starts when Cambium Phase 3 begins.

**Postgres migration** — prerequisite for: multi-instance deployment, proper FK enforcement, multi-tenancy at scale.

---

## What's next (sequenced)

| Priority | Work | Blocked by |
|---|---|---|
| 1 | Cambium Phases 1–4 | Nothing |
| 2 | Rhizome FastAPI internal interface | Cambium Phase 3 |
| 3 | Postgres migration | — |
| 4 | Multi-tenancy: thread user_id through all tools | Cambium providing JWT user_id |
| 5 | Verdant (React frontend, Epic 9) | Cambium Phase 2 (auth) stable |
| 6 | Model provider abstraction (env-var switch) | Nothing |
| 7 | Epic 2: Visual garden understanding | Media upload API (Cambium Phase 4) |
| 8 | Epic 6: Reactive monitoring and alerting | Background job infrastructure |
| 9 | Epic 3: Planning negotiation enhancements | Nothing |
| 10 | Epic 8: External knowledge retrieval | — |

---

## Epic inventory

The long-term product is organized around epics. Each epic is a product capability area.

### Epic 1: Garden Profiling and Spatial Modeling
**Status:** Partial — foundation exists  
Structured beds, containers, plants, care history. Missing: guided profiling workflow, richer spatial layout reasoning.

### Epic 2: Visual Garden Understanding
**Status:** Not started  
Image upload, plant identification from photos, pest/disease visual recognition, layout estimation. **Depends on:** media upload API (Epic 9 completion). See [epic_02_visual_garden_understanding.md](epics/epic_02_visual_garden_understanding.md).

### Epic 3: Project Planning and Negotiation
**Status:** Strong foundation  
Brief → proposal → revision → tasks exists. Missing: richer negotiation loop, stronger hard-constraint checking, proposal comparison UX.

### Epic 4: Task Creation and Execution Tracking
**Status:** Mostly complete  
Task generation, dependencies, recurrence, lifecycle, priority scoring, daily work list, cascade defer. The core task system is solid.

### Epic 5: Daily Triage and Operational Guidance
**Status:** Mostly complete  
Session-start triage snapshot, weather-aware task surfacing, urgency tiers, daily priority scoring endpoint.

### Epic 6: Reactive Monitoring and Alerting
**Status:** Partial — weather foundation exists  
Weather snapshots and approval-gated task adjustments exist. Missing: scheduled weather refresh, external alert ingestion (iNaturalist), proactive background monitoring. **Partially blocked by:** background job infrastructure. See [epic_06_reactive_monitoring_and_alerting.md](epics/epic_06_reactive_monitoring_and_alerting.md).

### Epic 7: Iteration and Amendments
**Status:** Not started as first-class workflow  
Plan revision, impact assessment, amendment generation. Foundations exist (revisions, supersession, interactions). **Blocked by:** stronger Epic 3 planning negotiation.

### Epic 8: Knowledge and External Retrieval
**Status:** Mostly not started  
Plant data (Perenual), pest observations (iNaturalist), web search, curated gardening knowledge, RAG. Open-Meteo already integrated.

### Epic 9: App-Facing Interaction and Frontend Experience
**Status:** Backend API complete; Cambium in progress; Verdant not started  
Backend has 93 tools covering all planned endpoints. Cambium (the Go gateway) is being built now. Verdant (React frontend) starts after Cambium auth is stable. See [epic_09_app_frontend_experience.md](epics/epic_09_app_frontend_experience.md).

### Epic 10: Garden Operations Expansion
**Status:** Not started  
Tool/resource inventory, cost tracking, harvest tracking, richer care/treatment coverage.

### Epic 11: Platform Hardening and Scale
**Status:** Not started in a focused way  
Richer observability, background workers, scheduled operations, stronger automation, Postgres migration (this one is actually underway).

---

## Dependency graph

```
E1 (Garden Profiling) ──────────────► E2 (Visual Understanding)
E1 ─────────────────────────────────► E3 (Planning & Negotiation)
E3 ──► E4 (Task Tracking) ──────────► E5 (Daily Triage)
E4 ─────────────────────────────────► E6 (Reactive Monitoring)
E3, E4, E6 ─────────────────────────► E7 (Iteration & Amendments)
E8 (Knowledge) ─────────────────────► E2, E3, E6
E9 (App / Frontend) ────────────────► E2, E3, E5
E10 (Ops Expansion) ────────────────► E3, E5, E7
E11 (Platform Hardening) ───────────► E6, E8, E9
```

---

## Roadmap principles

1. **Build on the completed core** — the planning-to-execution loop is solid. Avoid reopening foundations without a clear product need.
2. **Organize around epics** — every piece of work maps to a product capability area.
3. **Prefer end-to-end user loops** — features should improve the full loop: project → plan → tasks → triage → action → history → revision.
4. **Design for the app even when testing in the CLI** — the CLI is a simulation surface, not the final product.
5. **Make dependencies explicit** — sequence work by what enables what, not by enthusiasm.
