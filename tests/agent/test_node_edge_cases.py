"""
Edge-case tests for interaction_node and confirmation_node:
- Empty string / special-character responses to confirmation prompts
- interaction_node with nonexistent treatment plan ID
- interaction_node with no destructive or interactive calls
- should_continue with mixed tool calls
- normalize_resolution boundary values
"""
from __future__ import annotations

import pytest

from agent import nodes
from agent.interactions import normalize_resolution
from tests.support.factories import make_incident_report, make_profile, make_project, make_treatment_plan
from tests.support.fakes import make_tool_call_message


# ─── normalize_resolution edge cases ─────────────────────────────────────────

@pytest.mark.unit
def test_normalize_resolution_empty_string_becomes_cancel():
    result = normalize_resolution("")
    assert result.action_id == "cancel"


@pytest.mark.unit
def test_normalize_resolution_whitespace_only_becomes_cancel():
    result = normalize_resolution("   ")
    assert result.action_id == "cancel"


@pytest.mark.unit
def test_normalize_resolution_special_chars_not_confirm():
    result = normalize_resolution("!yes")
    assert result.action_id != "confirm"


@pytest.mark.unit
def test_normalize_resolution_yes_with_trailing_chars_not_confirm():
    result = normalize_resolution("yes!")
    assert result.action_id != "confirm"


@pytest.mark.unit
def test_normalize_resolution_dict_form_passes_through():
    result = normalize_resolution({"action_id": "confirm", "interaction_id": "x"})
    assert result.action_id == "confirm"


@pytest.mark.unit
def test_normalize_resolution_dict_missing_action_returns_empty_string():
    result = normalize_resolution({})
    assert result.action_id == ""


# ─── confirmation_node: non-standard response strings ─────────────────────────

@pytest.mark.graph
def test_confirmation_node_empty_string_cancels(monkeypatch, patched_sessionlocal):
    monkeypatch.setattr(nodes, "interrupt", lambda prompt: "")
    state = {
        "messages": [
            make_tool_call_message(
                "Deleting",
                name="delete_project",
                args={"project_id": "proj-1"},
                call_id="call-1",
            )
        ]
    }

    result = nodes.confirmation_node(state)

    assert "Operation cancelled" in result["messages"][0].content
    assert result["interaction_history"][0]["resolution_action"] == "cancel"


@pytest.mark.graph
def test_confirmation_node_special_char_response_cancels(monkeypatch, patched_sessionlocal):
    monkeypatch.setattr(nodes, "interrupt", lambda prompt: "!yes")
    state = {
        "messages": [
            make_tool_call_message(
                "Deleting",
                name="delete_bed",
                args={"bed_id": "bed-1"},
                call_id="call-1",
            )
        ]
    }

    result = nodes.confirmation_node(state)

    assert "Operation cancelled" in result["messages"][0].content


@pytest.mark.graph
def test_confirmation_node_yes_exclamation_cancels(monkeypatch, patched_sessionlocal):
    monkeypatch.setattr(nodes, "interrupt", lambda prompt: "yes!")
    state = {
        "messages": [
            make_tool_call_message(
                "Deleting",
                name="delete_plant",
                args={"plant_id": "p-1"},
                call_id="call-1",
            )
        ]
    }

    result = nodes.confirmation_node(state)

    assert "Operation cancelled" in result["messages"][0].content


# ─── interaction_node: missing treatment plan ─────────────────────────────────

@pytest.mark.graph
def test_interaction_node_missing_treatment_plan_returns_error(db_session, patched_sessionlocal):
    state = {
        "messages": [
            make_tool_call_message(
                "Approve treatment",
                name="approve_treatment_plan",
                args={"treatment_plan_id": "nonexistent-plan-id"},
                call_id="call-1",
            )
        ]
    }

    result = nodes.interaction_node(state)

    assert "No treatment plan found" in result["messages"][0].content
    assert result["pending_interaction"] is None


# ─── interaction_node: no actionable calls ────────────────────────────────────

@pytest.mark.graph
def test_interaction_node_no_destructive_or_interactive_calls_returns_empty():
    state = {
        "messages": [
            make_tool_call_message(
                "Listing",
                name="list_projects",
                args={},
                call_id="call-1",
            )
        ]
    }

    result = nodes.interaction_node(state)

    assert result == {}


# ─── interaction_node: already-approved plans ────────────────────────────────

@pytest.mark.graph
def test_interaction_node_already_approved_plan_not_reopened(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    incident = make_incident_report(db_session, project_id=project.id)
    plan = make_treatment_plan(db_session, incident, status="approved")

    state = {
        "messages": [
            make_tool_call_message(
                "Re-approve",
                name="approve_treatment_plan",
                args={"treatment_plan_id": plan.id},
                call_id="call-1",
            )
        ]
    }

    result = nodes.interaction_node(state)

    assert "already approved" in result["messages"][0].content
    assert result["pending_interaction"] is None


@pytest.mark.graph
def test_interaction_node_rejected_plan_not_reopened(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    incident = make_incident_report(db_session, project_id=project.id)
    plan = make_treatment_plan(db_session, incident, status="rejected")

    state = {
        "messages": [
            make_tool_call_message(
                "Approve rejected",
                name="approve_treatment_plan",
                args={"treatment_plan_id": plan.id},
                call_id="call-1",
            )
        ]
    }

    result = nodes.interaction_node(state)

    assert result["pending_interaction"] is None
    # Should mention the non-draft status
    assert "rejected" in result["messages"][0].content or "already" in result["messages"][0].content


# ─── should_continue: mixed tool calls ───────────────────────────────────────

@pytest.mark.graph
def test_should_continue_destructive_call_routes_to_interaction_node():
    """Even if mixed with non-destructive calls, a destructive call wins."""
    from langchain.messages import AIMessage
    state = {
        "messages": [
            AIMessage(
                content="Multiple calls",
                tool_calls=[
                    {"name": "list_projects", "args": {}, "id": "call-1", "type": "tool_call"},
                    {"name": "delete_project", "args": {"project_id": "p-1"},
                     "id": "call-2", "type": "tool_call"},
                ],
            )
        ]
    }

    assert nodes.should_continue(state) == "interaction_node"


@pytest.mark.graph
def test_should_continue_non_destructive_calls_route_to_tool_node():
    from langchain.messages import AIMessage
    state = {
        "messages": [
            AIMessage(
                content="Multiple reads",
                tool_calls=[
                    {"name": "list_projects", "args": {}, "id": "call-1", "type": "tool_call"},
                    {"name": "get_task", "args": {"task_id": "t-1"}, "id": "call-2", "type": "tool_call"},
                ],
            )
        ]
    }

    assert nodes.should_continue(state) == "tool_node"
