# Rhizome Agent Improvements

**Status:** Partially completed  
**Last updated:** 2026-04-11

---

## Purpose

This document captures near-term engineering improvements for the current Rhizome agent implementation, separate from the longer-horizon architecture work on state, persistence, and tenancy.

These improvements are intended to make the current agent more observable, more reliable, and easier to extend as we move into the next major feature area:

- comprehensive activity log
- task tracker / schedule generator
- daily task triage / planner

This document focuses on four improvement tracks:

1. ControlFlux integration
2. Unit test coverage
3. Presentation helper fixes
4. Validation fixes

State, persistence, and tenancy are intentionally out of scope here. Those are already planned as separate follow-on tickets.

---

## Progress snapshot

The original cleanup and hardening work is now partly complete.

Completed:

- presentation helper cleanup landed
- light tool-layer validation fixes landed
- pytest-based unit and integration test baseline landed
- phase 1 activity log foundation landed as a separate follow-on track

Still open:

- ControlFlux / OTel integration remains deferred
- project planner work remains ahead of task tracking
- later activity-log expansion remains open for task-driven care events

This means the near-term baseline work is in much better shape than when this
document was first drafted. The next major feature area is no longer "cleanup
first"; it is planner/task work on top of a cleaned-up and tested foundation.

---

## Current roadmap and GitHub confirmation

The active build plan in [build_plan.md](/Users/yashi/Documents/Work/Code/Gardening%20Agent/rhizome/docs/current%20work/build_plan.md) is consistent with the current GitHub issue queue.

### Confirmed roadmap alignment

