from __future__ import annotations

from langgraph.graph import END, START, StateGraph


def patch_all_sessionlocals(monkeypatch, session_factory) -> None:
    from agent import nodes
    from agent.tools import activity, beds_containers, plants, profile, projects, search

    monkeypatch.setattr(nodes, "SessionLocal", session_factory)
    monkeypatch.setattr(activity, "SessionLocal", session_factory)
    monkeypatch.setattr(profile, "SessionLocal", session_factory)
    monkeypatch.setattr(projects, "SessionLocal", session_factory)
    monkeypatch.setattr(plants, "SessionLocal", session_factory)
    monkeypatch.setattr(beds_containers, "SessionLocal", session_factory)
    monkeypatch.setattr(search, "SessionLocal", session_factory)


def build_test_agent(monkeypatch, fake_model, session_factory, checkpointer):
    from agent import nodes
    from agent.state import GardenState

    patch_all_sessionlocals(monkeypatch, session_factory)
    monkeypatch.setattr(nodes, "model_with_tools", fake_model)

    builder = StateGraph(GardenState)
    builder.add_node("llm_call", nodes.llm_call)
    builder.add_node("confirmation_node", nodes.confirmation_node)
    builder.add_node("tool_node", nodes.tool_node)
    builder.add_edge(START, "llm_call")
    builder.add_conditional_edges(
        "llm_call",
        nodes.should_continue,
        ["confirmation_node", "tool_node", END],
    )
    builder.add_edge("confirmation_node", "tool_node")
    builder.add_edge("tool_node", "llm_call")
    return builder.compile(checkpointer=checkpointer)
