# The Agent Loop

A complete walkthrough of what happens during one Rhizome session — from startup to the end of a conversation turn.

---

## Overview

Rhizome is a LangGraph state machine. Each conversation turn runs a series of graph nodes; tool calls may spawn additional model/tool loops. The graph persists state between turns via a LangGraph checkpointer: SQLite for quick local runs, Postgres for shared development, staging, and production.

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

`main.py` loads the compiled graph with a sync checkpointer and a thread ID that identifies the conversation. It then enters a `while True` loop reading input from stdin and invoking the graph.

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

Sets the `current_user_id` ContextVar from `config["configurable"]["user_id"]`. This is the user-scoping bridge for tools: tool modules read the current user from `db.database.current_user_id` instead of accepting user-controlled IDs.

This node also:
- Preserves opener text as text-first session focus when no user-supplied context exists
- Persists inferred context on `Thread.session_context` unless the user has explicitly overridden it through the API
- Updates thread metadata such as title, last activity, message count, and last AI preview
- Loads pending high/critical monitor alerts for prompt injection
- Loads pinned thread context from `Thread.pinned_context` and resolves it to prompt text
- Loads session focus context and resolves it to a separate prompt section from pinned context

---

## Step 3: weather_context_loader

Checks whether the current weather snapshot is stale and refreshes from Open-Meteo if needed. The node returns compact weather context for the prompt.

---

## Step 4: triage_reasoner

Builds or loads the current triage snapshot. This is separate from the main conversation LLM call and runs before the user's message is processed when enough garden/task context exists.

The triage reasoner:
1. Queries all active tasks with urgency tiers and deadlines
2. Queries the latest weather impacts
3. Uses the already-loaded `GardenState.session_context` when present, instead of re-inferring time, energy, and focus from the visible message text
4. Makes a fast LLM call asking: "given this garden context, what should this user focus on today?"
5. Persists a `TriageSnapshot` with recommended_task_ids, urgent/routine/project groupings, reasoning summary
6. Records a `triage_view` interaction envelope so the app can present the snapshot as structured UI

The main LLM call can then reference "today's triage" without needing to re-derive it.

Triage failures emit sanitized `triage_snapshot_error` telemetry with error type, truncated error text, and session-context metadata. Raw user text, prompt text, profile notes, provider keys, and full object notes are not emitted.

If no actionable context exists, the graph can skip the main LLM call and route to END for first-session/setup flows.

---

## Step 5: llm_call

The main LLM inference call. It builds the system prompt from the garden profile, temporal context, session context, pinned context, monitor alerts, weather context, latest triage, and recent structured interactions, then sends that prompt plus conversation history to the configured model. The model has access to all 94 tools via LangChain's tool binding.

Pinned context appears in the system prompt under `Pinned context for this thread:`. It is not prepended as a user message and is not stored as separate conversation content. Session focus objects and pinned context render through the same context-ref formatter, include object ids in `[id: ...]` / `(id: ...)` form, and can include a capped `Related open tasks:` shortlist for the selected plant, batch, bed, container, project, task, or incident. The prompt also instructs the model to treat session and pinned context as the current working set and to retrieve object details with a detail/list tool when the focus text requires more context than the compact summary provides. The garden profile is loaded into the system prompt under `You know this specific garden well:`.

Prompt-assembly telemetry emits a sanitized `llm_prompt_context` state snapshot with booleans/counts for which prompt sections were present, session-context source/ref metadata, triage snapshot id/counts, and whether related focus tasks were included. It does not emit the raw garden profile, session context text, pinned context text, or user message content.

The prompt guidelines are grouped by context priority, gardening advice, safety and confirmation, tool use, and duplicate prevention. Context priority tells the model to prefer fresh tool/database results over compact pinned/session summaries, and to avoid tool calls when the compact prompt context is already enough for an accurate answer.

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
7. **Route or execute** — destructive confirmations return to `tool_node` after `confirm`; structured review tools (`accept_project_proposal`, `approve_treatment_plan`, `approve_weather_task_changes`) execute inside `interaction_node` after approval and set `skip_tool_node=True` so the original tool call is not run twice. Cancellations return a cancellation message and route to END.

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
class GardenState(MessagesState):
    temporal_context: Optional[dict[str, Any]]
    session_context: Optional[dict[str, Any]]
    startup_opener: Optional[str]
    weather_context: Optional[dict[str, Any]]
    triage_snapshot: Optional[dict[str, Any]]
    pending_interaction: Optional[dict[str, Any]]
    interaction_history: Optional[list[dict[str, Any]]]
    skip_tool_node: Optional[bool]
    user_id: Optional[int]
    monitor_alerts: Optional[list[dict]]
    pinned_context_text: Optional[str]
```

`messages` comes from LangGraph's `MessagesState`. `user_id` is carried in both graph config and state for observability. `session_context_intake`, `weather_context_loader`, `triage_reasoner`, `llm_call`, and `tool_node` set the `current_user_id` ContextVar before tenant-scoped reads or tool execution. Runtime telemetry records intermediate graph events such as prompt-context assembly, tool start/completion, triage snapshots, and interaction snapshots. Tool telemetry records tool names and argument keys/counts rather than raw argument values. Rhizome does not emit private model chain-of-thought; it emits observable state transitions and sanitized decision/context metadata.

---

## Persistence

Two persistence layers:

**Application database** — SQLAlchemy models in `db/models.py`. Every tool write is persisted here. Plant care, tasks, projects, proposals, activity events, thread metadata, alerts, and API-facing context documents are durable.

SQLAlchemy session hooks emit sanitized `database_change` telemetry after committed ORM inserts, updates, and deletes. Payloads include operation, table, model, record id, tenant context, and changed field names for updates; they do not include row values or free-text fields.

Pinned-context changes are thread metadata writes. `POST /internal/data/threads/{thread_id}/context` and `DELETE /internal/data/threads/{thread_id}/context/{subject_type}/{subject_id}` update only `Thread.pinned_context`; they do not mutate the referenced plant, task, project, incident, bed, container, or batch. Successful pin/unpin operations also write durable `thread_context_pinned` / `thread_context_unpinned` activity events with subject links, in addition to the generic committed-write telemetry.

**LangGraph checkpoint store** — full graph state, including message history and interrupt state. A session can be resumed exactly mid-graph, including mid-approval-flow, by loading the checkpoint for its `thread_id`.

For quick local runs these are SQLite files (`rhizome.db`, `rhizome_checkpoints.db`). For shared dev/staging/prod they live in Postgres under the `rhizome` schema. The streaming API uses async checkpointers (`AsyncSqliteSaver`/`AsyncPostgresSaver`) because `astream_events()` and async state reads require the async LangGraph interface.

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
