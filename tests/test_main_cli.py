from __future__ import annotations

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from main import (
    build_startup_opener,
    get_latest_display_text,
    prompt_for_interaction_resolution,
    prompt_for_startup_context,
    render_interaction,
)


def test_render_interaction_outputs_sections_and_actions():
    interaction = {
        "interaction_type": "proposal_review",
        "title": "Review proposal",
        "summary": "Approve or revise.",
        "body": "Balanced plan for tomatoes.",
        "sections": [{"title": "Estimates", "items": ["Cost: $50", "Time: 8 hours"]}],
        "actions": [
            {"id": "accept_proposal", "label": "Accept proposal"},
            {"id": "request_revision", "label": "Request revision"},
        ],
    }

    rendered = render_interaction(interaction)

    assert "[proposal_review] Review proposal" in rendered
    assert "Estimates:" in rendered
    assert "1. Accept proposal" in rendered


def test_prompt_for_interaction_resolution_collects_inputs(monkeypatch):
    interaction = {
        "id": "interaction-1",
        "requires_response": True,
        "actions": [
            {
                "id": "request_revision",
                "label": "Request revision",
                "input_schema": [{"name": "note", "label": "Revision note", "required": True}],
            }
        ],
    }
    prompts = iter(["1", "Please make it lower maintenance."])
    monkeypatch.setattr("builtins.input", lambda _: next(prompts))

    resolution = prompt_for_interaction_resolution(interaction)

    assert resolution["interaction_id"] == "interaction-1"
    assert resolution["action_id"] == "request_revision"
    assert resolution["inputs"]["note"] == "Please make it lower maintenance."


def test_prompt_for_interaction_resolution_treats_triage_free_text_as_continue(monkeypatch):
    interaction = {
        "id": "interaction-2",
        "interaction_type": "triage_view",
        "requires_response": False,
        "actions": [
            {"id": "continue", "label": "Continue"},
            {"id": "focus_section", "label": "Focus section"},
        ],
    }
    monkeypatch.setattr("builtins.input", lambda _: "actually, show me my tasks")

    resolution = prompt_for_interaction_resolution(interaction)

    assert resolution["interaction_id"] == "interaction-2"
    assert resolution["action_id"] == "continue"
    assert resolution["passthrough_message"] == "actually, show me my tasks"


def test_prompt_for_interaction_resolution_treats_review_free_text_as_revision(monkeypatch):
    interaction = {
        "id": "interaction-3",
        "interaction_type": "treatment_plan_review",
        "requires_response": True,
        "actions": [
            {"id": "approve_treatment_plan", "label": "Approve treatment plan"},
            {
                "id": "revise_treatment_plan",
                "label": "Request revision",
                "input_schema": [{"name": "note", "label": "Revision note", "required": False}],
            },
        ],
    }
    monkeypatch.setattr("builtins.input", lambda _: "We already approved this, just show me the tasks.")

    resolution = prompt_for_interaction_resolution(interaction)

    assert resolution["interaction_id"] == "interaction-3"
    assert resolution["action_id"] == "revise_treatment_plan"
    assert resolution["inputs"]["note"] == "We already approved this, just show me the tasks."


def test_build_startup_opener_formats_prompted_context():
    opener = build_startup_opener("20", "low", "the tomato project outside")

    assert opener == "I have 20 minutes today. My energy is low. I'm thinking of working on the tomato project outside."


def test_prompt_for_startup_context_collects_time_energy_and_focus(monkeypatch):
    prompts = iter(["20", "high", "the tomatoes in the courtyard"])
    monkeypatch.setattr("builtins.input", lambda _: next(prompts))

    opener = prompt_for_startup_context()

    assert opener == "I have 20 minutes today. My energy is high. I'm thinking of working on the tomatoes in the courtyard."


def test_get_latest_display_text_falls_back_to_last_non_empty_tool_or_assistant_message():
    messages = [
        AIMessage(content="Earlier assistant reply."),
        HumanMessage(content="follow up"),
        ToolMessage(content="Approved treatment plan abc and created follow-up tasks.", tool_call_id="call-1"),
        AIMessage(content=""),
    ]

    text = get_latest_display_text(messages)

    assert text == "Approved treatment plan abc and created follow-up tasks."
