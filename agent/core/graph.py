# agent/graph.py
import os

from dotenv import load_dotenv

from langgraph.graph import StateGraph, START, END
from agent.core.state import GardenState
from agent.core.nodes import (
    interaction_node,
    llm_call,
    session_context_intake,
    should_continue_after_interaction,
    should_enter_llm_after_triage,
    should_continue,
    tool_node,
    triage_reasoner,
    weather_context_loader,
)

# Explicit rather than relying on the `agent.core.nodes` -> `agent.core.model`
# import chain above to have already called this — that ordering is an
# implementation detail of those modules, not a contract (#141 postmortem).
load_dotenv()

_database_url = os.environ.get("DATABASE_URL", "")
_use_postgres = _database_url.startswith("postgresql") or _database_url.startswith("postgres")


def _sqlite_checkpoint_path() -> str:
    return os.environ.get("RHIZOME_CHECKPOINT_SQLITE_PATH", "rhizome_checkpoints.db")


def build_agent(checkpointer):
    """Build the LangGraph agent graph against any checkpointer, sync or async.

    Shared by the module-level sync `agent` below, the FastAPI streaming agent
    (agent/api/app.py's lifespan), and test fixtures — keeping the topology in
    one place avoids it drifting out of sync across those build sites.
    """
    builder = StateGraph(GardenState)

    builder.add_node("session_context_intake", session_context_intake)
    builder.add_node("weather_context_loader", weather_context_loader)
    builder.add_node("triage_reasoner", triage_reasoner)
    builder.add_node("llm_call", llm_call)
    builder.add_node("interaction_node", interaction_node)
    builder.add_node("tool_node", tool_node)

    builder.add_edge(START, "session_context_intake")
    builder.add_edge("session_context_intake", "weather_context_loader")
    builder.add_edge("weather_context_loader", "triage_reasoner")
    builder.add_conditional_edges(
        "triage_reasoner",
        should_enter_llm_after_triage,
        ["llm_call", END],
    )
    builder.add_conditional_edges(
        "llm_call",
        should_continue,
        ["interaction_node", "tool_node", END]
    )
    builder.add_conditional_edges(
        "interaction_node",
        should_continue_after_interaction,
        ["tool_node", END],
    )
    builder.add_edge("tool_node", "llm_call")

    return builder.compile(checkpointer=checkpointer)


def _build_sync_checkpointer():
    """Sync checkpointer for the CLI (main.py) and the non-streaming
    /internal/agent, /internal/agent/resume endpoints, which only ever call
    .invoke()/.get_state() — never the async checkpointer interface.
    """
    if _use_postgres:
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
        # psycopg (v3) uses plain postgres:// — strip any SQLAlchemy driver prefix
        checkpoint_url = _database_url.replace("postgresql+psycopg2://", "postgresql://")
        # Route checkpointer tables to the rhizome schema alongside domain tables.
        conn = psycopg.connect(checkpoint_url, autocommit=True, options="-csearch_path=rhizome")
        saver = PostgresSaver(conn)
        saver.setup()  # creates langgraph checkpoint tables if they don't exist
        return saver
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    conn = sqlite3.connect(_sqlite_checkpoint_path(), check_same_thread=False)
    return SqliteSaver(conn)


# Built once at import time for the CLI and the synchronous agent endpoints.
# SqliteSaver/PostgresSaver work fine without a running event loop, so eager
# module-level construction is safe here — unlike the async-only path below.
checkpointer = _build_sync_checkpointer()
agent = build_agent(checkpointer)


async def build_async_checkpointer():
    """Async-capable checkpointer for the SSE streaming endpoints.

    astream_events()/aget_state() require the checkpointer's async interface
    (aget_tuple/aput/...). SqliteSaver/PostgresSaver raise NotImplementedError
    on those unconditionally — see langgraph/checkpoint/base/__init__.py — so
    streaming needs its own checkpointer built from the async-capable saver
    classes. Must be called from within a running event loop (FastAPI's
    lifespan, or a test's own loop) since both aiosqlite and psycopg's async
    connection require one to construct.

    Returns (checkpointer, aclose) — call `await aclose()` on shutdown.
    """
    if _use_postgres:
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        checkpoint_url = _database_url.replace("postgresql+psycopg2://", "postgresql://")
        conn = await AsyncConnection.connect(
            checkpoint_url, autocommit=True, prepare_threshold=0,
            row_factory=dict_row, options="-csearch_path=rhizome",
        )
        saver = AsyncPostgresSaver(conn)
        await saver.setup()
        return saver, conn.close

    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    conn = await aiosqlite.connect(_sqlite_checkpoint_path())
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver, conn.close
