# Code Organization

A guide to every directory and file in the Rhizome codebase. Use this when you need to know where something lives, how modules relate to each other, or how to add something new.

---

## Top-level layout

```
rhizome/
├── agent/          Core agent code — graph, domain logic, tools
├── db/             Database models, session factory, seed data
├── tests/          Test suite (310 tests)
├── docs/           Documentation
├── main.py         CLI entrypoint
├── CLAUDE.md       Claude Code session memory
└── README.md
```

---

## `agent/` — the agent

The agent is split into three layers: `core/` (the LangGraph runtime), `domain/` (business logic), and `tools/` (LLM-callable wrappers).

### `agent/core/` — LangGraph runtime

These files run the graph. They should be changed when the conversation flow, routing logic, or model access needs to change.

| File | Responsibility |
|---|---|
| `graph.py` | Defines and compiles the `StateGraph`. Wires nodes and conditional edges. Exposes the compiled `agent` object imported by `main.py`. |
| `nodes.py` | All node implementations: `session_context_intake`, `weather_context_loader`, `triage_reasoner`, `llm_call`, `interaction_node`, `tool_node`. Also defines `DESTRUCTIVE_TOOLS`, `INTERACTION_REVIEW_TOOLS`, and routing functions (`should_continue`, `should_continue_after_interaction`). |
| `state.py` | `GardenState` TypedDict — the state flowing through the graph. |
| `model.py` | **Single model seam.** All LLM access goes through `get_model()` and `get_triage_model()`. Never instantiate a model client anywhere else. Reads `RHIZOME_MODEL` and `RHIZOME_TRIAGE_MODEL` env vars. |
| `telemetry.py` | OpenTelemetry setup and observer framework. `emit_state_snapshot`, `emit_tool_completed`, `emit_tool_started`, `start_span`. Wired into all node transitions. |
| `temporal.py` | Timezone handling, `build_temporal_context` (day of week, season, frost proximity), `infer_session_context` (available time, energy level from user input). |

### `agent/domain/` — domain logic

These files contain the actual business logic. They're pure Python (no LangChain, no graph concerns) and are tested in `tests/agent/domain/` and `tests/db/`. Tool files call into domain files — not the other way.

| File | Responsibility |
|---|---|
| `activity_log.py` | Event recording helpers: `record_create_event`, `record_update_event`, `record_delete_event`, `record_activity_event`. Query helpers: `get_activity_for_subject`, `list_recent_activity_entries` (with filtering + cursor pagination), `get_activity_for_subject_in_project`. Formatting: `format_activity_feed`. `SNAPSHOT_FIELDS` dict maps model classes to their snapshotted fields. |
| `care.py` | `infer_care_action(task)` — keyword-based inference from task title/description. `_resolve_subjects(session, task)` — resolves linked subjects with name-matching fallback. `apply_task_completion_side_effects` — updates care timestamps and records care events. `CARE_ACTIONS` mapping: action → {subject_type → (event_type, field_name)}. |
| `incidents.py` | `create_incident_report`, `draft_treatment_plan`, `approve_treatment_plan`, `resolve_incident`. `approve_treatment_plan` generates Task objects for each step and records a `treatment_plan_approved` event. |
| `interactions.py` | Interaction envelope builders (`build_confirmation_interaction`, `build_proposal_review_interaction`, etc.), `record_interaction_summary`, `resolve_interaction_record` (now writes `interaction_resolved` activity event), `normalize_resolution` (maps text → InteractionResolution), `InteractionEnvelope`, `InteractionResolution` dataclasses. |
| `planner.py` | `estimate_plan_cost`, `estimate_plan_timeline`, `estimate_plan_effort` — deterministic arithmetic estimators. `check_plan_feasibility` — hard violations + soft warnings. `assemble_planning_context_data`, `get_or_create_brief`. `DEFAULT_PLANT_RULES` dict (tomato, pepper, basil + generic fallback). |
| `tracker.py` | Task generation (`generate_tasks_for_revision`, `_task_blueprints`, `_create_task`, `_create_series`, `_link_dependency`). State machine: `compute_task_blocked_state`, `compute_task_urgency`, `_refresh_task_status_from_dependencies`. Daily priority: `get_daily_priority_tasks`, `format_daily_priority_tasks`. Cascade: `cascade_defer_to_dependents`. Series: `materialize_task_series`, `list_materializable_series`. Constants: `VALID_TASK_STATUSES`, `VALID_TASK_PRIORITIES`, `_URGENCY_SCORE`, `_TYPE_SCORE`, `_PRIORITY_SCORE`. |
| `triage.py` | `build_triage_snapshot` — secondary LLM call that produces the triage snapshot. `format_triage_snapshot` — text formatter for the system prompt. |
| `weather.py` | `refresh_weather_snapshot` — fetches Open-Meteo and derives impacts. `get_latest_weather_snapshot`, `evaluate_weather_task_impacts`, `derive_weather_impacts`. |

### `agent/tools/` — LLM-callable wrappers

Tool files are thin. They: open a `SessionLocal()`, call domain logic, format a result, and return a string. The `@tool` decorator makes them callable by the LLM.

