from __future__ import annotations

from langgraph.graph import END, START, StateGraph


def patch_all_sessionlocals(monkeypatch, session_factory) -> None:
    from agent.core import nodes
    from agent.domain import triage as triage_runtime
    from agent.tools.operations import activity, care, incidents, interactions, triage, weather
    from agent.tools.garden import beds_containers, plants, profile, search
    from agent.tools.projects import planning, projects, tracker
    from agent.api import routers as api_routers
    from agent.core import nodes as core_nodes

    monkeypatch.setattr(nodes, "SessionLocal", session_factory)
    monkeypatch.setattr(core_nodes, "SessionLocal", session_factory)
    monkeypatch.setattr(activity, "SessionLocal", session_factory)
    monkeypatch.setattr(interactions, "SessionLocal", session_factory)
    monkeypatch.setattr(planning, "SessionLocal", session_factory)
    monkeypatch.setattr(tracker, "SessionLocal", session_factory)
    monkeypatch.setattr(triage, "SessionLocal", session_factory)
    monkeypatch.setattr(triage_runtime, "triage_summary_model", None)
    monkeypatch.setattr(weather, "SessionLocal", session_factory)
    monkeypatch.setattr(care, "SessionLocal", session_factory)
    monkeypatch.setattr(incidents, "SessionLocal", session_factory)
    monkeypatch.setattr(profile, "SessionLocal", session_factory)
    monkeypatch.setattr(projects, "SessionLocal", session_factory)
    monkeypatch.setattr(plants, "SessionLocal", session_factory)
    monkeypatch.setattr(beds_containers, "SessionLocal", session_factory)
    monkeypatch.setattr(search, "SessionLocal", session_factory)
    monkeypatch.setattr(api_routers, "SessionLocal", session_factory)


def build_test_agent(monkeypatch, fake_model, session_factory, checkpointer):
    from agent.core import nodes
    from agent.core.state import GardenState

    patch_all_sessionlocals(monkeypatch, session_factory)
    monkeypatch.setattr(nodes, "model_with_tools", fake_model)

    builder = StateGraph(GardenState)
    builder.add_node("session_context_intake", nodes.session_context_intake)
    builder.add_node("weather_context_loader", nodes.weather_context_loader)
    builder.add_node("triage_reasoner", nodes.triage_reasoner)
    builder.add_node("llm_call", nodes.llm_call)
    builder.add_node("interaction_node", nodes.interaction_node)
    builder.add_node("tool_node", nodes.tool_node)
    builder.add_edge(START, "session_context_intake")
    builder.add_edge("session_context_intake", "weather_context_loader")
    builder.add_edge("weather_context_loader", "triage_reasoner")
    builder.add_conditional_edges(
        "triage_reasoner",
        nodes.should_enter_llm_after_triage,
        ["llm_call", END],
    )
    builder.add_conditional_edges(
        "llm_call",
        nodes.should_continue,
        ["interaction_node", "tool_node", END],
    )
    builder.add_conditional_edges(
        "interaction_node",
        nodes.should_continue_after_interaction,
        ["tool_node", END],
    )
    builder.add_edge("tool_node", "llm_call")
    return builder.compile(checkpointer=checkpointer)
