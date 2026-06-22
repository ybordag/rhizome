# Tools Reference

All 94 tools registered in `agent/tools/__init__.py`, organized by domain.
Tools are exposed to the LLM via LangChain's tool binding and return strings
for chat use.

Cambium and Verdant should use Rhizome's structured internal API routes for
frontend data contracts. Those routes may share domain logic with tools, but
they should not require parsing tool prose.

---

## Garden entities (`agent/tools/garden/`)

### Profile
| Tool | Purpose |
|---|---|
| `get_garden_profile(detailed?)` | Show garden profile (climate zone, frost dates, tray capacity, location) |
| `update_garden_profile(...)` | Update profile fields |

### Plants (`plants.py`)
| Tool | Purpose |
|---|---|
| `add_plant(name, variety, quantity, source, ...)` | Add a plant to the garden |
| `update_plant(plant_id, status, ...)` | Update plant status, care state, notes |
| `remove_plant(plant_id, reason)` | Soft-remove a plant (status → removed) |
| `list_plants(status?, container_id?, bed_id?, batch_id?)` | List plants with filters |
| `delete_plant(plant_id)` | Hard delete (requires confirmation) |
| `batch_add_plant_type(name, quantity, source, ...)` | Add multiple plants of one type at once |
| `batch_update_plants(name, new_status?, project_id?, variety?, current_status?, quantity?, ...)` | Update plants matching a batch-style filter |
| `batch_remove_plants(name, reason, project_id?, variety?, current_status?, quantity?)` | Soft-remove plants matching a batch-style filter |
| `list_batches(project_id?)` | List plant batches |
| `delete_batch(batch_id)` | Hard delete batch (requires confirmation) |

### Beds & Containers (`beds_containers.py`)
| Tool | Purpose |
|---|---|
| `list_beds()` | List all beds with care state |
| `update_bed(bed_id, ...)` | Update bed fields (soil, sunlight, dimensions, notes) |
| `delete_bed(bed_id)` | Hard delete bed — blocked if active plants assigned (requires confirmation) |
| `list_containers()` | List all containers |
| `add_container(name, container_type, size_gallons, location, is_mobile, notes?)` | Add a container |
| `update_container(container_id, location?, notes?)` | Update container location or notes |
| `remove_container(container_id, reason?)` | Hard delete — blocked if active plants assigned (requires confirmation) |

### Search (`search.py`)
| Tool | Purpose |
|---|---|
| `search_garden(query, entity_type?, location?, status?)` | Find beds/containers/plants by name |
| `list_by_location(location)` | Show everything in a garden area |

---

## Projects (`agent/tools/projects/`)

### Projects (`projects.py`)
| Tool | Purpose |
|---|---|
| `create_project(name, goal, tray_slots, budget_ceiling, notes?)` | Create a new project |
| `update_project(project_id, name?, goal?, status?, ...)` | Update project fields |
| `get_project(project_id)` | Full project detail with beds, containers, plants, batches |
| `list_projects(status?)` | List all projects (4 bulk COUNT queries, not N+1) |
| `get_project_progress(project_id)` | Task completion %, timeline health, budget vs cap, blocker callout |
| `assign_bed_to_project(project_id, bed_id)` | Assign one bed (checks conflicts) |
| `assign_beds_to_project(project_id, bed_ids)` | Bulk assign beds (conflict + dedup detection in one query) |
| `assign_container_to_project(project_id, container_id)` | Assign one container |
| `assign_containers_to_project(project_id, container_ids)` | Bulk assign containers |
| `unassign_bed_from_project(project_id, bed_id)` | Remove bed assignment |
| `unassign_container_from_project(project_id, container_id)` | Remove container assignment |
| `add_plant_to_project(project_id, plant_id, notes?)` | Link plant to project |
| `remove_plant_from_project(project_id, plant_id, reason?)` | Soft-unlink plant |
| `delete_project(project_id)` | Hard delete — blocked if non-superseded tasks exist (requires confirmation) |

### Planning (`planning.py`)
| Tool | Purpose |
|---|---|
| `get_or_create_project_brief(project_id)` | Get or create the active planning brief |
| `get_project_brief(project_id)` | Get brief without creating |
| `update_project_brief(project_id, desired_outcome?, target_start?, ...)` | Update brief fields |
| `assemble_planning_context(project_id)` | Gather candidate locations + plant material + resource usage |
| `check_blocking_unknowns(project_id)` | List missing required fields before proposing |
| `list_candidate_locations(project_id)` | Available and unavailable beds/containers with conflict info |
| `list_candidate_plant_material(project_id)` | Existing plants usable as source material |
| `save_project_proposal(project_id, title, summary, ...)` | Generate and persist a proposal with estimates |
| `list_project_proposals(project_id)` | All proposals for a project |
| `get_project_proposal(project_id, proposal_id)` | Single proposal detail |
| `accept_project_proposal(project_id, proposal_id)` | Accept → create revision + execution spec (via interaction) |
| `preview_project_schedule(project_id, proposal_id?, revision_id?)` | Non-destructive task graph preview |