```
agent/tools/
  __init__.py         ← registers all 93 tools, exports `tools` list and `tools_by_name` dict
  garden/
    beds_containers.py
    plants.py
    profile.py
    search.py
  projects/
    planning.py
    projects.py
    tracker.py
  operations/
    activity.py
    care.py
    incidents.py
    interactions.py
    triage.py
    weather.py
```

**Important:** `agent/tools/__init__.py` is the single source of truth for which tools are registered. Adding a tool to a tool file but not to `__init__.py` means the LLM can't see it. Add both.

---

## `db/` — database

| File | Responsibility |
|---|---|
| `models.py` | All SQLAlchemy models. One class = one table. All indexes defined here. |
| `database.py` | `SessionLocal = sessionmaker(bind=engine)`. `current_user_id: ContextVar[int]` — set by `nodes.py` at session start, read by tools. `engine` created from `DATABASE_URL` env var (defaults to SQLite). |
| `seed.py` | Dev seed data — creates a sample garden profile, beds, containers, plants. Run with `python db/seed.py`. |

---

## `tests/` — test suite

```
tests/
  agent/
    core/    ← graph + node tests (test_graph, test_nodes, test_node_edge_cases, test_telemetry)
    domain/  ← domain logic unit tests (test_domain_logic)
  tools/
    garden/      ← test_plants, test_beds_containers, test_profile, test_search
    projects/    ← test_projects, test_planning, test_task_tracker_tools,
                   test_priority_and_progress, test_bulk_assign, test_query_efficiency
    operations/  ← test_triage_care_incident_operations, test_activity, test_interaction_tools,
                   test_status_and_orphans, test_activity_history
  db/
    test_activity_log.py
    test_interactions.py
    test_planner.py
    test_tracker.py
    test_temporal_weather_triage_helpers.py
  support/
    factories.py    ← make_profile(), make_project(), make_task(), etc.
    fakes.py        ← FakeBoundModel (mock LLM), FakeTool, make_ai_message, make_tool_call_message
    patching.py     ← patch_all_sessionlocals(), build_test_agent()
  conftest.py       ← shared fixtures: test_engine, db_session, patched_sessionlocal, etc.
  DEFERRED_TESTS.md ← consciously deferred test areas with rationale
```

See [Testing Guide](testing.md) for patterns and how to add tests.

---

## How to add a new tool

**1. Choose the right file.** Domain logic in `agent/domain/`. Tool wrapper in the appropriate `agent/tools/{garden,projects,operations}/` file.

**2. Write the domain function** (if needed) in `agent/domain/`.

**3. Write the tool wrapper** in the tool file:

```python
@tool
def my_new_tool(required_arg: str, optional_arg: Optional[str] = None) -> str:
    """One-line docstring — this is what the LLM sees to decide when to call the tool."""
    session = SessionLocal()
    try:
        # call domain logic
        result = my_domain_function(session, arg=required_arg)
        session.commit()
        return f"Done: {result.name}"
    except Exception as e:
        session.rollback()
        print(f"[DEBUG] Failed: {e}")
        return f"Failed: {str(e)}"
    finally:
        session.close()
```

**4. Register it in `agent/tools/__init__.py`:**

```python
# In the import block
from agent.tools.projects.projects import (
    ...,
    my_new_tool,
)

# In the tools list
tools = [
    ...,
    my_new_tool,
]
```

**5. Write tests.** See the [Testing Guide](testing.md). At minimum: happy path, not-found error, invalid input.

**6. If it's destructive**, add it to `DESTRUCTIVE_TOOLS` in `agent/core/nodes.py`. If it's a review/approval operation, add it to `INTERACTION_REVIEW_TOOLS`.

---

## Module dependency rules

- `agent/core/` may import from `agent/domain/` ✓
- `agent/core/` may import from `agent/tools/` ✓
- `agent/domain/` may import from `db/` ✓
- `agent/domain/` must NOT import from `agent/core/` or `agent/tools/` ✗
- `agent/tools/` may import from `agent/domain/` ✓
- `agent/tools/` may import from `db/` ✓
- `agent/tools/` must NOT import from `agent/core/` ✗

This keeps domain logic testable in isolation without needing the LangGraph runtime.

---

## Naming conventions

**Tools** — verb_noun pattern, snake_case: `complete_task`, `list_project_proposals`, `get_daily_priority_tasks`.

**Domain functions** — similar: `compute_task_blocked_state`, `apply_task_completion_side_effects`.

**Private domain helpers** — prefix `_`: `_create_task`, `_task_blueprints`, `_normalize_plant`.

**DB models** — PascalCase: `GardeningProject`, `TaskDependency`, `ActivityEvent`.

**Constants** — ALL_CAPS: `VALID_TASK_STATUSES`, `DESTRUCTIVE_TOOLS`, `DEFAULT_ACTOR_TYPE`.

**Test files** — `test_{module_name}.py` in the same subdirectory structure as the source.

**Test functions** — `test_{thing being tested}_{scenario}`: `test_complete_task_rejects_already_done`, `test_list_projects_counts_are_zero_for_empty_project`.
