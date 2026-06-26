from datetime import datetime, timedelta, timezone

import pytest
from langgraph.graph import END

from agent.core import nodes
from langchain.messages import HumanMessage, ToolMessage
from db.models import MonitorAlert
from tests.support.fakes import FakeBoundModel, FakeTool, make_ai_message, make_tool_call_message
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


# ---------------------------------------------------------------------------
# _monitor_alerts_text
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_monitor_alerts_text_formats_critical_and_high():
    state = {
        "monitor_alerts": [
            {"severity": "critical", "title": "Frost warning", "body": "3 tasks auto-deferred."},
            {"severity": "high", "title": "Storm incoming", "body": "Secure supports."},
        ]
    }
    text = nodes._monitor_alerts_text(state)
    assert "⚠ CRITICAL: Frost warning" in text
    assert "3 tasks auto-deferred." in text
    assert "⚠ HIGH: Storm incoming" in text


@pytest.mark.unit
def test_monitor_alerts_text_empty_when_no_alerts():
    assert nodes._monitor_alerts_text({"monitor_alerts": []}) == ""
    assert nodes._monitor_alerts_text({}) == ""


@pytest.mark.graph
def test_llm_call_injects_session_context_text_into_system_prompt(monkeypatch, patched_sessionlocal, db_session):
    make_profile(db_session)
    fake_model = FakeBoundModel([make_ai_message("ok")])
    monkeypatch.setattr(nodes, "model_with_tools", fake_model)

    state = {
        "messages": [HumanMessage(content="What should I do next?")],
        "temporal_context": {"current_date": "2026-06-25", "timezone": "America/Los_Angeles"},
        "weather_context": {"alerts_summary": "No weather alerts."},
        "triage_snapshot": {"formatted": "No triage snapshot available."},
        "session_context_text": "\n".join([
            "Time available: 45 minutes",
            "Energy: low but focused",
            "Thread focus: How do I fertilize the cherry tomatoes?",
            "Focus objects:",
            "- batch: Courtyard Tomatoes March 2026 (batch-1)",
        ]),
        "pinned_context_text": "- plant: Basil (plant-1)",
    }

    result = nodes.llm_call(state, {"configurable": {"user_id": "1"}})

    assert result["messages"][0].content == "ok"
    system_prompt = fake_model.invocations[0][0].content
    assert "Session context for this thread:" in system_prompt
    assert "Time available: 45 minutes" in system_prompt
    assert "Thread focus: How do I fertilize the cherry tomatoes?" in system_prompt
    assert "- batch: Courtyard Tomatoes March 2026 (batch-1)" in system_prompt
    assert "Pinned context for this thread:\n- plant: Basil (plant-1)" in system_prompt
    assert fake_model.invocations[0][1].content == "What should I do next?"


# ---------------------------------------------------------------------------
# session_context_intake — monitor_alerts injection
# ---------------------------------------------------------------------------

def _make_alert(db_session, *, user_id=1, severity="critical", status="pending",
                hours_until_expiry=24, alert_type="weather_critical"):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    alert = MonitorAlert(
        expires_at=now + timedelta(hours=hours_until_expiry),
        user_id=user_id,
        alert_type=alert_type,
        severity=severity,
        title=f"{severity} alert",
        body="Test body.",
        status=status,
        dismissed_at=now if status == "dismissed" else None,
    )
    db_session.add(alert)
    db_session.commit()
    return alert


@pytest.mark.integration
def test_session_context_intake_returns_pending_monitor_alerts(db_session, patched_sessionlocal):
    _make_alert(db_session, severity="critical")
    result = nodes.session_context_intake({"messages": []}, {"configurable": {"user_id": "1"}})
    assert len(result["monitor_alerts"]) == 1
    assert result["monitor_alerts"][0]["severity"] == "critical"
    assert result["monitor_alerts"][0]["title"] == "critical alert"


@pytest.mark.integration
def test_session_context_intake_excludes_dismissed_alerts(db_session, patched_sessionlocal):
    _make_alert(db_session, severity="critical", status="dismissed")
    result = nodes.session_context_intake({"messages": []}, {"configurable": {"user_id": "1"}})
    assert result["monitor_alerts"] == []


@pytest.mark.integration
def test_session_context_intake_excludes_expired_alerts(db_session, patched_sessionlocal):
    _make_alert(db_session, severity="critical", hours_until_expiry=-1)
    result = nodes.session_context_intake({"messages": []}, {"configurable": {"user_id": "1"}})
    assert result["monitor_alerts"] == []


@pytest.mark.integration
def test_session_context_intake_excludes_medium_and_low_severity(db_session, patched_sessionlocal):
    _make_alert(db_session, severity="medium", alert_type="working_window")
    _make_alert(db_session, severity="low", alert_type="working_window")
    _make_alert(db_session, severity="critical", alert_type="weather_critical")
    result = nodes.session_context_intake({"messages": []}, {"configurable": {"user_id": "1"}})
    assert len(result["monitor_alerts"]) == 1
    assert result["monitor_alerts"][0]["severity"] == "critical"


@pytest.mark.integration
def test_session_context_intake_excludes_other_users_alerts(db_session, patched_sessionlocal):
    _make_alert(db_session, user_id=2, severity="critical")
    result = nodes.session_context_intake({"messages": []}, {"configurable": {"user_id": "1"}})
    assert result["monitor_alerts"] == []


@pytest.mark.integration
def test_session_context_intake_returns_empty_list_when_no_alerts(db_session, patched_sessionlocal):
    result = nodes.session_context_intake({"messages": []}, {"configurable": {"user_id": "1"}})
    assert result["monitor_alerts"] == []


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
