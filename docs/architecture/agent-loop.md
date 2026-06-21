# The Agent Loop

A complete walkthrough of what happens during one Rhizome session — from startup to the end of a conversation turn.

---

## Overview

Rhizome is a LangGraph state machine. Each conversation turn runs a series of graph nodes; tool calls may spawn additional turns. The graph persists state between turns via a SQLite (→ Postgres) checkpointer.

```
session_context_intake
    ↓
weather_context_loader
    ↓
triage_reasoner  ─→ (no tasks) → END
    ↓
llm_call
    ↓
should_continue?
    ├── no tool calls → END
    ├── safe tool call → tool_node → llm_call (loop)
    └── destructive/review call → interaction_node
                                        ├── confirm → tool_node → llm_call
                                        └── cancel  → END
```

---

## Step 1: Session startup (`main.py`)

`main.py` loads the compiled graph with a SQLite checkpointer and a thread ID (identifies the conversation). It then enters a `while True` loop reading input from stdin and invoking the graph.

```python
graph = agent  # compiled LangGraph StateGraph from agent/core/graph.py
result = graph.invoke(
    {"messages": [HumanMessage(content=user_input)]},
    config={"configurable": {"thread_id": thread_id, "user_id": 1}}
)
```

`user_id` is carried in `graph.config["configurable"]["user_id"]`. Tools read it from `db.database.current_user_id` (a `ContextVar` set by `nodes.py` at session start).

---

## Step 2: session_context_intake

Loads the garden profile and sets the `current_user_id` ContextVar. Builds the system prompt by interpolating:
- Garden profile summary
- Temporal context (today's date, day of week, season, frost proximity)
- Latest weather context (fetched or from the last snapshot)
- Latest triage snapshot (loaded or freshly generated)
- Recent interaction history (last 5 resolved interactions)

The resulting system prompt is injected as a `SystemMessage` into the message history. This ensures every LLM call has full garden context without the LLM needing to ask "what garden are we talking about?"

---

## Step 3: weather_context_loader

Checks whether the current weather snapshot is stale (> 6 hours old) and refreshes from Open-Meteo if needed. The weather context is a compact text summary injected into the system prompt by the next step.

---

## Step 4: triage_reasoner

Makes a **secondary LLM call** using a lighter, faster model (`RHIZOME_TRIAGE_MODEL`). This is separate from the main conversation LLM call and runs before the user's message is processed.

The triage reasoner:
1. Queries all active tasks with urgency tiers and deadlines
2. Queries the latest weather impacts
3. Makes a fast LLM call asking: "given this garden context, what should this user focus on today?"
4. Persists a `TriageSnapshot` with recommended_task_ids, urgent/routine/project groupings, reasoning summary

This snapshot is then loaded by `session_context_intake` to build the triage section of the system prompt. The main LLM call can then reference "today's triage" without needing to re-derive it.

If no tasks exist, triage is skipped and the graph goes directly to END (first-session flow).

---

## Step 5: llm_call

The main LLM inference call. Sends the full message history (including the system prompt built in step 2) to the Gemini model. The model has access to all 94 tools via LangChain's tool binding.

If the model returns a plain text response (no tool calls), the conversation turn is complete → `should_continue` routes to END.

If the model calls one or more tools, execution continues.

---

## Step 6: should_continue (routing)

Inspects the last message's tool calls:

- **No tool calls** → END
- **Destructive tool** (`delete_project`, `delete_bed`, `delete_plant`, `remove_container`, `delete_batch`, `remove_plant`, `batch_remove_plants`) → `interaction_node`
- **Review tool** (`accept_project_proposal`, `approve_treatment_plan`, `approve_weather_task_changes`) → `interaction_node`
- **Any other tool** → `tool_node`

---

## Step 7a: tool_node (safe tools)

Executes each tool call from the last message. Tools are looked up in `tools_by_name` (the registry built from `agent/tools/__init__.py`). Each tool:
1. Opens a `SessionLocal()` DB session
2. Performs its logic
3. Returns a string result to the LLM
4. Closes the session in a `finally` block

Tool results are appended as `ToolMessage` objects. Execution returns to `llm_call` so the LLM can process the results and continue the conversation.

Tool calls may chain: the LLM sees the tool result and makes another tool call in the same turn. This loops through `tool_node → llm_call` until the LLM produces a response with no tool calls.

---

## Step 7b: interaction_node (approvals and confirmations)

Handles consequential operations. The flow:

1. **Build the interaction envelope** — a structured dict with title, summary, body, sections (content), and actions (buttons like "approve", "cancel", "confirm")
2. **Persist an `InteractionRecord`** — so the interaction can be referenced and prevented from re-opening if already resolved
3. **Call `interrupt(envelope)`** — LangGraph pauses the graph here and yields the envelope to the caller (the CLI renderer)
4. **User responds** — the CLI accepts the user's text response
5. **normalize_resolution** — maps text ("yes"/"y"/"confirm" → `confirm`, "no"/"cancel" → `cancel`) to an `InteractionResolution`
6. **Record resolution** — `resolve_interaction_record` updates the `InteractionRecord` status and writes an `interaction_resolved` activity event
7. **Route** — if `confirm`, execution continues to `tool_node` (the original tool call proceeds). If `cancel`, returns a cancellation message and sets `skip_tool_node=True` to route to END.

**Reuse detection** — if the interaction_node is asked to re-open an existing pending interaction (e.g. re-approve an already-approved plan), it returns the existing record's status and skips the interrupt. This prevents duplicate approval flows.

---

## Step 8: should_continue_after_interaction

After `interaction_node` resolves, this routing function decides:
- `skip_tool_node=True` (cancelled) → END
- Last message has tool calls → `tool_node` (confirmed, proceed with the original tool)
- No tool calls → END

---

## State: GardenState

The state dict that flows through the graph:

```python
class GardenState(TypedDict):
    messages: Annotated[list, add_messages]     # full conversation (auto-appended)
    pending_interaction: Optional[dict]          # current interaction envelope
    interaction_history: list[dict]              # resolved interactions this session
    skip_tool_node: bool                         # routing hint from interaction_node
```

`user_id` is NOT in state — it's in `graph.config["configurable"]["user_id"]` and accessed through the `current_user_id` ContextVar.

---

## Persistence

Two databases:

**`rhizome.db`** — application state. Every tool write is persisted here. Plant care, tasks, projects, proposals, activity events — all durable, all available to the next session.

**`rhizome_checkpoints.db`** — LangGraph checkpoints. The full `GardenState` (message history, pending interactions) is checkpointed after every node. A session can be resumed exactly mid-graph — including mid-approval-flow — by loading the checkpoint.

Both are SQLite in development. Both migrate to Postgres together (the LangGraph Postgres checkpointer is a drop-in replacement for `SqliteSaver`).

---

## Tool call anatomy

Every tool follows this pattern:

```python
@tool
def complete_task(task_id: str, actual_minutes: Optional[int] = None) -> str:
    """Complete a task and unblock dependent work when possible."""
    session = SessionLocal()
    try:
        task = _task_or_error(session, task_id)
        # ... domain logic ...
        session.commit()
        return f"Completed task '{task.title}'."
    except Exception as e:
        session.rollback()
        return f"Failed to complete task: {str(e)}"
    finally:
        session.close()
```

Tools return strings — the LLM reads tool output as text. Complex return values are formatted as human-readable text with key details (IDs, status, what changed). Tools never raise exceptions to the LLM; all errors become return strings.

Domain logic lives in `agent/domain/` modules (tracker.py, planner.py, care.py, etc.). Tool files are thin wrappers that open sessions, call domain functions, and format results.
