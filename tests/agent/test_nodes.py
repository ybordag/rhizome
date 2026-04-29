import pytest
from langgraph.graph import END

from agent import nodes
from langchain.messages import ToolMessage
from tests.support.fakes import FakeTool, make_ai_message, make_tool_call_message
from tests.support.factories import make_incident_report, make_profile, make_project, make_treatment_plan


@pytest.mark.graph
def test_should_continue_returns_end_for_plain_assistant_message():
    state = {"messages": [make_ai_message("Just a response.")]}

    assert nodes.should_continue(state) == END


@pytest.mark.graph
def test_should_continue_routes_to_tool_node_for_non_destructive_tool():
    state = {
        "messages": [
            make_tool_call_message(
                "Calling tool",
                name="list_projects",
                args={},
                call_id="call-1",
            )
        ]
    }

    assert nodes.should_continue(state) == "tool_node"


@pytest.mark.graph
def test_should_continue_routes_to_confirmation_node_for_destructive_tool():
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

    assert nodes.should_continue(state) == "interaction_node"


@pytest.mark.graph
def test_should_continue_routes_to_interaction_node_for_review_tool():
    state = {
        "messages": [
            make_tool_call_message(
                "Accepting proposal",
                name="accept_project_proposal",
                args={"project_id": "proj-1", "proposal_id": "proposal-1"},
                call_id="call-1",
            )
        ]
    }

    assert nodes.should_continue(state) == "interaction_node"


@pytest.mark.graph
def test_tool_node_invokes_expected_tool(monkeypatch):
    fake_tool = FakeTool("list_projects", "tool output")
    monkeypatch.setattr(nodes, "tools_by_name", {"list_projects": fake_tool})
    state = {
        "messages": [
            make_tool_call_message(
                "Calling tool",
                name="list_projects",
                args={"status": "active"},
                call_id="call-1",
            )
        ]
    }

    result = nodes.tool_node(state)

    assert fake_tool.calls == [{"status": "active"}]
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ToolMessage)
    assert result["messages"][0].tool_call_id == "call-1"
    assert result["messages"][0].content == "tool output"


@pytest.mark.graph
def test_tool_node_returns_error_for_unknown_tool(monkeypatch):
    monkeypatch.setattr(nodes, "tools_by_name", {})
    state = {
        "messages": [
            make_tool_call_message(
                "Calling missing tool",
                name="get_plant",
                args={"plant_id": "p-1"},
                call_id="call-1",
            )
        ]
    }

    result = nodes.tool_node(state)

    assert len(result["messages"]) == 1
    assert "Unknown tool 'get_plant'" in result["messages"][0].content


@pytest.mark.graph
def test_confirmation_node_returns_empty_when_no_destructive_calls():
    state = {
        "messages": [
            make_tool_call_message(
                "Calling tool",
                name="list_projects",
                args={},
                call_id="call-1",
            )
        ]
    }

    assert nodes.confirmation_node(state) == {}


@pytest.mark.graph
def test_confirmation_node_cancels_on_non_affirmative_response(monkeypatch, patched_sessionlocal):
    monkeypatch.setattr(nodes, "interrupt", lambda prompt: "no")
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

    assert result["messages"][0].content == "Operation cancelled. No changes were made."
    assert result["interaction_history"][0]["resolution_action"] == "cancel"


@pytest.mark.graph
@pytest.mark.parametrize("response", ["yes", "y", "confirm"])
def test_confirmation_node_allows_affirmative_responses(monkeypatch, patched_sessionlocal, response):
    monkeypatch.setattr(nodes, "interrupt", lambda prompt: response)
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

    assert result["interaction_history"][0]["resolution_action"] == "confirm"


@pytest.mark.graph
def test_interaction_node_does_not_reopen_already_approved_treatment_plan(db_session, patched_sessionlocal):
    profile = make_profile(db_session)
    project = make_project(db_session, profile)
    incident = make_incident_report(db_session, project_id=project.id, incident_type="blight")
    plan = make_treatment_plan(db_session, incident, status="approved")
    state = {
        "messages": [
            make_tool_call_message(
                "Approve treatment again",
                name="approve_treatment_plan",
                args={"treatment_plan_id": plan.id},
                call_id="call-1",
            )
        ]
    }

    result = nodes.interaction_node(state)

    assert "already approved" in result["messages"][0].content
    assert result["pending_interaction"] is None