### Tracker (`tracker.py`)
| Tool | Purpose |
|---|---|
| `generate_project_tasks(project_id, revision_id?)` | Initial task graph from execution spec |
| `regenerate_project_tasks(project_id, revision_id?, reason?)` | Replace tasks, preserving user-modified ones |
| `materialize_recurring_tasks(project_id?, days_ahead?)` | Roll out next N days of recurring series |
| `list_project_tasks(project_id, status?, include_superseded?)` | Tasks grouped by section |
| `get_task(task_id)` | Task detail with blockers, urgency, priority |
| `list_due_tasks(project_id?, days_ahead?)` | Due tasks with urgency tiers |
| `get_daily_priority_tasks(project_id?, limit?)` | Top-N by daily priority score |
| `list_blocked_tasks(project_id?)` | Tasks blocked by dependencies or anchors |
| `list_task_series(project_id)` | Recurring task rules |
| `explain_task_blockers(task_id)` | What's preventing this task from starting |
| `start_task(task_id, notes?)` | → in_progress (blocked if task has unresolved blockers) |
| `complete_task(task_id, actual_minutes?, notes?)` | → done; unblocks dependents; applies care side effects |
| `skip_task(task_id, reason)` | → skipped (requires reason) |
| `defer_task(task_id, deferred_until, reason?)` | → deferred; cascades earliest_start to direct dependents |
| `update_task(task_id, title?, scheduled_date?, priority?, ...)` | Update task fields (sets is_user_modified=True) |
| `update_task_series(series_id, cadence?, active?, ...)` | Update recurring rule |

---

## Operations (`agent/tools/operations/`)

### Search (`search.py`)
| Tool | Purpose |
|---|---|
| `search_domain(query, domains?, limit?)` | Search across structured Rhizome domain records for planning and triage context |

### Activity (`activity.py`)
| Tool | Purpose |
|---|---|
| `get_project_activity(project_id, limit?, event_type?, category?)` | Project activity filtered |
| `list_project_activity(project_id, category?, event_type?, since?, before_timestamp?, limit?)` | Cross-object project timeline with pagination |
| `get_plant_activity(plant_id, limit?, event_type?)` | Plant history |
| `get_task_activity(task_id, limit?)` | Task history (creation, status changes, care updates) |
| `get_bed_activity(bed_id, limit?, event_type?)` | Bed history |
| `get_container_activity(container_id, limit?, event_type?)` | Container history |
| `get_batch_activity(batch_id, limit?, event_type?)` | Batch history |
| `get_incident_activity(incident_id, limit?)` | Incident history |
| `list_recent_activity(project_id?, subject_type?, event_type?, category?, since?, before_timestamp?, limit?)` | General activity log |

### Care (`care.py`)
| Tool | Purpose |
|---|---|
| `get_current_care_state(subject_type, subject_id)` | Last care timestamps for a plant/bed/container |
| `get_recent_care_history(subject_type, subject_id, limit?)` | Recent care events |

### Incidents (`incidents.py`)
| Tool | Purpose |
|---|---|
| `list_incidents(project_id?, status?, limit?)` | List incident reports |
| `get_incident(incident_id)` | Incident detail with subjects and treatment plan status |
| `report_incident(incident_type, summary, project_id?, severity?, subjects?, ...)` | Record a new incident |
| `draft_treatment_plan(incident_id)` | Agent drafts a treatment approach |
| `get_treatment_plan(treatment_plan_id)` | Treatment plan with steps and follow-up |
| `approve_treatment_plan(treatment_plan_id)` | Approve plan → generate treatment tasks (via interaction) |
| `resolve_incident(incident_id, notes?)` | Mark incident resolved |

### Interactions (`interactions.py`)
| Tool | Purpose |
|---|---|
| `get_pending_interaction()` | Current pending interaction (if any) |
| `list_recent_interactions(limit?, interaction_type?, project_id?)` | Recent interactions |
| `get_interaction_record(interaction_id)` | Specific interaction detail |
| `resolve_interaction(interaction_id, action_id, inputs?)` | Resolve a pending interaction (polymorphic by type) |

### Triage (`triage.py`)
| Tool | Purpose |
|---|---|
| `run_daily_triage(opener?, timezone?)` | Run triage and persist snapshot |
| `get_latest_triage_snapshot()` | Most recent triage snapshot |
| `list_triage_recommendations(limit?)` | Agent-facing helper that formats recommended task IDs from today's triage. This is not a frontend API route; use `GET /triage/latest` for structured app data. |

### Weather (`weather.py`)
| Tool | Purpose |
|---|---|
| `refresh_weather_snapshot()` | Fetch fresh 7-day forecast from Open-Meteo |
| `get_latest_weather_snapshot()` | Most recent weather snapshot |
| `list_weather_impacted_tasks(project_id?)` | Tasks affected by current forecast |
| `draft_weather_task_changes(project_id, weather_snapshot_id)` | Propose weather-driven task adjustments |
| `approve_weather_task_changes(change_set_id)` | Apply proposed changes (via interaction) |

---

## Tool conventions

**All tools return strings.** The LLM reads tool output as text. Complex results are formatted as human-readable text with IDs embedded.

**All tools handle errors as return strings.** No exceptions propagate to the LLM. Error messages include enough context to retry ("No task found with id X.").

**All tools open and close their own DB session** in a `try/finally` block. Sessions are not shared across tool calls.

**Session-patching in tests** — the `patched_sessionlocal` fixture in `tests/support/patching.py` replaces `SessionLocal` in every tool module with a test session factory that uses an in-memory SQLite DB.

**Destructive tools route through `interaction_node`** — the set is defined in `DESTRUCTIVE_TOOLS` in `agent/core/nodes.py`. Review tools (accept_project_proposal, approve_treatment_plan, approve_weather_task_changes) route through the same node but as `INTERACTION_REVIEW_TOOLS`.
