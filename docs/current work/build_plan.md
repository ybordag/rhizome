# Rhizome — Build Plan

**Status:** Active  
**Last updated:** 2026-03-26

---

## How to use this document

Each step is written as a self-contained assignment. Before starting a step, read the whole section. At the end of each step there are things to play around with — don't skip these. They are how you will discover problems and build intuition before moving on.

**A note on context management:** Context management is not a separate step. It is a concern that evolves with every step. Each step has a section explaining what context management looks like at that stage. By the end of all steps, you will have built the full context management system incrementally without ever treating it as a big separate project.

**How to track progress:**
- Create a GitHub issue for each step before you start it
- Use the "what to build" list as your task checklist in the issue
- Update the status table below as you go
- Note anything that differed from the plan as a comment on the issue before closing it

---

## Steps overview

| Step | Name | Status | Core loop complete? |
|------|------|--------|-------------------|
| 1 | Grounded chat | ✅ complete | No |
| 2 | Persistent garden profile | 🔲 not started | No |
| 3 | Simple project tracking | 🔲 not started | No |
| 4 | Rough task timing | 🔲 not started | No |
| 5 | Daily triage | 🔲 not started | **Yes — core loop done** |
| 6 | Negotiation loop | 🔲 not started | Refinement |
| 7 | Web search + richer context | 🔲 not started | Refinement |
| 8 | Iteration | 🔲 not started | Refinement |
| 9 | Reactive monitoring | 🔲 not started | Refinement |
| 10 | RAG knowledge base | 🔲 not started | Refinement |

Steps 1–5 build the core loop. Steps 6–10 make it smarter and richer.

---

## Step 2 — Persistent garden profile

### What you should understand after this step

Why persistence matters and what "state" means across sessions versus within a session. You should understand the difference between LangGraph's built-in checkpointing (which handles in-session state) and your own database (which handles long-term state that survives across sessions). You should also understand SQLAlchemy's basic model definition pattern and why we're using SQLite now even though the production plan is Postgres.

### What to build

A SQLite database with two tables: one for the garden profile, one for conversation history. The garden profile is loaded at session start instead of being hardcoded. Conversation history is saved after each turn and reloaded when the session restarts.

Use LangGraph's `SqliteSaver` checkpointer to handle in-session conversation state automatically. Write your own garden profile loading separately.

**File structure additions:**
```
rhizome/
└── db/
    ├── __init__.py
    ├── models.py       ← SQLAlchemy models for GardenProfile and Conversation
    ├── database.py     ← connection setup, session factory
    └── seed.py         ← populate your garden profile into the DB
```

**`db/models.py`** should define:
- `GardenProfile` — one row per garden. Fields matching what you hardcoded in Step 1: climate_zone, frost_dates, soil_type, tray_capacity, tray_indoor_capacity, hard_constraints (store as JSON string for now), soft_preferences (JSON string), and a free-text `notes` field for anything that doesn't fit a structured field.
- `Conversation` — one row per session. Fields: session_id, started_at, summary (null for now, used in Step 7).

**`agent/state.py`** should be updated to add a `garden_profile` field to the state:
```python
class GardenState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    garden_profile: dict        # loaded from DB at session start
```

**`agent/graph.py`** should add a `load_profile` node that runs once at the start of each session, reads the garden profile from the database, and writes it into state. This node runs before `llm_call`.

### What the code should do at the end of this step

You should be able to:
1. Close the terminal mid-conversation
2. Reopen it
3. Have the agent remember your garden profile without you re-describing it
4. Edit the garden profile in the database and have the change reflected immediately in the next session

### Context management at this step

Context management now has two layers:
- **Static system prompt** — instructions, persona, behavioral rules (still hardcoded)
- **Dynamic garden profile** — loaded from DB and injected into the prompt at session start

The prompt structure is now assembled rather than hardcoded:
```
[static instructions]

Your garden:
[garden_profile loaded from database]

[conversation history]
```

This is the beginning of the separation between things that never change (instructions) and things that are specific to this user and session (garden data).

### Maps to architecture

- Implements the first part of O2 (persistence architecture) from the design doc
- Establishes the SQLAlchemy pattern that all future models will follow
- `GardenState` gets its first real field beyond `messages`
- SQLite here is intentional — Postgres with pgvector comes in Step 10. SQLAlchemy makes this a one-line config change when the time comes

