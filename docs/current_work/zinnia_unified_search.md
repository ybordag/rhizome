# Zinnia — Unified Entity Search

Branch: `zinnia`  
Issues: [rhizome#126](https://github.com/ybordag/rhizome/issues/126), [cambium#16](https://github.com/ybordag/cambium/issues/16)  
Roadmap: Intelligence track — Full-text search (Phase 2)

## Scope

Delivers two things at once:

1. **Issue #126** — `GET /api/v1/search` endpoint for the Verdant Pages context-pin modal: structured results across all six entity types, ILIKE on label fields, UUID shortcut, `types` + `limit` params.
2. **Intelligence roadmap Phase 2** — `tsvector` generated columns + GIN indexes on notes/description fields; `search_domain()` agent tool for free-text corpus search within a session.

The endpoint satisfies the frontend. The tsvector columns + agent tool satisfy the roadmap. Same implementation, two consumers.

---

## Parts

### Part 1 — Alembic migration: tsvector columns + GIN indexes ✅ in progress

Add `search_vector tsvector GENERATED ALWAYS AS (...) STORED` and a GIN index to each searchable table. Fields covered per table:

| Table | tsvector fields |
|---|---|
| `plant` | name, variety, notes, special_instructions, care_state_notes |
| `bed` | name, location, notes, care_state_notes |
| `container` | name, container_type, location, notes, care_state_notes |
| `task` | title, description, notes |
| `gardening_project` | name, notes |
| `incident_report` | incident_type, summary, notes |

Migration is Postgres-only (Alembic never runs on SQLite). Downgrade drops the columns and indexes.

---

### Part 2 — Domain layer: `agent/domain/search.py`

New `search_entities(session, user_id, query, types, limit_per_type)` function. One query per entity type; results merged and returned as a flat list of typed dicts.

**Per-type query logic:**
- ILIKE on label fields (matches #126 spec; works in SQLite for tests)
- If `q` is a valid UUID, try exact ID lookup first before ILIKE fallback
- Status exclusions: skip `removed` plants, `done`/`superseded` tasks, `complete` projects, `resolved` incidents

**User scoping:**
- plant, bed, container, task: direct `user_id` column
- gardening_project: direct `user_id` column
- incident_report: join through `gardening_project.user_id` (project-linked) OR through `incident_subject → plant/bed/container` (subject-linked)

**Result shape per entity:**

| Type | `label` | `secondary_label` | `summary` |
|---|---|---|---|
| plant | name (+ variety) | bed/container name · status | last care action |
| bed | name | location | active plant count |
| container | name | type · location | active plant count |
| task | title | project name · status | due date |
| project | name | status | open task count |
| incident | incident_type · summary (truncated) | severity · status | first affected subject |

Returns `{"results": [...], "by_type": {"plant": n, ...}}` matching the #126 response spec.

---

### Part 3 — Agent tool: `search_domain()`

New tool in `agent/tools/operations/search.py`. Calls `search_entities` and formats results as a readable string block for agent context. Registered in `tools/__init__.py`.

The agent tool is the roadmap Intelligence Phase 2 delivery — lets the agent search across the user's full corpus during planning and triage, not just fetch individual known records.

---

### Part 4 — API endpoint: `GET /api/v1/search`

New route in `agent/api/routers.py`. `SearchResultItemView` + `SearchResultsView` Pydantic models in `views.py`.

Query params: `q` (required), `types` (comma-separated, optional), `limit` (int, default 5, max 20).

Returns:
```json
{
  "results": [{ "subject_type", "subject_id", "label", "secondary_label", "summary" }],
  "by_type": { "plant": 0, "bed": 0, ... }
}
```

The existing `GET /api/v1/garden/search` endpoint stays — it's already wired in Cambium and has different semantics (name-only, returns full garden objects).

---

### Part 5 — Tests

`tests/tools/operations/test_search.py`:
- One test per entity type: ILIKE match, status exclusion, out-of-scope user isolation
- UUID exact-match shortcut
- Multi-type combined query; `types` filter; `limit` per type
- Empty query → 400 validation error
- API endpoint coverage via `TestClient`

---

## Cambium (post-merge)

Cambium #16 wires:
- `GET /api/v1/search` — pass-through proxy (`q`, `types`, `limit` params, `user_id` from JWT)
- `POST /api/v1/threads/{id}/context` + `DELETE /api/v1/threads/{id}/context/{type}/{id}` (rhizome#127 — separate branch)
