import pytest
from langgraph.graph import END

from agent import nodes
from langchain.messages import ToolMessage
from tests.support.fakes import FakeTool, make_ai_message, make_tool_call_message


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

    assert nodes.should_continue(state) == "confirmation_node"


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
def test_confirmation_node_cancels_on_non_affirmative_response(monkeypatch):
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

    assert result["messages"][0].content == "Deletion cancelled. No changes were made."


@pytest.mark.graph
@pytest.mark.parametrize("response", ["yes", "y", "confirm"])
def test_confirmation_node_allows_affirmative_responses(monkeypatch, response):
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

    assert nodes.confirmation_node(state) == {}
