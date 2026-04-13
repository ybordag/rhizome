# main.py
from agent.graph import agent
from agent.telemetry import configure_from_env, emit_message, emit_state_snapshot, start_span
from agent.tools.interactions import resolve_interaction
from langchain.messages import HumanMessage
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


def maybe_render_triage_interaction(config: dict, shown_ids: set[str]) -> None:
    state = agent.get_state(config)
    interaction = (getattr(state, "values", {}) or {}).get("pending_interaction")
    if not isinstance(interaction, dict):
        return
    if interaction.get("interaction_type") != "triage_view":
        return
    if interaction.get("id") in shown_ids:
        return

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
        return

    result = resolve_interaction.invoke(
        {
            "interaction_id": interaction["id"],
            "action_id": resolution["action_id"],
            "inputs": resolution["inputs"],
        }
    )
    print(f"\nRhizome: {result}\n")

def chat():
    print("Rhizome 🌿 — your garden assistant. Type 'quit' to exit.\n")
    configure_from_env()
    history = []
    config = {"configurable": {"thread_id": "main"}}
    shown_interaction_ids = set()

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "quit":
            break

        history.append(HumanMessage(content=user_input))
        emit_message(
            "user",
            user_input,
            payload={"thread_id": config["configurable"]["thread_id"]},
        )
        with start_span(
            "rhizome.chat.turn",
            {
                "rhizome.thread_id": config["configurable"]["thread_id"],
                "rhizome.history_length": len(history),
            },
        ):
            result = agent.invoke({"messages": history}, config=config)

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
        history.append(response)
        response_text = get_response_text(response)
        emit_message(
            "assistant",
            response_text,
            payload={"thread_id": config["configurable"]["thread_id"]},
        )
        print(f"\nRhizome: {response_text}\n")
        maybe_render_triage_interaction(config, shown_interaction_ids)

if __name__ == "__main__":
    chat()
