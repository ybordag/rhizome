# agent/graph.py
import os
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

_database_url = os.environ.get("DATABASE_URL", "")
_use_postgres = _database_url.startswith("postgresql") or _database_url.startswith("postgres")

if _use_postgres:
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver
    # psycopg (v3) uses plain postgres:// — strip any SQLAlchemy driver prefix
    _checkpoint_url = _database_url.replace("postgresql+psycopg2://", "postgresql://")
    # Route checkpointer tables to the rhizome schema alongside domain tables.
    _pg_conn = psycopg.connect(_checkpoint_url, autocommit=True, options="-csearch_path=rhizome")
    checkpointer = PostgresSaver(_pg_conn)
    checkpointer.setup()  # creates langgraph checkpoint tables if they don't exist
else:
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    _conn = sqlite3.connect("rhizome_checkpoints.db", check_same_thread=False)
    checkpointer = SqliteSaver(_conn)

def build_agent():
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

agent = build_agent()