### Play around with this before moving on

1. **Update a field in the garden profile and verify the agent's advice changes.** Change the frost date, add a new bed, change the soil type. This tests that the dynamic loading is actually working.

2. **Break the database intentionally.** Delete the database file and restart the app. What happens? The app should handle a missing profile gracefully — either by running a simple onboarding flow or giving a clear error. If it crashes with an unhandled exception, add error handling.

3. **Look at what LangGraph's checkpointer is saving.** After a conversation, open the SQLite database with a tool like TablePlus or DB Browser for SQLite and look at the checkpointer tables LangGraph created. Understanding what LangGraph persists automatically versus what you need to persist yourself is important for the steps ahead.

4. **Have a conversation across two sessions and see what the agent remembers.** In session one, tell the agent something specific: "I planted a Cecile Brunner rose in the courtyard bed last week." Close the terminal. Open a new session and ask "do you remember what I planted last week?" What happens? This surfaces the need for proper conversation memory, which you will address in Step 7.

---

## Step 3 — Simple project tracking

### What you should understand after this step

What it means to give the agent a persistent object to reason about, rather than just a static description. You should understand why a project is the right unit of work (it has scope, a goal, and a lifecycle), and what the minimum viable version of a project looks like before adding the full negotiation loop. You should also start thinking about how multiple pieces of state relate to each other — the garden profile is global, a project is scoped to specific beds and resources.

### What to build

The ability to create and retrieve projects. No negotiation loop yet — the user just tells the agent what they want to work on and the agent records it. The agent should then factor active projects into all advice.

**New database model:**
```python
class GardeningProject(Base):
    id: str                      # uuid
    name: str
    goal: str                    # user's stated intent, free text
    status: str                  # 'planning', 'active', 'maintaining', 'paused', 'complete'
    beds: str                    # JSON list of bed names from garden profile
    containers: str              # JSON list of container IDs
    tray_slots: int              # how many indoor trays this reserves
    budget_ceiling: float
    created_at: datetime
    notes: str                   # free text for anything else
```

**New tool: `create_project`**
The agent should be able to call this tool when the user expresses intent to work on something new. The tool creates a project record in the database and returns a confirmation.

**New tool: `list_projects`**
Returns all active and planning projects with their goals and status.

**Updated state:**
```python
class GardenState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    garden_profile: dict
    active_projects: list[dict]   # loaded at session start
```

**Updated graph:** Add a `load_projects` node that runs at session start alongside `load_profile`, fetching all non-complete projects and adding them to state.

### What the code should do at the end of this step

You should be able to say "I want to grow tomatoes and basil from seed in my courtyard growbags this spring" and have the agent:
1. Create a project record in the database
2. Confirm back what it understood — beds, containers, rough timeline
3. In all subsequent conversation turns, factor this project into its advice

You should also be able to say "what am I working on right now?" and get a summary of your active projects.

### Context management at this step

Context management adds a third layer:
- **Static system prompt** — instructions and persona
- **Dynamic garden profile** — loaded from DB
- **Active projects** — loaded from DB and injected as a brief summary

The prompt structure:
```
[static instructions]

Your garden:
[garden_profile]

Current projects:
[list of active projects with names, goals, and status]

[conversation history]
```

Notice that you are injecting project summaries, not full project detail. Full detail for a specific project will be injected as page context in a later step — for now, a brief summary of all projects is enough to keep the agent aware of what's in flight.

### Maps to architecture

- First implementation of `GardeningProject` model
- First use of tools beyond conversation (create_project, list_projects) — same tool-calling pattern as the calculator agent
- Establishes the pattern of loading relevant objects at session start
- The `active_projects` state field is the forerunner of the full project context system

### Play around with this before moving on

1. **Create two projects that compete for the same resource.** For example, two projects that both want to use your 8 indoor tray slots. Notice that the agent doesn't currently detect this conflict. This surfaces the need for the constraint checker in Step 6.

2. **Ask the agent to update a project.** Say "actually I want to add peppers to the courtyard project." Does the agent handle this gracefully? At this step it will probably just discuss it without updating the database — note this gap, it will be addressed properly in Step 8.

