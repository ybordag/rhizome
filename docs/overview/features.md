# Features

Complete inventory of Rhizome's current capabilities, organized by domain.

---

## Garden model

The foundation everything else builds on. Rhizome holds a persistent model of the physical garden.

**Garden profile** — climate zone, frost dates (last spring / first fall), soil type, tray capacity (total / indoor under grow lights), location coordinates for weather, hard constraints (e.g. dog-safe plants only), soft preferences.

**Beds** — named beds with location, sunlight level, soil type, dimensions, and care history (last watered, fertilized, amended, inspected). Assigned to projects.

**Containers** — pots, growbags, raised containers with type, size (gallons), location, mobility flag, and care history. Assigned to projects.

**Plants** — individual plants with variety, quantity, source (seed / cutting / transplant / existing), status (planned → germinating → seedling → established → producing → dormant → removed), timing dates (sow, red cup, transplant), care state (last watered/fertilized/inspected/treated/pruned), and fertilizing schedule. Linked to projects via ProjectPlant.

**Batches** — groups of plants sown together from the same source (seed packet, nursery, cutting donor). Track supplier, seed lot, grow light assignment, tray location.

**Care state** — every plant, bed, and container tracks last care timestamps and `care_state_notes`. Completing a task automatically updates care state on linked subjects (a "Water Tomato" task updates `last_watered_at` on the tomato plant and its container).

---

## Project planning

Structured lifecycle from goal to approved plan.

**Project brief** — user's working requirements: desired outcome, target start/completion, budget cap, effort preference, propagation preference, priority preferences. Auto-promotes to `ready_for_proposal` when all required fields are set.

**Planning context** — `assemble_planning_context` gathers candidate locations (with conflict detection against other active projects), candidate plant material (existing plants that could be reused or provide cuttings), and current resource allocation.

**Proposals** — agent-generated plans with:
- Selected plants and locations
- Propagation strategy (seed vs starts)
- Feasibility check (hard violations + soft warnings)
- Cost estimate: plant material, materials, soil amendment, container setup, 10% contingency
- Timeline estimate: planning start → first action → establishment → completion → maintenance mode
- Effort estimate: total hours, avg/peak hours per week, work buckets (setup / propagation / care)
- Assumptions, tradeoffs, risks, feasibility notes

**Versioning** — proposals are versioned. Multiple proposals can exist for a brief; accepting one supersedes prior revisions.

**Acceptance** — accepting a proposal creates a `ProjectRevision` and `ProjectExecutionSpec` (normalized for task generation). Previous revisions are superseded.

**Schedule preview** — non-destructive preview of the task graph and recurring series that would be generated from a proposal, before committing.

---

## Task management

Auto-generated task graphs with full lifecycle management.

**Task generation** — from an accepted `ProjectExecutionSpec`, Rhizome generates:
- Section header tasks (Setup, Propagation, Establishment, Ongoing care, Maintenance mode / harvest)
- Milestone tasks per plant (sow, pot up, transplant, supports, harvest window check)
- Recurring series (watering every 2–3 days, inspection weekly, fertilizing every 14 days, pruning for fruiting vines)
- Initial 14-day materialization of recurring instances
- TaskDependency links (sow → pot up → transplant; location prep blocks transplant; etc.)

**Event anchors** — tasks that wait for a biological trigger event (plant_germinated, plant_transplanted) rather than a fixed date. When the event fires, the task gets a scheduled date and unblocks.

**Priority** — `Task.priority` field (critical / high / normal / low). Auto-assigned at generation from task type (milestone→high, maintenance→normal, emergency→critical, opportunistic→low). User-overridable via `update_task`.

