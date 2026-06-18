# main.py
from datetime import datetime, timezone

from agent.graph import agent
from agent.telemetry import configure_from_env, emit_message, emit_state_snapshot, start_span
from agent.tools.operations.interactions import resolve_interaction
from langchain.messages import HumanMessage, ToolMessage
from langgraph.types import Command

def get_response_text(message) -> str:
    """Extract plain text from a message, handling both string and block formats."""
    if isinstance(message.content, str):
        return message.content
    if isinstance(message.content, list):
        return " ".join(
            block["text"]
            for block in message.content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(message.content)


def get_latest_display_text(messages) -> str:
    """Prefer the latest non-empty assistant/tool text from the current turn."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        text = get_response_text(message).strip()
        if not text:
            continue
        if isinstance(message, ToolMessage):
            return text
        return text
    return ""


def render_interaction(interaction: dict) -> str:
    lines = [
        f"[{interaction.get('interaction_type', 'interaction')}] {interaction.get('title', 'Interaction')}",
        interaction.get("summary", ""),
    ]
    body = interaction.get("body")
    if body:
        lines.extend(["", str(body)])
    for section in interaction.get("sections", []):
        lines.extend(["", f"{section.get('title', 'Details')}:"])
        for item in section.get("items", []):
            lines.append(f"  - {item}")
    lines.extend(["", "Actions:"])
    for idx, action in enumerate(interaction.get("actions", []), start=1):
        lines.append(f"  {idx}. {action.get('label', action.get('id'))}")
    return "\n".join(line for line in lines if line is not None)


def build_startup_opener(
    available_minutes: str,
    energy_level: str,
    work_focus: str,
) -> str:
    parts = []
    minutes = available_minutes.strip()
    if minutes:
        parts.append(f"I have {minutes} minutes today.")
    normalized_energy = energy_level.strip().lower()
    if normalized_energy:
        parts.append(f"My energy is {normalized_energy}.")
    focus = work_focus.strip()
    if focus:
        parts.append(f"I'm thinking of working on {focus}.")
    return " ".join(parts) or "hi"


def prompt_for_startup_context() -> str:
    print("How much time do you have today?")
    while True:
        minutes = input("<enter time in minutes>\n").strip()
        if not minutes or minutes.isdigit():
            break
        print("Please enter the number of minutes you have available, or leave it blank.")

    print("\nHow much energy do you have today:")
    print("Options: low, medium, high")
    while True:
        energy = input("<enter energy>\n").strip().lower()
        if not energy:
            energy = "medium"
        if energy in {"low", "medium", "high"}:
            break
        print("Please choose low, medium, or high.")

    print("\nWhat were you thinking of working on?")
    focus = input("<open answer?>\n").strip()
    print()
    return build_startup_opener(minutes, energy, focus)


def _free_text_interaction_resolution(interaction: dict, raw: str) -> dict | None:
    interaction_type = interaction.get("interaction_type")
    actions = interaction.get("actions", [])
    if interaction_type == "triage_view":
        return {
            "interaction_id": interaction["id"],
            "action_id": "continue",
            "inputs": {},
            "actor": "cli_user",
            "passthrough_message": raw,
        }

    revision_action = next(
        (
            action
            for action in actions
            if action.get("id") in {"request_revision", "revise_treatment_plan"}
        ),
        None,
    )
    if revision_action:
        inputs = {}
        input_schema = revision_action.get("input_schema") or []
        if input_schema:
            inputs[input_schema[0]["name"]] = raw
        return {
            "interaction_id": interaction["id"],
            "action_id": revision_action["id"],
            "inputs": inputs,
            "actor": "cli_user",
        }
    return None


def prompt_for_interaction_resolution(interaction: dict) -> dict:
    actions = interaction.get("actions", [])
    while True:
        raw = input("Select action: ").strip()
        if not raw and not interaction.get("requires_response"):
            return {
                "interaction_id": interaction["id"],
                "action_id": "continue",
                "inputs": {},
                "actor": "cli_user",
            }
        selected = None
        if raw.isdigit():
            index = int(raw) - 1
            if 0 <= index < len(actions):
                selected = actions[index]
        else:
            selected = next((action for action in actions if action.get("id") == raw), None)
            if not selected and raw:
                implicit = _free_text_interaction_resolution(interaction, raw)
                if implicit is not None:
                    return implicit
        if not selected:
            print("Invalid selection. Choose an action number or action id.")
            continue

        inputs = {}
        for field in selected.get("input_schema") or []:
            options = field.get("options")
            prompt = f"{field.get('label', field['name'])}"
            if options:
                prompt += f" ({', '.join(options)})"
            prompt += ": "
            value = input(prompt).strip()
            if field.get("required") and not value:
                print(f"{field.get('label', field['name'])} is required.")
                break
            if value:
                inputs[field["name"]] = value
        else:
            return {
                "interaction_id": interaction["id"],
                "action_id": selected["id"],
                "inputs": inputs,
                "actor": "cli_user",
            }


def maybe_render_triage_interaction(config: dict, shown_ids: set[str]) -> str | None:
    state = agent.get_state(config)
    interaction = (getattr(state, "values", {}) or {}).get("pending_interaction")
    if not isinstance(interaction, dict):
        return None
    if interaction.get("interaction_type") != "triage_view":
        return None
    if interaction.get("id") in shown_ids:
        return None

    print(f"\nRhizome:\n{render_interaction(interaction)}\n")
    resolution = prompt_for_interaction_resolution(interaction)
    shown_ids.add(interaction["id"])
    if resolution["action_id"] == "continue":
        resolve_interaction.invoke(
            {
                "interaction_id": interaction["id"],
                "action_id": "continue",
                "inputs": {},
            }
        )
        return resolution.get("passthrough_message")

    result = resolve_interaction.invoke(
        {
            "interaction_id": interaction["id"],
            "action_id": resolution["action_id"],
            "inputs": resolution["inputs"],
        }
    )
    print(f"\nRhizome: {result}\n")
    return None


def bootstrap_startup_triage(config: dict, shown_ids: set[str], startup_opener: str) -> str | None:
    agent.invoke({"messages": [], "startup_opener": startup_opener}, config=config)
    return maybe_render_triage_interaction(config, shown_ids)


def make_session_config(user_id: int = 1) -> dict:
    thread_id = f"session-{user_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    return {"configurable": {"thread_id": thread_id, "user_id": user_id}}

def chat():
    print("Rhizome 🌿 — your garden assistant. Type 'quit' to exit.\n")
    configure_from_env()
    config = make_session_config()
    shown_interaction_ids = set()
    pending_user_input = bootstrap_startup_triage(
        config,
        shown_interaction_ids,
        prompt_for_startup_context(),
    )

    while True:
        if pending_user_input is not None:
            user_input = pending_user_input.strip()
            pending_user_input = None
            if user_input:
                print(f"You: {user_input}")
        else:
            user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "quit":
            break

        emit_message(
            "user",
            user_input,
            payload={"thread_id": config["configurable"]["thread_id"]},
        )
        with start_span(
            "rhizome.chat.turn",
            {"rhizome.thread_id": config["configurable"]["thread_id"]},
        ):
            result = agent.invoke(
                {"messages": [HumanMessage(content=user_input)]},
                config=config,
            )

            # check graph state for interrupts
            state = agent.get_state(config)
            if state.next:
                # graph is paused — find the interrupt value
                interrupts = [
                    i for task in state.tasks
                    for i in task.interrupts
                ]
                if interrupts:
                    interrupt_payload = interrupts[0].value
                    emit_state_snapshot(
                        "interaction_requested",
                        payload={"interrupt": interrupt_payload},
                        tags=["interaction", "interrupt"],
                    )
                    if isinstance(interrupt_payload, dict):
                        print(f"\nRhizome:\n{render_interaction(interrupt_payload)}\n")
                        resolution = prompt_for_interaction_resolution(interrupt_payload)
                    else:
                        print(f"\nRhizome: {interrupt_payload}\n")
                        user_confirmation = input("You: ").strip()
                        resolution = user_confirmation
                    emit_message(
                        "user",
                        str(resolution),
                        payload={"thread_id": config["configurable"]["thread_id"], "resume": True},
                    )
                    result = agent.invoke(
                        Command(resume=resolution),
                        config=config
                    )

        response = result["messages"][-1]
        response_text = get_response_text(response).strip() or get_latest_display_text(result["messages"])
        emit_message(
            "assistant",
            response_text,
            payload={"thread_id": config["configurable"]["thread_id"]},
        )
        print(f"\nRhizome: {response_text}\n")
        pending_user_input = maybe_render_triage_interaction(config, shown_interaction_ids)

if __name__ == "__main__":
    chat()