3. **Create a project and then ask for advice specific to it.** "What do I need to do to get started on the tomato project?" The advice should reference the specific project, not just general tomato growing advice.

4. **Mark a project as complete and verify it disappears from context.** Update the status in the database directly. Restart the session. The completed project should no longer appear in the active projects list.

---

## Step 4 — Rough task timing

### What you should understand after this step

How to bridge from a goal ("grow tomatoes from seed") to a timeline ("start seeds February 15th, move to red cups March 8th, transplant April 1st"). You should understand how to use external data (frost dates from Open-Meteo) to anchor a schedule, and why task timing in gardening is deadline-driven rather than effort-driven — the window closes whether you're ready or not.

You should also understand the difference between a task that has a hard deadline (transplant before the window closes or the plant becomes root-bound) and a task that has a soft deadline (fertilize sometime this month). This distinction will matter heavily in Step 5.

### What to build

A `generate_schedule` tool that takes a project and produces a list of dated tasks. It should call the Open-Meteo API to get frost dates for your location, then work backwards from the last spring frost date to compute seed start dates.

For the two-step transplant process, it should generate three events per plant:
1. `sow` — start seeds in tray
2. `transplant_to_red_cup` — move seedlings to red cup water reservoir
3. `transplant_to_final` — move to final pot, growbag, or bed

**New database model:**
```python
class Task(Base):
    id: str
    project_id: str
    type: str                        # 'milestone', 'maintenance', 'emergency', 'opportunistic'
    description: str
    window_start: date
    window_end: date
    deadline: date | None            # hard deadline — miss this and the task fails
    reversible: bool
    what_happens_if_skipped: str     # generated by LLM at creation time
    what_happens_if_delayed: str     # generated by LLM at creation time
    status: str                      # 'pending', 'done', 'skipped'
    created_at: datetime
```

**New integration: `integrations/open_meteo.py`**
A function that takes a latitude/longitude and returns the approximate last spring frost date and first fall frost date.

**Note on plant timing data:** For this step, hardcode approximate days-to-transplant for a small list of common plants (tomatoes ~8 weeks, basil ~4 weeks, peppers ~10 weeks) in a Python dict. The Perenual API integration for richer plant data comes later.

### What the code should do at the end of this step

After creating a project with a plant list, saying "can you work out a seed schedule for the tomato project?" should produce a concrete, dated timeline saved to the database:

```
Rhizome: Here's your seed schedule for the courtyard tomato project:

Tomatoes:
- Feb 12: Sow seeds in indoor tray (8 weeks before last frost)
- Mar 8:  Move to red cups (roots filling tray cells)
- Apr 9:  Transplant to final growbag (after last frost, hardened off)

Basil:
- Mar 15: Sow seeds in indoor tray (4 weeks before transplant)
- Apr 9:  Transplant to growbag alongside tomatoes

If you miss the Feb 12 sow date: tomatoes won't be large enough to
transplant until well after your ideal planting window, shortening
your growing season significantly.
```

### Context management at this step

Context management adds a fourth layer — today's upcoming tasks:

```
[static instructions]

Your garden:
[garden_profile]

Current projects:
[active project summaries]

Coming up this week:
[tasks due in the next 7 days, across all projects]

[conversation history]
```

"Coming up this week" is the seed of the daily triage view you will build in Step 5. At this step it is a simple list with no reasoning — just the raw tasks due soon.

### Maps to architecture

- First external API integration (Open-Meteo)
- First implementation of the `Task` model
- The `what_happens_if_skipped` and `what_happens_if_delayed` fields being LLM-generated at task creation time is a core design decision from the design doc — this step is where you validate that it actually produces useful content
- The two-step transplant events (sow → red cup → final) are the specific workflow described in the problem statement

### Play around with this before moving on

1. **Check the frost date against a reliable local source.** Look up Bay Area frost dates on a trusted gardening site and compare to what Open-Meteo returns. Frost date accuracy directly affects your entire seed schedule — if it's off by two weeks, everything downstream is off.

2. **Ask "what happens if I miss the sow date by two weeks?"** The agent should reason about this using the `what_happens_if_delayed` metadata it generated. Is the answer useful?

