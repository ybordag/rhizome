# agent/graph.py
import sqlite3
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from agent.state import GardenState
from agent.nodes import llm_call, tool_node, should_continue, confirmation_node

conn = sqlite3.connect("rhizome_checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)

def build_agent():
    builder = StateGraph(GardenState)

    builder.add_node("llm_call", llm_call)
    builder.add_node("confirmation_node", confirmation_node)
    builder.add_node("tool_node", tool_node)

    builder.add_edge(START, "llm_call")
    builder.add_conditional_edges(
        "llm_call",
        should_continue,
        ["confirmation_node", "tool_node", END]
    )
    builder.add_edge("confirmation_node", "tool_node")
    builder.add_edge("tool_node", "llm_call")

    return builder.compile(checkpointer=checkpointer)

agent = build_agent()