# Deferred Tests

Tests that are known gaps but consciously deferred. Each entry explains why it was deferred and what would need to change to enable it.

---

## Scale / bulk operations

**What:** Verifying that tools behave correctly at realistic scale — 100+ plants, 50+ tasks, 20+ concurrent projects, 500+ activity events.

**Why deferred:** The application is single-user and not yet deployed. The current data volumes are trivially small. N+1 fixes (already landed) address the structural problem; adding scale tests now would just validate against SQLite which doesn't reflect Postgres performance characteristics.

**Re-enable when:** Postgres migration is complete. Use `pytest-benchmark` or a dedicated load-test script against a staging Postgres instance.

---

## DST / timezone edge cases

**What:** Task scheduling, triage timestamps, and weather snapshot dates all use naive UTC datetimes. When the user's local timezone observes DST, edge cases like "midnight rollover during the spring-forward hour" could produce off-by-one date errors.

**Why deferred:** The codebase stores all datetimes in naive UTC and converts to local timezone only for display. Until the Postgres migration (which moves to `DateTime(timezone=True)`) and a real frontend exist, DST bugs are latent but not user-visible.

**Re-enable when:** Postgres migration lands. Add parametrized tests that inject a `now` value at a DST boundary (e.g. `2026-03-08 02:00 America/Los_Angeles`) and verify task urgency and triage date labeling are correct.

---

## Weather API failure simulation

**What:** `refresh_weather_snapshot` calls Open-Meteo. If the network is down or returns an error, the current code propagates the exception. No fallback or retry is tested.

**Why deferred:** Tests mock the model and skip live API calls. Adding a weather API mock requires either `responses` / `httpretty` or a test fixture that patches `httpx`/`requests` at the right level. Not yet set up.

**Re-enable when:** The project adds a dedicated HTTP mock fixture. Tests should cover: 404, timeout, malformed JSON, and rate-limit (429) responses.

---

## Inference model unavailable / fallback

**What:** The model factory in `agent/model.py` is expected to fall back from Fairlead → Gemini Flash → Claude Haiku. This chain is never exercised in tests.

**Why deferred:** All tests use `FakeBoundModel` and never reach the real model factory. The fallback chain is infrastructure-level behavior that requires running Fairlead or simulating its failure.

**Re-enable when:** Fairlead is built and a test environment exists that can simulate endpoint failures.

---

## Concurrency / race conditions

**What:** Two simultaneous requests updating the same task, project, or triage snapshot could produce inconsistent state. SQLite serializes writes so this can't be observed locally.

**Why deferred:** SQLite's write serialization masks all concurrency bugs. Meaningful concurrency tests require Postgres with real concurrent sessions.

**Re-enable when:** Postgres migration is complete. Use `threading` or `asyncio` to fire concurrent `update_task` / `complete_task` calls and verify that exactly one succeeds cleanly.

---

## Deep task dependency chains (>5 levels)

**What:** `cascade_defer_to_dependents` pushes `earliest_start` forward on *direct* dependents only (one level). For chains A→B→C→D→E, deferring A only adjusts B. C–E remain inconsistent.

**Why deferred:** Chains this deep don't occur in the current task blueprints. The single-level cascade was a deliberate scope decision. Full transitive cascading requires a recursive or BFS traversal and re-evaluation of every downstream task's dates.

**Re-enable when:** A user reports a scheduling inconsistency in a deep chain, or the task blueprint generator creates deeper dependency graphs. The fix is a BFS traversal in `cascade_defer_to_dependents`; the tests can be parameterized by chain depth.

---

## Proposal cost / timeline accuracy (regression against LLM outputs)

**What:** `estimate_plan_cost`, `estimate_plan_timeline`, and `estimate_plan_effort` are tested for arithmetic correctness (see `test_domain_logic.py`). What is NOT tested is whether the numbers stay calibrated against real-world garden outcomes over time — i.e. whether a Tomato project that the planner says takes 11 weeks actually takes 11 weeks.

**Why deferred:** This requires historical project completion data, which doesn't exist yet. It's a model-accuracy concern, not a code-correctness concern.

**Re-enable when:** Several projects have been run end-to-end and completion data exists. Build a regression fixture that compares planned vs. actual timeline/cost for seeded historical projects.

---

## Activity log retention / pruning

**What:** No tests verify what happens when the activity log grows very large (10,000+ events), or that old events are retained/pruned according to any policy.

**Why deferred:** There is no retention policy yet. This is an operational concern for when the app is deployed.

**Re-enable when:** A retention policy is defined and implemented.

---

## Data corruption recovery

**What:** No tests verify behaviour when the database is in an inconsistent state — e.g., a `Task` row whose `project_id` references a deleted project (only possible in SQLite, not Postgres with FK enforcement), or a `TaskDependency` whose `blocking_task_id` points to a superseded task.

**Why deferred:** These states shouldn't arise from normal application code. With Postgres FK enforcement they become impossible. Not worth investing in recovery logic for SQLite edge cases.

**Re-enable when:** If a migration script or manual DB intervention creates inconsistent state, add a `db/repair.py` utility and test it.

---

## Multi-device / multi-session interaction state

**What:** If a user has the app open in two browser tabs and resolves an interaction in one, the other tab's state may be stale. The interaction system uses polling and LangGraph checkpoints; stale-state handling is untested.

**Why deferred:** No frontend exists yet. This is a frontend + backend co-design problem.

**Re-enable when:** Verdant is built and polling/SSE behavior can be driven by real frontend test scenarios.

---

## `check_plan_feasibility` exhaustive constraint testing

**What:** `check_plan_feasibility` has several hard constraint checks (budget cap, timeline, tray capacity, location availability) and soft warnings (sunlight mismatch). Only the happy path is indirectly tested via `save_project_proposal`.

**Why deferred:** The feasibility checks are already partially covered via integration tests on `assemble_planning_context` and `list_candidate_locations`. Dedicated unit tests of every violation path are straightforward to add but low urgency given the existing integration coverage.

**Re-enable when:** A constraint is found to be silently ignored in a real planning session. Add one unit test per violation type to `test_domain_logic.py`.

---

## SSE streaming endpoints

**What:** Tests for `POST /internal/agent/stream` and `POST /internal/agent/resume/stream` — verifying the SSE event sequence (token events, interaction event when graph pauses, done event), correct `Content-Type: text/event-stream` header, and that the stream closes cleanly.

**Why deferred:** The streaming endpoints use `agent.astream_events()` which calls the real LangGraph graph and LLM. The `fresh_test_graph` fixture builds a test graph with a `FakeBoundModel`, but wiring it into the FastAPI `TestClient` requires either:
- Patching `agent.core.graph.agent` in the test session before the router module loads (import-time state), or
- Restructuring the router to accept an injectable graph instance (FastAPI dependency injection pattern)

Neither is trivial. The non-streaming agent endpoint has the same gap — streaming makes it more visible.

**Re-enable when:** The router is refactored to accept an injectable `agent` via FastAPI `Depends`, allowing `TestClient` tests to inject the `fresh_test_graph`. At that point, streaming tests can verify the full event sequence end-to-end with a fake model.
