# Rhizome Roadmap

## How we work

Work is organised into **tracks** — thematic areas that can progress in parallel. Each active initiative gets a named branch and a doc in `docs/current_work/`. Completed initiative docs move to `docs/archive/`.

---

## Platform

Infrastructure that everything else depends on.

| Initiative | Status | Scope |
|---|---|---|
| FastAPI internal layer | **complete** (narcissus → main) | `/internal/agent` (LangGraph) + `/internal/data/...` (~80 endpoints); SSE streaming; `server.py` entry point |
| Thread management | **complete** (narcissus) | `Thread` model; botanical name generation in Cambium; conversation list, history, delete endpoints |
| Cambium proxy + full API | **complete** (phloem + periderm → main) | Cambium Phases 1–4: auth, key management, proxy, all ~95 routes wired |
| Multi-tenancy | pending | Audit all tool queries to confirm `user_id` scoping; harden against any remaining hardcoded `1` |
| k3s deployment | pending | Thor + Loki cluster setup, Helm for Postgres, raw manifests for Rhizome/Cambium/Verdant |

---

## Intelligence

Capabilities that make the agent smarter and better grounded.

| Initiative | Status | Scope |
|---|---|---|
| Google Search grounding | pending | Live search for planning queries — grounds proposals in current information rather than training data |
| RAG / knowledge base | pending | pgvector embeddings over plant care guides, pest/disease references, seed databases |
| Full-text search | pending | Postgres `tsvector` across plants, tasks, projects, activity; `GET /api/v1/search` |
| iNaturalist | pending | Local species/pest observation data via public API; feeds sighting catalog and reactive monitoring |

See [Intelligence initiative plan](initiatives/intelligence.md) for design detail.

---

## Sensing

Background monitoring and environmental awareness.

| Initiative | Status | Scope |
|---|---|---|
| Reactive monitoring (calendula) phases 1–4 | **complete** | Weather auto-apply, working window alerts, session-start delivery, triage + series jobs |
| Visual garden understanding | pending | MediaAsset + GardenSighting models; plant ID, pest/sighting catalog, space assessment, sun audit from photos |
| iNaturalist pest monitoring | pending | Background `pest_job()` — cross-reference local observations against active projects; best built after visual garden understanding |

See [calendula plan](../current_work/calendula_reactive_monitoring.md) and [visual garden plan](initiatives/visual_garden_understanding.md).

---

## Onboarding

| Initiative | Status | Scope |
|---|---|---|
| Google Drive integration | pending | MCP sidecar; import images from Drive into MediaAsset store |
| Chat import | pending | Parse exported AI chat histories → extract garden profile + project context → `interaction_node` confirmation |

See [Onboarding and data import plan](initiatives/onboarding_and_data_import.md).

---

## Frontend

| Initiative | Status | Scope |
|---|---|---|
| Verdant | not started | React app — dashboard, alert banners, task list, project view, chat interface, conversation history |

See [Verdant initiative plan](initiatives/app_frontend_experience.md).

---

## Routing

| Initiative | Status | Scope |
|---|---|---|
| Fairlead + vLLM | **in progress** (Phases 1–4 on main, Phase 5 pending) | Inference router (Rust), vLLM on Loki GPU, fallback chain (local → cloud) |

See [Fairlead design doc](../../../fairlead/design.md).

---

## Dependency map

```
FastAPI internal layer ──┐
Thread management        │
Multi-tenancy            ├──► Verdant (frontend)
Cambium full API ────────┘

Google Search ──────────────┐
RAG ────────────────────────┼──► Richer planning, care recommendations, incident analysis
Full-text search ───────────┤
iNaturalist ────────────────┘

Visual garden understanding (MediaAsset + GardenSighting)
    ├──► iNaturalist pest monitoring (photo + local data = stronger ID)
    ├──► Image-grounded incident reports
    └──► Space/sun data improves project planning

Google Drive ──► Chat import ──► faster onboarding for new users

Fairlead ──► vLLM local inference ──► cost-free local operation on Sparks
```