3. **Try a plant with a very long lead time.** Peppers need 10-12 weeks before transplanting. Does the schedule correctly push the sow date much earlier than tomatoes?

4. **Try to schedule more plants than you have tray space for.** Add 10 varieties and see what happens. The agent currently has no constraint checking on tray slots — it will generate a schedule requiring more than 8 trays without flagging it. Note this gap — it will be addressed in Step 6.

5. **Read the `what_happens_if_skipped` text the LLM generated for each task.** Is it accurate and useful? This is metadata that will drive the triage reasoning in Step 5 — it matters that it's good. If it's generic or vague, adjust the task generation prompt.

---

## Step 5 — Daily triage

### What you should understand after this step

This is the most important step conceptually. You should understand why **priority is not a property of a task** — it is a function of the task, the current date, the user's available time and energy, and what other tasks are competing for attention. A static priority number can't capture this. Reasoning can.

You should also understand urgency escalation — the same task automatically changes urgency as its deadline approaches, without anyone manually updating a field.

**After this step, the core loop is complete.** Grounded advice → persistent garden → projects → tasks → daily triage. Everything after this step makes the core loop smarter and richer.

### What to build

A triage flow that answers "what should I do today?" by reasoning over all pending tasks given the user's session context.

**New node: `session_context_intake`**
Runs at the start of each session. Infers available time, energy level, and any stated focus from the user's opening message. If the user just says "hi" with no context, sets all fields to null and the triage node applies sensible defaults.

```python
class SessionContext(TypedDict):
    available_minutes: int | None
    energy_level: str | None    # 'low', 'medium', 'high'
    focus: str | None           # e.g. "I want to work on the tomato project"
    constraints: str | None     # e.g. "my back hurts, nothing heavy"
```

**New node: `urgency_escalator`**
Runs before triage. Computes current urgency for each pending task based on its `window_end` date:
- `window_end` is 14+ days away → `backlog`
- `window_end` is 3–14 days away → `scheduled`
- `window_end` is 1–3 days away → `time_sensitive`
- `window_end` is today or tomorrow → `blocker`

**Important:** Urgency is **not stored in the database**. It is computed fresh each session and lives only in state for that session. The database stores the window dates; the escalator computes urgency from them at runtime.

**New node: `triage_reasoner`**
An LLM node that receives all pending tasks with their computed urgency, the session context, and the active project summaries. It produces a ranked recommendation grouped into: blockers, today's agenda, daily maintenance, and backlog — with explicit reasoning about tradeoffs.

**Updated state:**
```python
class GardenState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    garden_profile: dict
    active_projects: list[dict]
    pending_tasks: list[dict]
    session_context: SessionContext | None
```

### What the code should do at the end of this step

Opening the app and saying "I've got about an hour this afternoon, my back is a bit sore" should produce something like:

```
Rhizome: Got it — an hour, nothing too heavy. Here's what I'd focus on:

Needs attention today:
→ Move tomato seedlings to red cups
  Window closes in 2 days. If you miss this they'll get root-bound
  and transplant shock will be significantly worse.

Good use of your hour:
→ Check the courtyard bed for aphids and remove by hand
  10-15 minutes, no heavy lifting, and catching it early means
  you won't need neem oil later.

Save for a better day (needs effort):
→ Prepare growbags with soil mix for final tomato transplant
  Due April 9th but this is heavy work — worth saving for when
  your back is feeling better.

Daily:
→ Water seedlings under grow lights (5 min)
→ Check soil moisture in courtyard pots (5 min)
```

The recommendations should change meaningfully if you say "I have 3 hours and I'm feeling energetic" versus "I'm tired, just tell me the one thing I can't skip."

### Context management at this step

The full prompt structure for the core loop:

```
[static instructions — who Rhizome is, behavioral rules]

Your garden:
[garden_profile — loaded from DB]

Current projects:
[active project summaries — loaded from DB]

Coming up / pending tasks:
[tasks with computed urgency — loaded from DB, urgency computed fresh each session]

Today's context:
[session_context — inferred from opening message]

[conversation history]
```

Every slot in the prompt now has a named source and a clear purpose. This is the explicit context slot architecture. Nothing is in the prompt by accident.

### Maps to architecture

