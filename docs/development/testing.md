# Testing Guide

Rhizome has 850+ non-live tests. This guide explains the test structure, the patterns used throughout, and how to write new tests.

---

## Running tests

```bash
# Local suite (use RHIZOME_ENV; excludes live provider calls)
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m "not live"

# Full suite, including live provider smoke tests
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest

# By marker
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m unit        # fast, no DB required
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m integration # database-backed
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -m graph       # graph + orchestration

# Specific directory
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest tests/tools/projects/

# Specific file
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest tests/tools/operations/test_activity_history.py

# Verbose
/opt/miniconda3/envs/RHIZOME_ENV/bin/python -m pytest -v
```

Non-live tests do **not** require `GOOGLE_API_KEY`. The LLM is mocked outside `@pytest.mark.live` tests.

---

## Markers

| Marker | When to use |
|---|---|
| `@pytest.mark.unit` | Pure Python, no DB, no filesystem. Fast. Use for domain logic, pure functions. |
| `@pytest.mark.integration` | Requires a DB session. Most tool tests are integration tests. |
| `@pytest.mark.graph` | Requires the full LangGraph graph or its nodes. Use for routing, interaction flow, graph orchestration tests. |

---

## Core fixtures (`tests/conftest.py`)

| Fixture | What it provides |
|---|---|
| `test_engine` | Fresh SQLite engine backed by a `tmp_path` file |
| `setup_schema` | Runs `Base.metadata.create_all` on the test engine |
| `session_factory` | `sessionmaker` bound to `test_engine` |
| `db_session` | A single open session for the test; closed after |
| `patched_sessionlocal` | Patches `SessionLocal` in every tool module to use `session_factory` |
| `seed_garden_profile` | Creates a `GardenProfile` via `make_profile(db_session)` |
| `fake_bound_model` | A `FakeBoundModel` with no queued responses |
| `fresh_test_graph` | Compiled LangGraph graph with mocked model and patched sessions |
| `reset_user_id` | (autouse) Resets `current_user_id` to 1 before each test |

---

## The patching pattern

Tools use `SessionLocal()` to create DB sessions. In tests, `patched_sessionlocal` replaces `SessionLocal` in every tool module with a session factory that points at the test DB.

This is done in `tests/support/patching.py`:

```python
def patch_all_sessionlocals(monkeypatch, session_factory) -> None:
    from agent.tools.operations import activity, care, incidents, ...
    from agent.tools.garden import beds_containers, plants, profile, search
    from agent.tools.projects import planning, projects, tracker

    monkeypatch.setattr(projects, "SessionLocal", session_factory)
    monkeypatch.setattr(tracker, "SessionLocal", session_factory)
    # ... etc for all modules
```

**Key implication:** if you write a test that calls a tool, you need the `patched_sessionlocal` fixture. If you only call domain functions directly (not via tools), you don't need it — just pass `db_session` directly.

---

## Factory functions (`tests/support/factories.py`)

Factories create test data and commit it. They follow a `make_X(session, ...)` pattern:

```python
make_profile(db_session)
make_project(db_session, profile)
make_project_brief(db_session, project)
make_project_proposal(db_session, project, brief)
make_project_revision(db_session, project, proposal)
make_task_generation_run(db_session, project=project, revision=revision)
make_task(db_session, project=project, revision=revision, generation_run=run, **overrides)
make_bed(db_session, profile)
make_container(db_session, profile)
make_plant(db_session, profile, container=container, bed=bed, **overrides)
make_batch(db_session, profile, project=project)
make_incident_report(db_session, **overrides)
make_treatment_plan(db_session, incident)
make_triage_snapshot(db_session, recommended_task_ids=[...])
```

All factories call `_persist(session, obj)` which does `session.add` + `session.commit` + `session.refresh`.

---

## The `_accept_plan` helper

Many tests need a project with tasks. The `_accept_plan` function in `tests/tools/projects/test_task_tracker_tools.py` creates a full project with an accepted proposal (brief → proposal → accepted):

```python
from tests.tools.projects.test_task_tracker_tools import _accept_plan

project = _accept_plan(
    db_session,
    patched_sessionlocal,
    propagation_method="seed",    # or "nursery"
    target_completion="2026-07-01",
    budget_cap=120.0,
)
```

Then call `generate_project_tasks.invoke({"project_id": project.id})` to add tasks.

---

## Writing a new integration test