**Daily work list** — `get_daily_priority_tasks(limit, project_id?)` scores every active task and returns the top N. Score = urgency weight (100/75/40/10) + type weight (50/20/5/0) + priority weight (60/30/0/-20) + blocking bonus (+30 if task unblocks ≥1 other) + triage alignment (+25 if in today's triage recommendations) + blocked penalty (-20).

**Lifecycle** — tasks move through: `pending → in_progress → done/skipped/deferred/blocked/superseded`. Completing a task: unblocks direct dependents, applies care side effects, records activity.

**Cascade defer** — deferring a task pushes direct dependents' `earliest_start` forward by the same delta, preventing silent schedule inconsistencies.

**Regeneration** — `regenerate_project_tasks` supersedes all replaceable prior tasks (preserving `is_user_modified=True` tasks) and generates a fresh graph from the current execution spec.

**Blocker logic** — `compute_task_blocked_state` checks: (a) event anchor without resolved date, (b) any direct dependency not in `{done, skipped}`. Note: only checks direct blockers (one level deep), no recursive traversal.

**Series and recurrence** — `TaskSeries` defines the recurring rule; `materialize_task_series` rolls out instances on a 14-day horizon each time it's called. Series are deactivated on regeneration.

---

## Daily triage

Session-time snapshot for "what should I do today?"

**Triage snapshot** — built at every session start via a secondary, faster LLM call. Takes weather context, temporal context (day of week, season, frost proximity), urgent/routine/project task lists, and produces: reasoning summary, recommended task IDs, urgent/routine/project groupings.

**Urgency tiers** — computed dynamically from task dates:
- `blocker` — deadline or window_end ≤ tomorrow
- `time_sensitive` — window_end ≤ 2 days away
- `scheduled` — window_end ≤ 14 days
- `backlog` — everything else

**Weather integration** — weather snapshot loaded at session start; weather-affected tasks surface in triage with urgency context.

---

## Weather

**Snapshot** — fetches 7-day forecast from Open-Meteo (free, no API key) and derives impacts: frost, heat, heavy rain, storm, good planting window. Stores conditions summary, alerts summary, and recommended actions.

**Task impacts** — `list_weather_impacted_tasks` identifies tasks materially affected by current weather (e.g. "transplant tomatoes" conflicting with a forecast frost).

**Approval-gated changes** — `draft_weather_task_changes` builds a proposed set of task adjustments. `approve_weather_task_changes` applies them after user confirmation. All weather-driven task changes go through the interaction system.

---

## Incidents and treatment

**Incident reports** — user or agent reports a pest, blight, or weed incident linked to affected plants/beds/containers. Tracks type, severity, subjects.

**Treatment plans** — agent drafts a treatment approach with recommended steps (each with a due offset in days from approval) and follow-up strategy. Requires user approval before tasks are created.

**Approval** — `approve_treatment_plan` runs through the interaction node. On approval: treatment tasks are generated, linked to the incident's project, and appear in triage.

**Resolution** — `resolve_incident` marks an incident resolved with optional notes.

---

## Human-in-the-loop interactions

The structured interaction system is how Rhizome handles decisions that shouldn't be made unilaterally.

**Interaction types:**
- `confirmation_request` — destructive operation confirmation (delete_project, delete_bed, etc.)
- `proposal_review` — project proposal acceptance (accept_project_proposal)
- `treatment_plan_review` — treatment plan approval (approve_treatment_plan)
- `weather_change_review` — weather-driven task change approval (approve_weather_task_changes)

**Mechanics** — LangGraph's `interrupt` primitive pauses the graph and presents an `InteractionEnvelope` (structured card with title, summary, sections, action buttons). The graph resumes only after the user resolves the interaction. If cancelled, no changes are made and a cancellation record is written.

**Reuse** — pending interactions are persisted as `InteractionRecord`. If the agent tries to re-open the same interaction (e.g. re-approve an already-approved plan), it detects the existing record and redirects.

**History** — every resolution (confirm, cancel, approve, reject) is recorded as an `interaction_resolved` activity event, so user decisions appear in the project timeline.

---

## Action history

Every state change is recorded. The history system makes this queryable.

**Activity events** — every tool write calls `record_create_event`, `record_update_event`, `record_delete_event`, or `record_activity_event`. Events carry: actor, event_type, category, summary, project_id, event_metadata (before/after snapshots for update events), and links to affected subjects via `ActivitySubject`.

**Per-entity history** — `get_plant_activity`, `get_task_activity`, `get_bed_activity`, `get_container_activity`, `get_batch_activity`, `get_incident_activity` — all return a timeline filtered to a specific object.

**Project timeline** — `list_project_activity(project_id, category?, event_type?, since?, before_timestamp?, limit?)` — cross-object timeline for everything that happened within a project. Supports DB-level filtering and cursor pagination (`before_timestamp` for paging).

**General log** — `list_recent_activity` supports the same filters: category, event_type, since, before_timestamp.

---

## Search and navigation

`search_garden(query, entity_type?, location?, status?)` — find beds, containers, or plants by name, with optional location and status filters. Returns resolved location names and project membership counts.

`list_by_location(location)` — show everything in a specific garden area.

`list_projects(status?)`, `get_project(id)`, `get_project_progress(id)` — project navigation and status.