- Implements the Task Management workflow
- Validates the core design decision: priority as reasoning, not storage
- The urgency escalation rules established here are the same ones Reactive Monitoring (Step 9) will trigger when an external event occurs
- The triage node's job — reasoning over tradeoffs between "minimize immediate loss" and "maintain gardening velocity" — is the behavior described in the design doc

### Play around with this before moving on

This step has the most to explore because it is the heart of the system.

1. **Test session context sensitivity.** Keep the same pending tasks and try three different openers: "I have 3 hours and lots of energy", "I have 30 minutes", and "I'm exhausted, what's the one thing I can't skip." The recommendations should be meaningfully different each time. If they aren't, your triage prompt needs work.

2. **Test urgency escalation.** Manually set a task's `window_end` to tomorrow in the database. Without changing anything else, run the triage. It should now appear as a blocker. Set it back to two weeks away — it should drop to scheduled or backlog.

3. **Create a conflict the triage has to resolve.** Have a blocker task that takes 2 hours and tell the agent you only have 1 hour. Does it acknowledge the conflict and help you decide what to partially do, or does it just list the blocker without reasoning about your time constraint?

4. **Ask "why are you recommending this order?"** The agent should explain its reasoning. If it can't, the triage prompt needs to explicitly require reasoning, not just a ranked list.

5. **Ask about a task that isn't in the task list.** Say "what about pruning the roses?" If rose pruning isn't a scheduled task, does the agent handle this gracefully? It should distinguish between scheduled tasks (in the database) and general gardening questions (answered from its grounded knowledge).

---

## Step 6 — Negotiation loop

### What you should understand after this step

The human-in-the-loop interrupt pattern in LangGraph — what it means for a graph to pause mid-execution, wait for input, and resume from exactly where it left off. You should understand why this is different from just asking a follow-up question in a normal conversation turn, and why it requires explicit state management.

You should also understand constraint checking as a first-class operation: hard constraints are checked before proposals are generated, not after. If a hard constraint is violated, the agent explains why and stops — it does not generate proposals that work around the constraint.

### What to build

Replace the simple project creation from Step 3 with a proper negotiation loop.

**New nodes:**
- `goal_parser` — extracts intent, target plants, scope (which beds/containers), and implicit constraints from the user's message
- `constraint_checker` — validates against hard constraints: is the bed available? Is the timeline feasible given frost dates? Are all proposed plants non-toxic to dogs? If a hard constraint is violated, the workflow ends here with a clear explanation
- `resource_checker` — checks tray slot availability across all active projects and surfaces conflicts with resolution options
- `proposal_generator` — generates exactly 3 proposals, each satisfying all hard constraints but making different tradeoffs: Option A maximizes the stated goal, Option B maximizes cost-effectiveness, Option C minimizes labor
- `plan_committer` — writes the approved plan to the database and triggers task generation

**LangGraph interrupt:** The graph interrupts after `proposal_generator`, waits for the user to choose or negotiate, then resumes. Read the LangGraph documentation on `interrupt()` before implementing this — it is different from how you might expect it to work.

**Updated project model:** Add `approved_plan` (JSON) and `negotiation_history` (JSON list) fields to `GardeningProject`.

### What the code should do at the end of this step

Saying "I want to grow a cottage garden in the front bed this spring, budget around $100" should produce three concrete proposals, each with a plant list, cost estimate, and honest tradeoff description. The agent should then handle negotiation ("can we combine the lavender from A with the nasturtiums from B?") until you approve a plan, which is then saved and used to generate the task schedule.

### Context management at this step

No new context layers are added. The negotiation history lives in the conversation messages during the session. Once a plan is approved, only the outcome (plant list, plan summary) is persisted to the project record and surfaced in future sessions — the back-and-forth negotiation is not.

### Maps to architecture

- Implements the Planning sub-workflow
- First use of LangGraph's interrupt pattern (O3 from the design doc — the last major blocker resolved)
- The three-proposal structure (maximize goal / maximize cost / minimize effort) is the design decision from the design doc
- Constraint checking before proposal generation is a core architectural principle

### Play around with this before moving on

1. **Try to create a project that violates a hard constraint.** Propose a plant that's toxic to dogs. Does the constraint checker catch it cleanly and explain why?

2. **Try to create a project that needs more trays than are available.** Does the resource checker surface the conflict with useful resolution options?