```python
import pytest
from agent.tools.projects.tracker import complete_task, start_task
from tests.support.factories import make_profile, make_project, make_project_brief, ...

@pytest.mark.integration
def test_my_feature_does_the_right_thing(db_session, patched_sessionlocal):
    # 1. Set up test data using factories
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    # ... build up to what you need

    # 2. Call the tool
    result = start_task.invoke({"task_id": task.id})

    # 3. Assert on the string result
    assert "Started task" in result

    # 4. If you need to check DB state, expire_all() first
    db_session.expire_all()
    refreshed = db_session.query(Task).filter(Task.id == task.id).one()
    assert refreshed.status == "in_progress"
```

**Important:** if a factory commits data and then a tool opens its own session, you need to commit before the tool call too. Factories commit automatically. For `record_activity_event` or other domain calls in tests, call `db_session.commit()` before invoking tools.

---

## Writing a unit test

Unit tests don't use DB fixtures:

```python
import pytest
from agent.domain.care import infer_care_action
from types import SimpleNamespace

@pytest.mark.unit
def test_infer_care_action_water():
    task = SimpleNamespace(generator_key="tomato.watering", title="Water tomatoes", description="")
    assert infer_care_action(task) == "water"
```

For domain functions that need a DB session (like `compute_task_blocked_state`), use the `db_session` fixture — it creates a fresh in-memory DB. No `patched_sessionlocal` needed since you're calling the domain function directly, not a tool.

---

## Writing a graph test

```python
import pytest
from agent import nodes  # now at agent.core.nodes, but `from agent.core import nodes` also works
from tests.support.fakes import make_tool_call_message

@pytest.mark.graph
def test_should_continue_routes_correctly(monkeypatch, patched_sessionlocal):
    monkeypatch.setattr(nodes, "interrupt", lambda prompt: "confirm")
    state = {
        "messages": [
            make_tool_call_message(
                "Deleting",
                name="delete_project",
                args={"project_id": "proj-1"},
                call_id="call-1",
            )
        ]
    }
    result = nodes.confirmation_node(state)
    assert result["interaction_history"][0]["resolution_action"] == "confirm"
```

The `make_tool_call_message` and `make_ai_message` helpers in `tests/support/fakes.py` build synthetic LangChain message objects.

---

## FakeBoundModel

For tests that need the full graph (not just a node), use `FakeBoundModel`:

```python
def test_full_turn(fresh_test_graph, fake_bound_model):
    fake_bound_model.queue(
        AIMessage(content="Here is my response.")
    )
    result = fresh_test_graph.invoke(
        {"messages": [HumanMessage(content="What's in my garden?")]},
        config={"configurable": {"thread_id": "test-thread", "user_id": 1}}
    )
    assert "response" in result["messages"][-1].content
```

`FakeBoundModel.queue(*responses)` sets up responses in order. Calling `invoke` beyond the queued responses raises `AssertionError`.

---

## Deferred tests

`tests/DEFERRED_TESTS.md` documents 11 test areas that are consciously not tested and why:
- Bulk scale tests (wait for Postgres)
- DST edge cases (wait for timezone-aware columns)
- Weather API failure simulation (needs HTTP mocking setup)
- Circular dependency chains deeper than 2 levels
- Concurrency / race conditions (SQLite serializes writes)

Review this file before adding a test you think might already be covered or explicitly deferred.

---

## Test coverage summary

| Area | File | Key scenarios covered |
|---|---|---|
| Domain logic | `tests/agent/domain/test_domain_logic.py` | compute_task_blocked_state (9 cases), planner estimates, infer_care_action patterns, _resolve_subjects |
| Graph routing | `tests/agent/core/test_nodes.py` | all routing branches |
| Node edge cases | `tests/agent/core/test_node_edge_cases.py` | empty string confirm, special chars, missing plan, mixed calls |
| Task tracker | `tests/tools/projects/test_task_tracker_tools.py` | generate, regenerate, materialize, all lifecycle actions |
| Priority/progress | `tests/tools/projects/test_priority_and_progress.py` | daily scoring, priority field, project progress |
| Bulk assign | `tests/tools/projects/test_bulk_assign.py` | partial success, conflicts, dedup, idempotency |
| Query efficiency | `tests/tools/projects/test_query_efficiency.py` | count correctness, location resolution, unique constraints |
| Status transitions | `tests/tools/operations/test_status_and_orphans.py` | all invalid transition rejections, orphan prevention |
| Activity history | `tests/tools/operations/test_activity_history.py` | all new tools, filtering, pagination, interaction events |
