# Using the CLI

The CLI is a simulation surface for the full app experience. Every feature — project planning, task management, triage, incident reporting — is accessible through conversation.

---

## Starting a session

```bash
python main.py
```

On startup, the agent:
1. Loads your garden profile and project state from the DB
2. Fetches the latest weather forecast (if stale)
3. Runs a triage pass — a secondary, faster LLM call that produces a structured session snapshot with recommended tasks, urgency groupings, and weather context
4. Introduces the session with a summary of what's happening in the garden

If the DB is empty (first run), the agent will ask you to describe your garden.

---

## Conversation patterns

**Ask about your garden**
```
How are my tomatoes doing?
What's in the front bed?
When did I last water the peppers?
```

**Start or check on projects**
```
I want to plan a summer vegetable garden in the courtyard bed.
What's the status of my tomato project?
Show me the tasks for the raised bed project.
```

**Plan a project** (the full negotiation flow)
```
I want to grow tomatoes, basil, and one pepper plant this summer.
[Agent asks clarifying questions about budget, timeline, space]
[Agent presents a proposal with cost/timeline/effort estimates]
[You approve, revise, or reject]
[Agent generates the task graph]
```

**Daily triage**
```
What should I do today?
What are my most urgent tasks?
Show me my top 5 priorities.
```

**Task actions**
```
I finished watering the tomatoes.       → complete_task
I'm starting on the transplanting now.  → start_task
Skip the fertilizing this week.         → skip_task (requires a reason)
Defer the pruning until next weekend.   → defer_task
```

**Incidents**
```
I found aphids on my pepper plants.     → report_incident
What's the treatment plan for the aphids?
I've treated the aphids, they're gone.  → resolve_incident
```

**Weather**
```
What does the weather look like this week?
How does the forecast affect my tasks?
Refresh the weather data.
```

---

## How the agent pauses for approval

For consequential decisions — approving a project plan, applying weather-driven task changes, deleting something — the agent will pause mid-conversation and present a structured card.

Example: approving a treatment plan
```
Agent: I've drafted a treatment plan for the aphid incident.

──────────────────────────────────────────────
TREATMENT PLAN: Aphids on pepper plants

Approach: Organic-first — neem oil spray + manual removal

Recommended steps:
  • Spray neem oil solution today
  • Re-inspect in 3 days
  • Manual removal if population persists

[approve] [reject]
──────────────────────────────────────────────

Type 'approve', 'reject', or your feedback:
```

The conversation is paused at this point. The graph resumes only after you respond. If you cancel or reject, no changes are made.

---

## Tips

**Use task IDs for precision.** When completing or acting on a specific task, the agent works best with the exact task ID from `list_project_tasks` or `list_due_tasks`. You can also use the exact task title as a fallback, but IDs are unambiguous.

**Ask for explanations.** "Why is this task blocked?" → `explain_task_blockers`. "What happens if I skip this?" → the task's `what_happens_if_skipped` field.

**Check history.** "What happened to the tomatoes last week?" → the agent can query `get_plant_activity`. "Show me the full project history." → `list_project_activity`.

**Triage is regenerated each session.** The triage snapshot is built at session start. If you want a fresh one mid-session, ask "run triage again" or "what should I focus on now?"

---

## Session persistence

Conversation history and pending interactions are persisted in the LangGraph checkpointer keyed by `thread_id`. Local SQLite runs use `rhizome_checkpoints.db`; Postgres-backed environments use the LangGraph Postgres checkpointer. The next session picks up exactly where you left off — including any pending approvals that weren't resolved.

Garden state (plants, tasks, projects, care history) is persisted in the application database selected by `DATABASE_URL` and is always current regardless of session state.

---

## Internal API and Swagger UI

Rhizome also runs as a FastAPI server (`python server.py`) that Cambium calls. When the server is running, the full internal API is explorable at:

```
http://localhost:8001/docs
```

FastAPI generates this Swagger UI automatically — it always reflects the live code. Use it to inspect the `/internal/data/...` endpoints during development or to understand what Cambium is proxying.

The CLI (`python main.py`) and the API server (`python server.py`) share the same LangGraph agent and domain code — the only difference is the interface layer.