3. **Abandon a negotiation mid-way and come back later.** Start planning, get to the proposals stage, then change the subject entirely. Come back the next day and try to resume. Does the interrupt state persist correctly?

4. **Negotiate across multiple turns.** Don't accept any of the three options — mix and match, ask to swap one plant for another, ask what happens if you reduce the budget. The agent should handle multi-turn negotiation gracefully without losing track of what's been discussed.

---

## Step 7 — Web search + richer context

### What you should understand after this step

When to use web search versus built-in knowledge — web search is best for current, time-sensitive, or location-specific information (pricing, availability, recent pest outbreaks). You should understand that web search without good grounding produces generic results; web search grounded in your garden profile produces useful ones.

You should also understand conversation summarization — why long conversations eventually need compression, what information is worth preserving in a summary, and what can be safely discarded.

### What to build

**Web search tool:** Add a web search tool. Update the system prompt to specify when to use it: current plant pricing and availability, recent pest reports, anything time-sensitive or location-specific.

**Conversation summarization:** After every 10 conversation turns, the oldest 10 turns are compressed into a summary and stored in the Conversation record. The full turns are removed from the active message state. At the start of the next session, the summary is injected into the prompt before recent messages.

**Recalled context:** Add a `recall_context` tool the agent can call when the user mentions something relating to a specific project or task not currently in the prompt. The tool fetches full detail from the database and adds it to a `recalled_context` list in state. Items in recalled context are dropped when they are no longer being actively discussed.

**Updated state:**
```python
class GardenState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    garden_profile: dict
    active_projects: list[dict]
    pending_tasks: list[dict]
    session_context: SessionContext | None
    conversation_summary: str | None    # from previous session
    recalled_context: list[dict]        # dynamically added mid-session
```

### What the code should do at the end of this step

- "What does lavender cost at Bay Area nurseries right now?" triggers a web search and returns a current, local answer
- After a 15-turn conversation, the oldest turns are summarized and the summary appears at the start of the next session
- Mentioning a specific project causes the agent to fetch and inject its full detail if it's not already in context

### Context management at this step

The full prompt structure is now:

```
[static instructions]

Your garden:
[garden_profile]

Current projects:
[active project summaries]

[if recalled_context is not empty]
Currently discussing:
[recalled project/task/plant full detail]
[end if]

Coming up this week:
[tasks with computed urgency]

Today's context:
[session_context]

[if conversation_summary exists]
From our last conversation:
[conversation_summary]
[end if]

Recent messages:
[last N turns verbatim]
```

This is the complete explicit context slot architecture. Every item in the prompt has a named source, a purpose, and a lifecycle.

### Maps to architecture

- Implements the hybrid context management approach: explicit slots for known-relevant content, web search for current information, RAG (Step 10) for curated knowledge
- Conversation summarization is the foundation for long-running sessions
- Recalled context implements the dynamic context injection pattern from the interface design discussion

### Play around with this before moving on

1. **Test summarization quality.** Have a 15-turn conversation with real decisions (approve a plan, create tasks). Check what the summary captures. Are the key decisions preserved? Adjust the summarization prompt if important information is lost.

2. **Test recalled context lifecycle.** Discuss one project, then pivot to asking about another. Does the agent recall the second project's detail? After you're done with that topic, does it drop from context on the next turn?

3. **Ask something requiring web search AND garden grounding.** "Are there aphids in the Bay Area right now, and would my lavender be at risk?" This should search for local reports AND reason about your specific plants.

---

## Step 8 — Iteration

### What you should understand after this step

The difference between planning (building a plan from scratch with the goal of finding the best possible option) and iterating (amending an existing plan with the goal of minimum disruption). These have different objectives and should be different nodes. Understanding this distinction is important for systems design generally — it comes up whenever you have both creation and update operations on a complex object.

### What to build

**New nodes:**
- `change_parser` — understands what changed and why (user-initiated vs. external event)
- `impact_assessor` — determines which parts of the existing plan are affected
- `amendment_generator` — proposes minimal changes to address the change, not a full new plan
- `plan_updater` — writes the amendment and appends an entry to the project's iteration history

**Updated project model:** Add an `iterations` field (JSON list) to `GardeningProject`. Each entry records: what changed, why, when, and what tasks were affected.

