# agent/graph.py
import sqlite3
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from agent.state import GardenState
from agent.nodes import (
    confirmation_node,
    llm_call,
    session_context_intake,
    should_continue,
    tool_node,
    triage_reasoner,
    weather_context_loader,
)

conn = sqlite3.connect("rhizome_checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)

def build_agent():
    builder = StateGraph(GardenState)

    builder.add_node("session_context_intake", session_context_intake)
    builder.add_node("weather_context_loader", weather_context_loader)
    builder.add_node("triage_reasoner", triage_reasoner)
    builder.add_node("llm_call", llm_call)
    builder.add_node("confirmation_node", confirmation_node)
    builder.add_node("tool_node", tool_node)

    builder.add_edge(START, "session_context_intake")
    builder.add_edge("session_context_intake", "weather_context_loader")
    builder.add_edge("weather_context_loader", "triage_reasoner")
    builder.add_edge("triage_reasoner", "llm_call")
    builder.add_conditional_edges(
        "llm_call",
        should_continue,
        ["confirmation_node", "tool_node", END]
    )
    builder.add_edge("confirmation_node", "tool_node")
    builder.add_edge("tool_node", "llm_call")

    return builder.compile(checkpointer=checkpointer)

agent = build_agent()