- **Step 4: Rough task timing** is open as issue [#19](https://github.com/ybordag/rhizome/issues/19)
  - Add `Task` model
  - Add Open-Meteo integration
  - Implement `generate_schedule`
  - Inject upcoming tasks into prompt context

- **Step 5: Daily triage** is open as issue [#20](https://github.com/ybordag/rhizome/issues/20)
  - Add `session_context_intake`
  - Add `urgency_escalator`
  - Add `triage_reasoner`
  - Add `session_context` and `pending_tasks` to state

### Related open issues

- [#12](https://github.com/ybordag/rhizome/issues/12) `Additional Task Data Fields`
  - equipment needed
  - material needed
  - follow-up date

- [#13](https://github.com/ybordag/rhizome/issues/13) `Schedule Generator should also take weather forecast into account when planning`

- [#14](https://github.com/ybordag/rhizome/issues/14) `Create Tool/Resource Inventory`

- [#15](https://github.com/ybordag/rhizome/issues/15) `Cost and Produce Tracking`

### Gap confirmation

There is currently **no explicit open GitHub issue** for:

- ControlFlux / OTel integration
- presentation helper cleanup
- validation hardening

Updates since this document was first drafted:

- the unit and integration test baseline now exists and is tracked in open
  issue [#27](https://github.com/ybordag/rhizome/issues/27)
- the phase 1 activity log foundation is now implemented and tracked by closed
  issue [#34](https://github.com/ybordag/rhizome/issues/34)
- the later task-driven care follow-up remains open in
  [#33](https://github.com/ybordag/rhizome/issues/33)

The task tracker / planner direction is still represented by the roadmap and
GitHub issues, but the activity log is no longer only implied future work: its
phase 1 foundation is now part of the codebase.

---

## Why these improvements matter now

When this document was first drafted, the current agent had four weaknesses that
would make Step 4 and Step 5 harder if left unaddressed:

- limited observability into graph execution and tool usage
- near-zero automated test coverage
- string formatting defects in model presentation helpers
- inconsistent validation across tools and models

Most of that baseline risk has now been reduced. The remaining major gap before
planner/task work expands is observability and runtime tracing:

- understanding how planning and task-generation behavior unfolds at runtime
- tracing failures across graph execution and tool usage
- preserving enough operational context for later planner/task debugging

---

## Improvement 1: ControlFlux Integration

**Status:** Deferred

### Goal

Add an observability and runtime-event layer around Rhizome that works:

- **standalone via OpenTelemetry**
- **optionally with ControlFlux later**

This should not require replacing Rhizome’s current model path yet.

### Why this is the right first integration

Rhizome is currently a LangGraph tool-calling agent. The immediate need is to observe and log what the graph is doing, not to swap the LLM transport.

For Rhizome, the most valuable telemetry events are:

- user message received
- LLM call started / completed
- tool call started / completed
- destructive confirmation requested / cancelled / approved
- task schedule generation started / completed
- triage reasoning started / completed
- optional state snapshots at key graph boundaries

### Scope

Near-term ControlFlux-compatible integration should be **observer-style**, not **model-replacement-style**.

That means:

- keep Gemini + current tool-calling path intact
- emit OTel spans directly from Rhizome
- define an observer interface so a future ControlFlux adapter can forward the same lifecycle events into an external controller / replay system

### Recommended implementation shape

- Add a small telemetry module under `agent/`
- Emit spans around:
  - per chat turn
  - `llm_call`
  - each individual tool invocation
  - confirmation interrupt flow
- Emit structured events for:
  - messages
  - tools
  - state snapshots
- Treat `thread_id` as the initial `trace_id`

### Desired outcome

By the time Step 4 and Step 5 land, we should be able to answer:

- what tasks were generated and from which prompt context?
- which tool calls were invoked to create the schedule?
- why did the triage node recommend one task over another?
- where did a failure occur in the graph?

### Relationship to upcoming features

This directly supports:

- activity log
- task schedule debugging
- triage auditability
- later ControlFlux integration in shadow mode

### Ticket recommendation

This should become its own GitHub issue if we decide to proceed with it before Step 4 implementation.

---

## Improvement 2: Unit Test Coverage

**Status:** Implemented baseline

### Goal

Establish a minimum test baseline before the task / planner feature set expands the surface area further.

### Current problem

This was the original problem statement. It is no longer true after the recent
test-suite work. Rhizome now has a pytest-based baseline covering:

- model formatting
- DB-backed tool behavior
- graph branching and destructive confirmation flow
- telemetry smoke behavior
- activity-log schema, write paths, and history queries

The remaining work here is expansion, not baseline creation.

Before this work, the test directories existed but the checked-in tests and
conftests were effectively empty. That meant the repo had almost no guardrails
for:

- model formatting
- tool behavior
- graph branching
- destructive confirmation flow
- schedule / task generation

### Minimum baseline to add

#### Model tests

- `GardenProfile.to_summary()` and `to_detailed()`
- `GardeningProject.to_summary()` and `to_detailed()`
- `Bed.to_summary()` / `to_detailed()`
- `Container.to_summary()` / `to_detailed()`

#### Tool tests

- `create_project`
- `list_projects`
- `get_project`
- `update_project`
- `add_plant`
- `update_plant`
- `remove_plant`
- key destructive tool safety paths

#### Graph / node tests

- `should_continue()` branching
- destructive tool detection
- confirmation cancel path
- confirmation approve path

#### Telemetry tests

- no-op behavior without OTel installed
- span / event hooks do not break normal execution
- observer hooks do not alter agent behavior

### Desired outcome

This baseline is now in place. Step 4 and Step 5 can build on top of a stable
foundation where:

- helper formatting regressions are caught
- invalid statuses are rejected in tests
- destructive flows are proven
- tool output contracts are stable

### Relationship to upcoming features

This is a prerequisite for confident task and triage work.

Without tests, every new scheduling rule or urgency rule will be fragile.

### Ticket recommendation

Keep [#27](https://github.com/ybordag/rhizome/issues/27) as the umbrella test
coverage tracker for follow-on expansion.

---

## Improvement 3: Presentation Helper Fixes

**Status:** Implemented

### Goal

Fix user-facing formatting defects in model helper methods before the agent starts surfacing richer task and schedule data.

### Current problem

This cleanup has already landed.

Several `to_summary()` / `to_detailed()` helpers concatenate strings without proper separators or newlines. This causes malformed output such as:

- `... totalCreated at: ...`
- `Updated at: ... Notes: ...`

These bugs are minor today, but they will matter much more once the agent is presenting:

- task lists
- schedule windows
- activity timelines
- project detail views

### Fix areas

- `GardenProfile`
- `GardeningProject`
- `Bed`
- `Container`
- any related plant / batch presentation helpers

### Desired outcome

All model summary and detail renderers should produce:

- stable line structure
- predictable whitespace
- readable multi-line output
- output that is safe to inject into prompts without accidental run-together fields

### Relationship to upcoming features

Step 4 and Step 5 rely heavily on clear text presentation:

- “Coming up this week”
- task details
- triage output
- project summaries

If the base rendering is sloppy, prompt quality and user-facing output both degrade.

### Ticket recommendation

This work is complete and should only need follow-on updates if new planner/task
objects introduce additional renderers.

---

## Improvement 4: Validation Fixes

**Status:** Implemented (light tool-layer validation)

### Goal

Harden tool-layer validation so invalid data cannot silently enter the database before task and planner features expand the schema further.

### Current problem

The initial hardening pass has already landed.

Validation is inconsistent today.

Examples:

- project status values are validated
- plant status values are not consistently validated
- date parsing is optimistic
- some tools rely on assumptions rather than enforcing input constraints

This is manageable for current CRUD, but it becomes riskier once we add:

- deadline windows
- urgency fields
- follow-up dates
- schedule generation metadata
- planner context

### Recommended validation additions

#### Enum-like field validation

- plant lifecycle status
- project lifecycle status
- task type
- future task status / urgency fields

#### Input integrity checks

- ISO date validation with clear errors
- no ambiguous empty strings where `None` is expected
- location exclusivity where needed
  - e.g. plant in bed vs plant in container

#### Cross-record safety checks

- batch / plant / project consistency
- duplicate active assignment handling
- destructive operations with explicit safety guarantees

### Desired outcome

Rhizome should reject malformed writes early and return useful tool messages for recovery.

### Relationship to upcoming features

This is especially important for Step 4 and Step 5 because invalid task windows or malformed status values will cascade into:

- bad schedule generation
- wrong urgency escalation
- broken triage reasoning

### Ticket recommendation

Future validation work should be scoped alongside the planner/task schema rather
than as a separate precondition ticket.

---

## Recommended sequencing

This was the original recommended sequence:

1. **Presentation helper fixes**
2. **Validation fixes**
3. **Unit test baseline**
4. **Step 4: Rough task timing**
5. **Step 5: Daily triage**
6. **ControlFlux integration in shadow / observer mode**

### Why this order

- presentation and validation are small, high-leverage cleanup tasks
- tests provide safety before task logic lands
- Step 4 and Step 5 are already the next roadmap features
- ControlFlux integration is valuable, but it is more effective once there is richer task/triage behavior to observe

An alternative is to start a **minimal standalone OTel integration now**, but still treat full ControlFlux-style harness integration as parallel or follow-on work.

---

## Activity log note

This section is now partly outdated. The activity log is no longer only planned:
phase 1 has already landed.

Current activity-log status:

- phase 1 activity-log foundation is complete
- project/plant/bed/container/batch history can now be recorded and queried
- later task-driven care events remain deferred until task tracking exists

The remaining work is to connect the future planner/task system into this
foundation rather than to invent the activity log from scratch.

---

## Suggested next action

The cleanup baseline has mostly been established. The best next action is:

1. define the project planner from scratch against the current codebase
2. design the task tracker to build on planner output and activity-log events
3. revisit ControlFlux / OTel integration only once planner/task execution adds
   more runtime behavior worth observing
