# Rhizome Roadmap

## How we work

Work is organised into **tracks** — thematic areas that can progress in parallel. Each active initiative gets a named branch and a doc in `docs/current_work/`. Completed initiative docs move to `docs/archive/`.

---

## Platform

Infrastructure that everything else depends on.

| Initiative | Status | Scope |
|---|---|---|
| FastAPI internal layer | **in progress** | `/internal/agent` (LangGraph) + `/internal/data/...` (direct CRUD) routers for Cambium |
| Cambium proxy (phloem branch) | **in progress** | Cambium Phase 3 — HTTP client, provider key injection, all `/api/v1` routes |
| Multi-tenancy | pending | Thread real `user_id` from Cambium JWT into all ~15 tool files (currently hardcoded to 1) |
| k3s deployment | pending | Thor + Loki cluster setup, Helm for Postgres, raw manifests for Rhizome/Cambium/Verdant |
| Cambium full API surface | pending | Cambium Phase 4 — all planned endpoints fully wired |

---

## Intelligence

Capabilities that make the agent smarter and better grounded.

| Initiative | Status | Scope |
|---|---|---|
| Google Search grounding | pending | Live search for planning queries — grounds proposals in current information rather than training data |
| RAG / knowledge base | pending | pgvector embeddings over plant care guides, pest/disease references, seed databases |
| Full-text search | pending | Postgres `tsvector` across plants, tasks, projects, activity; `GET /api/v1/search` |

See [Intelligence initiative plan](initiatives/intelligence.md) for design detail.

---

## Sensing

Background monitoring and environmental awareness.

| Initiative | Status | Scope |
|---|---|---|
| Reactive monitoring (calendula) phases 1–4 | **complete** | Weather auto-apply, working window alerts, session-start delivery, triage + series jobs |
| iNaturalist pest monitoring | pending | `pest_job()` querying iNaturalist Observations API near garden location → `IncidentReport` + `MonitorAlert`. Best built after visual garden understanding is in place. |
| Visual garden understanding | pending | Image processing, plant/disease/pest identification from photos, visual growth tracking |

See [calendula plan](../current_work/calendula_reactive_monitoring.md) and [visual garden plan](initiatives/visual_garden_understanding.md).

---

## Frontend

| Initiative | Status | Scope |
|---|---|---|
| Verdant | not started | React app — dashboard, alert banners, task list, project view, chat interface |

See [Verdant initiative plan](initiatives/app_frontend_experience.md).

---

## Routing

| Initiative | Status | Scope |
|---|---|---|
| Fairlead + vLLM | not started | Inference router (Go/Rust), vLLM on Loki GPU, fallback chain (local → cloud) |

See [Fairlead design doc](../../../fairlead/design.md).

---

## Dependency map

```
FastAPI internal layer ──┐
Multi-tenancy            ├──► Cambium full API ──► Verdant
Cambium proxy ───────────┘

Google Search ───────────┐
RAG ─────────────────────┼──► Richer planning, care recommendations, incident analysis
Full-text search ────────┘

Visual garden understanding ──► iNaturalist (full photo integration)
                              └► Image-grounded incident reports

Fairlead ──► vLLM local inference ──► cost-free local operation on Sparks
```