**Trigger:** Either user-initiated ("I want to add marigolds to the tomato project") or agent-detected ("your basil didn't germinate — should I adjust the schedule?").

### What the code should do at the end of this step

"The aphids got my basil, I think I need to start over with new seeds" should produce a minimal amendment: a revised sow date for replacement basil, updated tasks reflecting the new timeline, and an iteration log entry. The tomato schedule and everything else should remain untouched.

### Maps to architecture

- Implements the Iterating sub-workflow
- The iteration log enables project history — you can see what changed and why over the life of a project
- Sets up the pattern that Reactive Monitoring (Step 9) will use to automatically trigger iterations in response to external events

---

## Step 9 — Reactive monitoring

### What you should understand after this step

Event-driven workflows — triggered by an external schedule or event rather than user input. You should understand how this differs architecturally from a user-initiated workflow, and how an external trigger (a frost warning) connects through to user-facing output (a blocker task in the triage view).

### What to build

- `weather_monitor` node — fetches tomorrow's forecast via Open-Meteo and identifies frost events, heat waves, and heavy rain
- `pest_alert_checker` node — queries iNaturalist for pest species observations within 25 miles of your location in the past week
- `vulnerability_assessor` node — cross-references any alerts against active projects and plant inventory to determine what is at risk
- `alert_generator` node — creates new emergency tasks and upgrades urgency on existing tasks for affected projects
- A daily trigger script — run manually each morning, or set up as a cron job

**Alert urgency by project status:**
- `active` project with tender seedlings + frost warning → new `blocker` task: "Bring in tender seedlings tonight"
- `maintaining` project with established plants + same frost warning → informational note only, no blocker

### What the code should do at the end of this step

Running the daily monitoring script should check the forecast, and if frost is predicted, create a blocker task. The next time you open the app and ask "what should I do today?", that task appears at the top of the triage list as a blocker with the reason clearly stated.

### Maps to architecture

- Implements the Reactive Monitoring workflow
- Uses the same urgency levels and triage system established in Step 5
- Connects to Step 8 — a serious event can automatically trigger an iteration on affected projects

---

## Step 10 — RAG knowledge base

### What you should understand after this step

When RAG is more appropriate than web search. RAG is best for curated, stable knowledge where consistency and reliability matter more than recency — companion planting relationships, organic pest management techniques, zone-specific growing guides. Web search is best for current information. Understanding this distinction is the core of the hybrid retrieval strategy.

This step also migrates from SQLite to Postgres, which is the production database.

### What to build

**Postgres migration:**
- Set up a local Postgres instance
- Add the pgvector extension: `CREATE EXTENSION vector;`
- Migrate all existing SQLite models to Postgres — with SQLAlchemy this is a connection string change, not a rewrite

**Knowledge base table:**
```sql
CREATE TABLE knowledge_base (
    id uuid PRIMARY KEY,
    category text,           -- 'companion_planting', 'pest_management', 'propagation', 'zone_9b'
    tags text[],
    content text,
    embedding vector(1536)   -- dimension depends on your embedding model
);
```

**Content ingestion pipeline:** A script that takes curated text files, chunks them, embeds them, and inserts them into the knowledge base.

**Initial content to curate and embed:**
- Companion planting relationships for your target plants
- Bay Area zone 9b specific growing guides
- Organic pest management techniques
- Propagation guides by species

**`rag_retriever` tool:** Queries the knowledge base using vector similarity search filtered by category and tags. Returns the top 3-5 most relevant chunks.

**Updated retrieval strategy:** Tell the agent: use `rag_retriever` for companion planting, organic pest management, and zone-specific growing advice; use web search for pricing, availability, and recent pest reports; use its own knowledge for general horticultural principles.

### What the code should do at the end of this step

"What can I plant alongside my tomatoes to deter pests?" returns advice sourced from your curated companion planting knowledge base — reliably, consistently, and without needing to search the web.

### Maps to architecture

- Completes the full tool suite defined in the architecture
- Postgres with pgvector is the final state of the persistence layer
- The hybrid retrieval strategy (RAG + web search + LLM knowledge) is the production context management approach

---

*End of build plan. Next action: create a GitHub issue for Step 1 and get started.*