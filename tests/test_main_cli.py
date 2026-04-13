from __future__ import annotations

from main import prompt_for_interaction_resolution, render_interaction


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
